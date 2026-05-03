"""Group join request handler."""
import asyncio
from typing import Dict, Optional

from loguru import logger
from nonebot.adapters.onebot.v11 import Bot

from .paper_handler import PaperSubmissionHandler
from .verification_handler import QQVerificationHandler
from .websocket_client import WebSocketClient
from .welcome_handler import WelcomeMessageHandler


class PendingJoinRequest:
    """Stores a pending group join request."""

    def __init__(self, group_id: int, user_id: int, comment: str, flag: str = ""):
        self.group_id = group_id
        self.user_id = user_id
        self.comment = comment
        self.flag = flag
        self.timestamp = asyncio.get_event_loop().time()
        self.paper_data: Optional[Dict] = None


class GroupJoinHandler:
    """Handles group join requests and determines approval/rejection."""

    def __init__(
        self,
        ws_client: WebSocketClient,
        verification_handler: QQVerificationHandler,
        paper_handler: PaperSubmissionHandler,
        allowed_groups: Optional[set] = None,
        welcome_handler: Optional[WelcomeMessageHandler] = None
    ):
        self.ws_client = ws_client
        self.verification_handler = verification_handler
        self.paper_handler = paper_handler
        self.welcome_handler = welcome_handler
        self._pending_requests: Dict[str, PendingJoinRequest] = {}
        self.allowed_groups: set = allowed_groups or set()

    async def handle_group_join(
        self,
        bot: Bot,
        group_id: int,
        user_id: int,
        comment: str = "",
        flag: str = ""
    ):
        """Handle a new group join request.

        Logic:
        1. Check if the group is in allowed groups (if configured)
        2. Check if active verification exists for this QQ
           - If yes, verify comment against verify_content
           - Send success/failed response to server
           - Approve or reject based on verification result
        3. If no active verification, check if paper submission data exists
           - If yes, use rating_id to determine action
        4. If neither, query server for user records to check rating
        """
        qq = str(user_id)
        logger.info(f"Group join request: group={group_id}, user={qq}, comment={comment}, flag={flag}")

        # Step 0: Check if this group is allowed
        if self.allowed_groups and group_id not in self.allowed_groups:
            logger.info(f"Ignoring join request for group {group_id}: not in allowed groups")
            return

        # Step 1: Check for active verification
        if self.verification_handler.has_active_verification(qq):
            await self._handle_verification_join(bot, group_id, user_id, qq, comment, flag)
            return

        # Step 2: Check for stored paper submission data
        paper_data = self.paper_handler.get_paper_data(qq)
        if paper_data:
            await self._handle_paper_join(bot, group_id, user_id, qq, paper_data, flag)
            return

        # Step 3: Query server for user records
        await self._handle_query_join(bot, group_id, user_id, qq, flag)

    async def _handle_verification_join(
        self,
        bot: Bot,
        group_id: int,
        user_id: int,
        qq: str,
        comment: str,
        flag: str
    ):
        """Handle join based on active verification."""
        result = await self.verification_handler.check_join_request(bot, qq, comment)

        if result == "success":
            logger.info(f"Approving join for {qq}: verification passed")
            await self._approve_join(bot, flag, user_id)
            await self.verification_handler.send_verify_response(
                qq,
                self.verification_handler.get_verify_message_id(qq) or "",
                "success"
            )
            paper_data = self.paper_handler.get_paper_data(qq)
            if paper_data:
                await self._send_welcome_if_enabled(bot, group_id, paper_data)
            self.paper_handler.clear_paper_data(qq)
        elif result == "failed":
            logger.info(f"Rejecting join for {qq}: verification failed")
            await self._reject_join(bot, flag, user_id)
            await self.verification_handler.send_verify_response(
                qq,
                self.verification_handler.get_verify_message_id(qq) or "",
                "failed"
            )

    async def _handle_paper_join(
        self,
        bot: Bot,
        group_id: int,
        user_id: int,
        qq: str,
        paper_data: dict,
        flag: str
    ):
        """Handle join based on paper submission data."""
        rating_id = paper_data.get("rating_id", "")
        answer_count = paper_data.get("answer_count", 0)
        max_answer_count = paper_data.get("max_answer_count", 0)

        if self.paper_handler.should_approve_join(rating_id):
            logger.info(f"Approving join for {qq}: rating {rating_id} allowed")
            await self._approve_join(bot, flag, user_id)
            await self._send_welcome_if_enabled(bot, group_id, paper_data)
            self.paper_handler.clear_paper_data(qq)
        elif self.paper_handler.should_reject_join(rating_id, answer_count, max_answer_count):
            logger.info(f"Rejecting join for {qq}: max attempts reached")
            await self._reject_join(bot, flag, user_id)
        else:
            logger.info(f"No action for join {qq}")

    async def _handle_query_join(
        self,
        bot: Bot,
        group_id: int,
        user_id: int,
        qq: str,
        flag: str
    ):
        """Handle join by querying server for user records."""
        try:
            # Store pending request
            pending = PendingJoinRequest(group_id, user_id, "", flag)
            self._pending_requests[qq] = pending

            # Query exam records using WebSocketClient's public method
            asyncio.create_task(self._query_and_process_exam_records(qq, bot, flag, user_id))

            logger.info(f"Queried exam records for {qq}")
        except Exception as e:
            logger.error(f"Error querying exam records for {qq}: {e}")
            await self._reject_join(bot, flag, user_id)

    async def _query_and_process_exam_records(
        self,
        qq: str,
        bot: Bot,
        flag: str,
        user_id: int
    ):
        """Query exam records and process join decision."""
        try:
            records = await self.ws_client.query_exam_records(qq)

            pending = self._pending_requests.pop(qq, None)
            if not pending:
                logger.debug(f"No pending join request for {qq}")
                return

            if not records:
                logger.info(f"No exam records for {qq}, rejecting join")
                await self._reject_join(bot, flag, user_id)
                return

            # Get most recent record
            latest_record = records[0]
            rating_id = latest_record.rating_id

            logger.info(f"Latest record for {qq}: rating={rating_id}")

            if self.paper_handler.should_approve_join(rating_id):
                await self._approve_join(bot, flag, user_id)
                paper_data_for_welcome = {
                    "paper_id": latest_record.paper_id,
                    "generate_time": latest_record.generate_time,
                    "submit_time": latest_record.submit_time,
                    "score": latest_record.score,
                    "answer_count": 0,
                    "rating_id": rating_id,
                }
                await self._send_welcome_if_enabled(bot, pending.group_id, paper_data_for_welcome)
            else:
                await self._reject_join(bot, flag, user_id)
        except Exception as e:
            logger.error(f"Error processing exam records for {qq}: {e}")
            await self._reject_join(bot, flag, user_id)

    async def process_exam_records_response(self, data: dict):
        """Process exam records response from server."""
        # Let WebSocketClient cache the records
        self.ws_client.process_exam_records_response(data)

        query_data = data.get("data", {})
        qq = query_data.get("qq", "")
        records_data = query_data.get("records", [])

        pending = self._pending_requests.pop(qq, None)
        if not pending:
            logger.debug(f"No pending join request for {qq}")
            return

        bot = None  # Bot reference may not be available here
        flag = pending.flag
        user_id = pending.user_id
        group_id = pending.group_id

        if not records_data:
            logger.info(f"No exam records for {qq}, rejecting join")
            await self._reject_join(bot, flag, user_id)
            return

        # Get most recent record
        latest_record = records_data[0]
        rating_id = latest_record.get("rating_id", "")

        logger.info(f"Latest record for {qq}: rating={rating_id}")

        if self.paper_handler.should_approve_join(rating_id):
            await self._approve_join(bot, flag, user_id)
            paper_data_for_welcome = {
                "paper_id": latest_record.get("paper_id", ""),
                "generate_time": latest_record.get("generate_time"),
                "submit_time": latest_record.get("submit_time"),
                "score": latest_record.get("score"),
                "answer_count": 0,
                "rating_id": rating_id,
            }
            await self._send_welcome_if_enabled(bot, group_id, paper_data_for_welcome)
        else:
            await self._reject_join(bot, flag, user_id)

    async def _approve_join(self, bot: Optional[Bot], flag: str, user_id: int):
        """Approve a group join request."""
        try:
            if bot and flag:
                await bot.set_group_add_request(
                    flag=flag,
                    sub_type="invite",
                    approve=True
                )
            logger.info(f"Approved group join: flag={flag}, user={user_id}")
        except Exception as e:
            logger.error(f"Failed to approve join for {user_id}: {e}")

    async def _reject_join(self, bot: Optional[Bot], flag: str, user_id: int):
        """Reject a group join request."""
        try:
            if bot and flag:
                await bot.set_group_add_request(
                    flag=flag,
                    sub_type="invite",
                    approve=False
                )
            logger.info(f"Rejected group join: flag={flag}, user={user_id}")
        except Exception as e:
            logger.error(f"Failed to reject join for {user_id}: {e}")

    def update_paper_submission(self, paper_data: dict):
        """Update paper submission data for future join decisions."""
        qq = paper_data.get("qq", "")
        if qq:
            self.paper_handler.set_paper_data(qq, paper_data)
            logger.info(f"Updated paper submission data for {qq}")

    async def _send_welcome_if_enabled(
        self,
        bot: Optional[Bot],
        group_id: int,
        paper_data: dict
    ):
        """Send welcome message if the feature is enabled."""
        if not self.welcome_handler or not bot:
            return
        try:
            await self.welcome_handler.send_welcome_message(bot, group_id, paper_data)
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")

    async def _cleanup_pending_request(self, qq: str):
        """Clean up pending join request after timeout."""
        await asyncio.sleep(30)
        if qq in self._pending_requests:
            del self._pending_requests[qq]
            logger.debug(f"Cleaned up pending join request for {qq}")
