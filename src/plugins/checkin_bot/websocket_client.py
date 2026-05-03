"""WebSocket client for server communication."""
import asyncio
import json
import time
import uuid
from typing import Callable, Dict, List, Optional

import websockets
from loguru import logger

from .config import BotConfig


class ExamRecord:
    """Represents an exam record."""

    def __init__(self, paper_id: str, rating_id: str = "", score: str = "",
                 generate_time: Optional[int] = None, submit_time: Optional[int] = None):
        self.paper_id = paper_id
        self.rating_id = rating_id
        self.score = score
        self.generate_time = generate_time
        self.submit_time = submit_time

    @classmethod
    def from_dict(cls, data: dict) -> "ExamRecord":
        """Create ExamRecord from dict."""
        return cls(
            paper_id=data.get("paper_id", ""),
            rating_id=data.get("rating_id", ""),
            score=data.get("score", ""),
            generate_time=data.get("generate_time"),
            submit_time=data.get("submit_time")
        )


class WebSocketClient:
    """WebSocket client for communicating with the exam server."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.ws = None
        self.running = False
        self._message_handlers: Dict[str, Callable] = {}
        self._reconnect_delay = 5
        self._max_reconnect_delay = 300
        self._pending_verifications: Dict[str, dict] = {}
        self._pending_exam_queries: Dict[str, asyncio.Event] = {}
        self._exam_records_cache: Dict[str, List[ExamRecord]] = {}

    def register_handler(self, message_type: str, handler: Callable):
        """Register a handler for a specific message type."""
        self._message_handlers[message_type] = handler

    def get_handler(self, message_type: str) -> Optional[Callable]:
        """Get handler for a message type."""
        return self._message_handlers.get(message_type)

    @property
    def ws_url(self) -> str:
        """Get WebSocket URL."""
        protocol = "wss" if self.config.server.protocol == "wss" else "ws"
        return f"{protocol}://{self.config.server.host}:{self.config.server.port}/checkIn/api/websocket/thirdParty/{self.config.server.sid}"

    async def connect(self):
        """Establish WebSocket connection."""
        self.running = True
        while self.running:
            try:
                logger.info(f"Connecting to server: {self.ws_url}")
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=30,
                    ping_timeout=10
                ) as ws:
                    self.ws = ws
                    self._reconnect_delay = 5
                    logger.info("WebSocket connection established")

                    await self._authenticate()

                    await self._message_loop()
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection closed: {e}")
                await self._reconnect()
            except Exception as e:
                logger.error(f"Connection error: {e}")
                await self._reconnect()

    async def _authenticate(self):
        """Send JWT token for authentication."""
        auth_message = {
            "type": "token",
            "messageId": str(uuid.uuid4()),
            "data": {"token": self.config.server.jwt_token}
        }
        await self.ws.send(json.dumps(auth_message))
        logger.info("Authentication message sent")

        response = await self.ws.recv()
        response_data = json.loads(response)
        if response_data.get("type") == "success":
            logger.info("Authentication successful")
        else:
            logger.error(f"Authentication failed: {response_data}")

    async def _message_loop(self):
        """Main message processing loop."""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "unknown")
                    message_id = data.get("messageId", "")
                    logger.debug(f"Received message: type={msg_type}, messageId={message_id}")
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON message: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed by server")

    async def _handle_message(self, data: dict):
        """Route message to appropriate handler."""
        message_type = data.get("type", "unknown")
        handler = self._message_handlers.get(message_type)

        if handler:
            try:
                await handler(data)
            except Exception as e:
                logger.error(f"Handler error for {message_type}: {e}")
        else:
            logger.warning(f"No handler registered for message type: {message_type}")

    async def send_message(self, message: dict):
        """Send a message to the server."""
        if self.ws:
            try:
                await self.ws.send(json.dumps(message, ensure_ascii=False))
                logger.debug(f"Message sent: type={message.get('type')}")
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
        else:
            logger.error("WebSocket not connected, cannot send message")

    async def _reconnect(self):
        """Handle reconnection with exponential backoff."""
        if not self.running:
            return

        delay = self._reconnect_delay
        logger.info(f"Reconnecting in {delay} seconds...")
        await asyncio.sleep(delay)

        if self._reconnect_delay == 5:
            self._reconnect_delay = 10
        elif self._reconnect_delay == 10:
            self._reconnect_delay = 60
        else:
            self._reconnect_delay = min(
                self._reconnect_delay + 240,
                self._max_reconnect_delay
            )

    async def disconnect(self):
        """Disconnect from server."""
        self.running = False
        if self.ws:
            await self.ws.close()
            logger.info("Disconnected from server")

    def add_pending_verification(self, qq: str, verify_content: str) -> str:
        """Add a pending verification and return its ID."""
        verify_id = str(uuid.uuid4())
        self._pending_verifications[qq] = {
            "verify_id": verify_id,
            "verify_content": verify_content,
            "timestamp": time.time()
        }
        return verify_id

    def get_pending_verification(self, qq: str) -> Optional[dict]:
        """Get pending verification for a QQ number."""
        return self._pending_verifications.get(qq)

    def remove_pending_verification(self, qq: str):
        """Remove pending verification."""
        if qq in self._pending_verifications:
            del self._pending_verifications[qq]

    def get_verification_timeout(self) -> float:
        """Get verification timeout in seconds."""
        return self.config.verify_timeout * 60

    def is_rating_allowed(self, rating_id: str) -> bool:
        """Check if a rating ID is in the allowed list."""
        if not self.config.allowed_rating_ids:
            return False
        return rating_id in self.config.allowed_rating_ids

    async def query_exam_records(self, qq: str, timeout: float = 10.0) -> List[ExamRecord]:
        """Query exam records for a user.

        Args:
            qq: QQ number to query.
            timeout: Timeout in seconds for waiting response.

        Returns:
            List of ExamRecord objects, empty list if no records or timeout.
        """
        query_message = {
            "type": "exam_records_query",
            "messageId": str(uuid.uuid4()),
            "data": {"qq": qq}
        }

        event = asyncio.Event()
        self._pending_exam_queries[qq] = event

        try:
            await self.send_message(query_message)
            logger.info(f"Queried exam records for {qq}")

            await asyncio.wait_for(event.wait(), timeout=timeout)

            records = self._exam_records_cache.pop(qq, [])
            return records
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for exam records response for {qq}")
            return []
        finally:
            self._pending_exam_queries.pop(qq, None)

    async def invalidate_exam_records(self, qq: str, paper_ids: List[str]) -> bool:
        """Invalidate exam records for a user.

        Args:
            qq: QQ number whose records to invalidate.
            paper_ids: List of paper IDs to invalidate.

        Returns:
            True if request was sent successfully, False otherwise.
        """
        if not paper_ids:
            return False

        invalidate_message = {
            "type": "exam_invalidate_request",
            "messageId": str(uuid.uuid4()),
            "data": {"paper_ids": paper_ids}
        }

        try:
            await self.send_message(invalidate_message)
            logger.info(
                f"Sent invalidate request for {len(paper_ids)} "
                f"exam records of user {qq}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send invalidate request for {qq}: {e}")
            return False

    def process_exam_records_response(self, data: dict) -> None:
        """Process exam records response from server.

        This method caches the exam records and signals waiting queries.

        Args:
            data: The response data from server.
        """
        query_data = data.get("data", {})
        qq = query_data.get("qq", "")
        records_data = query_data.get("records", [])

        records = [ExamRecord.from_dict(r) for r in records_data]
        self._exam_records_cache[qq] = records

        event = self._pending_exam_queries.get(qq)
        if event:
            event.set()

        logger.info(f"Cached {len(records)} exam records for user {qq}")
