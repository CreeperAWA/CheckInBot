"""Bot startup file.

This file initializes the NoneBot application and starts the WebSocket connection.
"""
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# Load plugins first
nonebot.load_from_toml("pyproject.toml")

# Import and initialize handlers AFTER loading plugins
from src.plugins.checkin_bot.main import initialize_handlers, start_websocket_connection

initialize_handlers()

# Register startup event
@driver.on_startup
async def start_bot():
    """Start WebSocket connection on bot startup."""
    from loguru import logger
    logger.info("CheckInBot starting up...")
    await start_websocket_connection()

if __name__ == "__main__":
    nonebot.run()
