"""Main plugin entry point for CheckInBot.

This NoneBot plugin implements a robot that:
1. Communicates with an exam server via WebSocket
2. Handles QQ verification flows
3. Processes exam paper submissions
4. Manages group join requests
"""
import asyncio
from typing import Optional

from loguru import logger
from nonebot import get_bots, on_request, on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, GroupRequestEvent, GroupDecreaseNoticeEvent
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.plugin import PluginMetadata

from .config import load_config
from .group_handler import GroupJoinHandler
from .leave_group_handler import LeaveGroupInvalidateHandler
from .paper_handler import PaperSubmissionHandler
from .verification_handler import QQVerificationHandler
from .websocket_client import WebSocketClient
from .welcome_handler import WelcomeMessageHandler

__plugin_meta__ = PluginMetadata(
    name="CheckInBot",
    description="机器人应用，实现与服务器的通讯功能及QQ号验证流程",
    usage="自动处理QQ群验证和考试提交",
)

# Global instances
_ws_client: Optional[WebSocketClient] = None
_verification_handler: Optional[QQVerificationHandler] = None
_paper_handler: Optional[PaperSubmissionHandler] = None
_group_handler: Optional[GroupJoinHandler] = None
_welcome_handler: Optional[WelcomeMessageHandler] = None
_leave_group_handler: Optional[LeaveGroupInvalidateHandler] = None
_config = None


def get_ws_client() -> Optional[WebSocketClient]:
    """Get global WebSocket client instance."""
    return _ws_client


def get_config():
    """Get global config instance."""
    return _config


def initialize_handlers():
    """Initialize all handler instances."""
    global _ws_client, _verification_handler, _paper_handler, _group_handler, _welcome_handler, _leave_group_handler, _config

    _config = load_config()
    _ws_client = WebSocketClient(_config)
    _verification_handler = QQVerificationHandler(_ws_client)
    _paper_handler = PaperSubmissionHandler(_ws_client)
    _welcome_handler = WelcomeMessageHandler(_config.welcome_message)
    _leave_group_handler = LeaveGroupInvalidateHandler(
        _ws_client,
        enabled=_config.leave_group_invalidate.enabled
    )
    _group_handler = GroupJoinHandler(
        _ws_client, _verification_handler, _paper_handler,
        set(_config.allowed_join_groups) if _config.allowed_join_groups else None,
        _welcome_handler
    )

    # Register WebSocket message handlers
    _ws_client.register_handler("qq_verify_check", _handle_verify_check)
    _ws_client.register_handler("qq_verify_request", _handle_verify_request)
    _ws_client.register_handler("notification_paper_submit", _handle_paper_submit)
    _ws_client.register_handler("exam_records_response", _handle_exam_records)
    _ws_client.register_handler("blacklist_full", _handle_blacklist_full)
    _ws_client.register_handler("blacklist_add", _handle_blacklist_add)
    _ws_client.register_handler("blacklist_remove", _handle_blacklist_remove)

    # Register notification handlers
    for notification_type in [
        "notification_submit_frequency",
        "notification_login_failure",
        "notification_login_success",
        "notification_quick_submit",
        "notification_exam_start",
    ]:
        _ws_client.register_handler(
            notification_type, _handle_notification
        )

    logger.info("All handlers initialized")


async def _handle_verify_check(data: dict):
    """Handle qq_verify_check message."""
    bot = _get_bot()
    if bot and _verification_handler:
        await _verification_handler.handle_verify_check(bot, data)


async def _handle_verify_request(data: dict):
    """Handle qq_verify_request message."""
    bot = _get_bot()
    if bot and _verification_handler:
        await _verification_handler.handle_verify_request(bot, data)


async def _handle_paper_submit(data: dict):
    """Handle paper submission notification from server."""
    if _paper_handler and _group_handler:
        action = await _paper_handler.handle_paper_submit(data)
        if action:
            _group_handler.update_paper_submission(data.get("data", {}))


async def _handle_exam_records(data: dict):
    """Handle exam records response from server."""
    if _group_handler:
        await _group_handler.process_exam_records_response(data)


async def _handle_blacklist_full(data: dict):
    """Handle full blacklist list."""
    logger.info(
        f"Received full blacklist: "
        f"{len(data.get('data', {}).get('list', []))} entries"
    )


async def _handle_blacklist_add(data: dict):
    """Handle blacklist add notification."""
    logger.info(f"Blacklist add: {data.get('data', {})}")


async def _handle_blacklist_remove(data: dict):
    """Handle blacklist remove notification."""
    logger.info(f"Blacklist remove: {data.get('data', {})}")


async def _handle_notification(data: dict):
    """Handle general notification messages."""
    logger.info(f"Received notification: {data.get('type')}")


def _get_bot() -> Optional[Bot]:
    """Get the first available bot instance."""
    bots = get_bots()
    if bots:
        return list(bots.values())[0]
    return None


async def start_websocket_connection():
    """Start WebSocket connection in background."""
    if _ws_client:
        logger.info("Starting WebSocket connection...")
        asyncio.create_task(_ws_client.connect())


# NoneBot event handlers

# Handle group join requests
group_request_matcher = on_request(priority=5)


@group_request_matcher.handle()
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    """Handle group join request events."""
    if event.sub_type in ("invite", "add"):
        if _group_handler:
            await _group_handler.handle_group_join(
                bot,
                event.group_id,
                event.user_id,
                event.comment or "",
                event.flag or "",
            )


# Handle group messages for verification purposes
group_message_matcher = on_message(priority=10, block=False)


@group_message_matcher.handle()
async def handle_group_message(bot: Bot, event: GroupMessageEvent):
    """Handle incoming group messages for verification purposes."""
    message_text = event.message.extract_plain_text().strip()

    # Check if this message matches any pending verification
    if _ws_client:
        pending = _ws_client.get_pending_verification(str(event.user_id))
        if pending:
            if message_text == pending["verify_content"]:
                logger.info(
                    f"Verification match: user {event.user_id} "
                    f"sent correct content"
                )
                _ws_client.remove_pending_verification(str(event.user_id))


# Handle group decrease events (member leaves or is kicked)
group_decrease_matcher = on_notice(priority=5)


@group_decrease_matcher.handle()
async def handle_group_decrease(bot: Bot, event: GroupDecreaseNoticeEvent):
    """Handle group decrease events (member leaves or is kicked)."""
    if _leave_group_handler:
        await _leave_group_handler.handle_group_decrease(
            bot,
            event.group_id,
            event.user_id,
            event.sub_type
        )
