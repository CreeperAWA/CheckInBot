"""QQ verification flow handler."""
import asyncio
import time
from typing import Optional, Dict

from loguru import logger
from nonebot.adapters.onebot.v11 import Bot

from .config import load_config
from .websocket_client import WebSocketClient


class VerificationRecord:
    """Tracks a single verification session."""

    def __init__(self, qq: str, message_id: str, verify_content: str, timeout: int):
        self.qq = qq
        self.message_id = message_id
        self.verify_content = verify_content
        self.timeout = timeout
        self.start_time = time.time()
        self.completed = False
        self.result: Optional[str] = None


class QQVerificationHandler:
    """Handles QQ verification flow with the exam server."""

    def __init__(self, ws_client: WebSocketClient):
        self.ws_client = ws_client
        self._active_verifications: Dict[str, VerificationRecord] = {}

    async def handle_verify_check(self, bot: Optional[Bot], data: dict):
        """Handle QQ verification check request from server.

        Checks if the QQ number is present in configured groups.
        Returns true (need_verify) if NOT in groups, false if in groups.
        """
        qq = data.get("data", {}).get("qq", "")
        message_id = data.get("messageId", "")

        if not qq or not message_id:
            logger.error("Invalid verify_check message: missing qq or messageId")
            return

        logger.info(f"QQ verify check for: {qq}")

        # Check if QQ is in any of the configured groups
        is_in_group = await self._check_qq_in_groups(bot, qq)

        # If in group, don't need verify; if not in group, need verify
        need_verify = not is_in_group
        response = {
            "type": "qq_verify_check_response",
            "messageId": message_id,
            "data": {
                "qq": qq,
                "need_verify": need_verify
            }
        }

        await self.ws_client.send_message(response)
        logger.info(f"Sent verify check response for {qq}: need_verify={need_verify}")

    async def handle_verify_request(self, bot: Optional[Bot], data: dict):
        """Handle QQ verification request from server.

        Contains QQ number and verify_content string. We check group join
        requests for matching QQ and verify_content.
        """
        qq = data.get("data", {}).get("qq", "")
        verify_content = data.get("data", {}).get("verify_content", "")
        message_id = data.get("messageId", "")

        if not qq or not verify_content or not message_id:
            logger.error("Invalid verify_request message: missing required fields")
            return

        logger.info(f"QQ verify request for {qq} with content: {verify_content}")

        # Store verification record
        timeout = self.ws_client.get_verification_timeout()
        record = VerificationRecord(qq, message_id, verify_content, timeout)
        self._active_verifications[qq] = record

        # Start timeout monitoring
        asyncio.create_task(self._monitor_verification_timeout(qq))

        # Try to find matching group join request
        await self._process_group_join_for_verification(bot, qq, verify_content, message_id)

    async def _process_group_join_for_verification(
        self,
        bot: Optional[Bot],
        qq: str,
        verify_content: str,
        message_id: str
    ):
        """Search for group join requests that match the verification content.

        This is triggered when we receive a verify_request from the server.
        We need to check if there's a pending group join request from this QQ
        with the matching verify_content.
        """
        # The group join request will be handled by the GroupJoinHandler
        # when it receives the GroupRequestEvent. We just need to store
        # the expected verification content so the group handler can match it.
        logger.info(f"Stored verification expectation for QQ {qq}")

    async def check_join_request(
        self,
        bot: Optional[Bot],
        qq: str,
        join_comment: str
    ) -> Optional[str]:
        """Check if a group join request matches an active verification.

        Returns:
            "success" - join comment contains verification content
            "failed" - join comment doesn't contain verification content
            None - no active verification for this QQ
        """
        record = self._active_verifications.get(qq)
        if not record or record.completed:
            return None

        if record.verify_content in join_comment:
            record.completed = True
            record.result = "success"
            logger.info(f"Verification SUCCESS for QQ {qq}")
            return "success"
        else:
            record.completed = True
            record.result = "failed"
            logger.info(f"Verification FAILED for QQ {qq}")
            return "failed"

    def clear_active_verification(self, qq: str):
        """Clear active verification for a QQ number."""
        if qq in self._active_verifications:
            del self._active_verifications[qq]
            logger.debug(f"Cleared active verification for QQ {qq}")

    async def send_verify_response(
        self,
        qq: str,
        message_id: str,
        status: str
    ):
        """Send verification response to server."""
        response = {
            "type": "qq_verify_response",
            "messageId": message_id,
            "data": {
                "qq": qq,
                "status": status
            }
        }

        await self.ws_client.send_message(response)
        logger.info(f"Sent verify response for {qq}: status={status}")

    async def _monitor_verification_timeout(self, qq: str):
        """Monitor verification timeout and send timeout response."""
        record = self._active_verifications.get(qq)
        if not record:
            return

        await asyncio.sleep(record.timeout)

        if not record.completed:
            record.completed = True
            record.result = "timeout"
            logger.warning(f"Verification TIMEOUT for QQ {qq}")

            await self.send_verify_response(qq, record.message_id, "timeout")

    def has_active_verification(self, qq: str) -> bool:
        """Check if QQ has an active (non-completed) verification."""
        record = self._active_verifications.get(qq)
        return record is not None and not record.completed

    def get_verify_message_id(self, qq: str) -> Optional[str]:
        """Get the message_id for an active verification."""
        record = self._active_verifications.get(qq)
        if record and not record.completed:
            return record.message_id
        return None

    async def _check_qq_in_groups(self, bot: Optional[Bot], qq: str) -> bool:
        """Check if a QQ number is in any of the configured groups."""
        config = load_config()

        for group_id in config.group_list:
            try:
                member_info = await bot.get_group_member_info(
                    group_id=group_id,
                    user_id=int(qq),
                    no_cache=False
                )
                if member_info:
                    logger.info(f"QQ {qq} found in group {group_id}")
                    return True
            except Exception as e:
                logger.debug(f"QQ {qq} not in group {group_id}: {e}")
                continue

        return False

    def cleanup_expired_verifications(self):
        """Remove completed verifications older than 1 hour."""
        now = time.time()
        expired_qqs = []
        for qq, record in self._active_verifications.items():
            if record.completed and (now - record.start_time > 3600):
                expired_qqs.append(qq)

        for qq in expired_qqs:
            del self._active_verifications[qq]
