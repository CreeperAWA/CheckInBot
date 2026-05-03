"""Handle group leave events and auto-invalidate exam records."""
from loguru import logger
from nonebot.adapters.onebot.v11 import Bot

from .websocket_client import WebSocketClient


class LeaveGroupInvalidateHandler:
    """Handle auto-invalidation of exam records when user leaves group."""

    def __init__(self, ws_client: WebSocketClient, enabled: bool = False):
        self.ws_client = ws_client
        self.enabled = enabled

    def update_config(self, enabled: bool):
        """Update enabled status."""
        self.enabled = enabled
        logger.info(f"Leave group invalidate feature {'enabled' if enabled else 'disabled'}")

    async def handle_group_decrease(
        self,
        bot: Bot,
        group_id: int,
        user_id: int,
        sub_type: str
    ):
        """Handle group decrease event (member leaves or is kicked)."""
        if not self.enabled:
            logger.debug(f"Leave group invalidate feature is disabled, skipping")
            return

        qq = str(user_id)
        logger.info(
            f"Group decrease event: group={group_id}, user={qq}, "
            f"sub_type={sub_type}, auto-invalidate={'enabled' if self.enabled else 'disabled'}"
        )

        await self._query_and_invalidate_exam_records(qq)

    async def _query_and_invalidate_exam_records(self, qq: str):
        """Query user's exam records and invalidate all of them."""
        try:
            # Step 1: Query exam records using WebSocketClient's public method
            records = await self.ws_client.query_exam_records(qq)

            if not records:
                logger.info(f"No exam records found for user {qq}")
                return

            logger.info(f"Found {len(records)} exam records for user {qq}")

            # Step 2: Extract paper_ids and invalidate all records
            paper_ids = [record.paper_id for record in records]
            await self.ws_client.invalidate_exam_records(qq, paper_ids)

        except Exception as e:
            logger.error(f"Error processing exam records invalidation for {qq}: {e}")
