"""Exam paper submission handler."""
import time
from typing import Dict, Optional

from loguru import logger

from .websocket_client import WebSocketClient


class PaperSubmissionHandler:
    """Handles exam paper submission notifications from server."""

    def __init__(self, ws_client: WebSocketClient):
        self.ws_client = ws_client
        self._paper_data: Dict[str, dict] = {}

    async def handle_paper_submit(self, data: dict):
        """Handle paper submission notification.

        Processes the submission and determines group join action
        based on rating ID and answer count.
        """
        submit_data = data.get("data", {})
        rating_id = submit_data.get("rating_id", "")
        qq = submit_data.get("qq", "")
        answer_count = submit_data.get("answer_count", 0)
        max_answer_count = submit_data.get("max_answer_count", 0)

        if not rating_id or not qq:
            logger.error("Invalid paper submit message: missing rating_id or qq")
            return

        logger.info(
            f"Paper submission: qq={qq}, rating_id={rating_id}, "
            f"answer_count={answer_count}/{max_answer_count}"
        )

        # Store paper data for future join decisions
        self._paper_data[qq] = submit_data

        # Check if rating ID is allowed
        is_allowed = self.ws_client.is_rating_allowed(rating_id)

        action = {
            "qq": qq,
            "rating_id": rating_id,
            "allowed": is_allowed,
            "answer_count": answer_count,
            "max_answer_count": max_answer_count
        }

        logger.info(f"Paper submission action: {action}")
        return action

    def should_approve_join(self, rating_id: str) -> bool:
        """Determine if group join should be approved based on rating ID."""
        return self.ws_client.is_rating_allowed(rating_id)

    def should_reject_join(
        self,
        rating_id: str,
        answer_count: int,
        max_answer_count: int
    ) -> bool:
        """Determine if group join should be rejected."""
        if self.ws_client.is_rating_allowed(rating_id):
            return False

        # Reject when answer count equals max answer count
        return answer_count >= max_answer_count

    def get_paper_data(self, qq: str) -> Optional[dict]:
        """Get stored paper data for a QQ number."""
        return self._paper_data.get(qq)

    def set_paper_data(self, qq: str, data: dict):
        """Store paper data for a QQ number."""
        self._paper_data[qq] = data

    def clear_paper_data(self, qq: str):
        """Clear stored paper data for a QQ number."""
        if qq in self._paper_data:
            del self._paper_data[qq]

    def cleanup_old_data(self, max_age: float = 3600):
        """Clean up paper data older than max_age seconds."""
        now = time.time()
        to_remove = []
        for qq, data in self._paper_data.items():
            timestamp = data.get("_timestamp", 0)
            if now - timestamp > max_age:
                to_remove.append(qq)

        for qq in to_remove:
            del self._paper_data[qq]
