"""
WeMai configuration module.

Loads settings from the environment and provides a few parsing helpers.
"""

import logging
import os
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()


def _parse_list(value: Optional[str], default: List[str] = None) -> List[str]:
    """Parse a comma-separated string into a list."""
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    """Parse a string boolean value."""
    if not value:
        return default
    return value.lower() in ("true", "yes", "1", "t", "y")


WX_TARGET_CHATS = _parse_list(os.getenv("WX_TARGET_CHATS"), [])
WX_LISTEN_ALL_IF_EMPTY = _parse_bool(os.getenv("WX_LISTEN_ALL_IF_EMPTY"), False)
WX_EXCLUDED_CHATS = _parse_list(
    os.getenv("WX_EXCLUDED_CHATS"),
    ["文件传输助手", "微信团队", "微信支付"],
)

MAIBOT_API_URL = os.getenv("MAIBOT_API_URL", "http://192.168.8.124:8000/api/message")

REDIS_URL = os.getenv("REDIS_URL", "redis://192.168.8.124:6379")
REDIS_QUEUE_KEY = os.getenv("REDIS_QUEUE_KEY", "autoText")

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "wemai.log")
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s - %(levelname)s - %(message)s")
LOG_DATE_FORMAT = os.getenv("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S")

PLATFORM_ID = os.getenv("PLATFORM_ID", "pywechat")


def print_config_info():
    """Log the active configuration."""
    logger = logging.getLogger(__name__)
    logger.info("\n=== WeMai Configuration ===")
    logger.info("Target chats: %s", WX_TARGET_CHATS)
    logger.info("Listen all if empty: %s", WX_LISTEN_ALL_IF_EMPTY)
    logger.info("Excluded chats: %s", WX_EXCLUDED_CHATS)
    logger.info("MaiBot API URL: %s", MAIBOT_API_URL)
    logger.info("Redis URL: %s", REDIS_URL)
    logger.info("Redis queue key: %s", REDIS_QUEUE_KEY)
    logger.info("API listen address: %s:%s", API_HOST, API_PORT)
    logger.info("Log level: %s", LOG_LEVEL)
    logger.info("Platform id: %s", PLATFORM_ID)
    logger.info("===========================\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print_config_info()
