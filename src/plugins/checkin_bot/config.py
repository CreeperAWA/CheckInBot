"""Bot configuration model and loader."""
from pathlib import Path
from typing import List, Optional

import yaml
from loguru import logger
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """WebSocket server configuration."""
    host: str = "localhost"
    port: int = 8080
    protocol: str = "ws"
    sid: str = ""
    jwt_token: str = ""


class BotConfig(BaseModel):
    """Main bot configuration."""
    server: ServerConfig = Field(default_factory=ServerConfig)
    group_list: List[int] = Field(default_factory=lambda: [640265417, 1032389222])
    verify_timeout: int = 3
    allowed_rating_ids: List[str] = Field(default_factory=list)
    allowed_join_groups: List[int] = Field(default_factory=list)


def load_config(config_path: str = None) -> BotConfig:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = str(Path(__file__).parent.parent.parent.parent / "bot_config.yaml")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)

        if raw_config is None:
            raw_config = {}

        config = BotConfig.model_validate(raw_config)
        logger.info(f"Configuration loaded from {config_path}")
        return config
    except FileNotFoundError:
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return BotConfig()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return BotConfig()
