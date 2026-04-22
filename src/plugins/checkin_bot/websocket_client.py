"""WebSocket client for server communication."""
import asyncio
import json
import time
import uuid
from typing import Callable, Dict, Optional

import websockets
from loguru import logger

from .config import BotConfig


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
        self._pending_paper_submissions: Dict[str, dict] = {}

    def register_handler(self, message_type: str, handler: Callable):
        """Register a handler for a specific message type."""
        self._message_handlers[message_type] = handler

    def get_handler(self, message_type: str) -> Optional[Callable]:
        """Get handler for a message type."""
        return self._message_handlers.get(message_type)

    @property
    def ws_url(self) -> str:
        """Get WebSocket URL."""
        return f"{self.config.server.protocol}://{self.config.server.host}:{self.config.server.port}/api/websocket/thirdParty/{self.config.server.sid}"

    async def connect(self):
        """Establish WebSocket connection."""
        self.running = True
        while self.running:
            try:
                logger.info(f"Connecting to server: {self.ws_url}")
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    self._reconnect_delay = 5
                    logger.info("Connected to server")

                    # Send authentication
                    await self._authenticate()

                    # Start message loop
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

        # Wait for auth response
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
                    logger.debug(f"Received message: {data.get('type', 'unknown')}")
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
        if self.ws and self.ws.open:
            await self.ws.send(json.dumps(message))
            logger.debug(f"Message sent: {message.get('type')}")
        else:
            logger.error("WebSocket not connected, cannot send message")

    async def _reconnect(self):
        """Handle reconnection with exponential backoff."""
        if not self.running:
            return

        logger.info(f"Reconnecting in {self._reconnect_delay} seconds...")
        await asyncio.sleep(self._reconnect_delay)

        # Exponential backoff: 5s -> 10s -> 1min -> 5min -> 5min...
        if self._reconnect_delay == 5:
            self._reconnect_delay = 10
        elif self._reconnect_delay == 10:
            self._reconnect_delay = 60
        else:
            self._reconnect_delay = min(self._reconnect_delay * 5, self._max_reconnect_delay)

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
