"""
WePush 配置模块
从.env文件加载配置，支持环境变量覆盖
"""

import os
import logging
from typing import List, Optional
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

# 微信监听配置
def _parse_list(value: Optional[str], default: List[str] = None) -> List[str]:
    """解析逗号分隔的字符串为列表"""
    if not value:
        return default or []
    return [item.strip() for item in value.split(',') if item.strip()]

def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    """解析字符串为布尔值"""
    if not value:
        return default
    return value.lower() in ('true', 'yes', '1', 't', 'y')

# 要监听的聊天对象列表
WX_TARGET_CHATS = _parse_list(os.getenv('WX_TARGET_CHATS'), [])

# 是否在未指定目标聊天时监听所有聊天
WX_LISTEN_ALL_IF_EMPTY = _parse_bool(os.getenv('WX_LISTEN_ALL_IF_EMPTY'), False)

# 排除的聊天对象
WX_EXCLUDED_CHATS = _parse_list(
    os.getenv('WX_EXCLUDED_CHATS'), 
    ["文件传输助手", "微信团队", "微信支付"]
)

# MaiBot API 配置
MAIBOT_API_URL = os.getenv('MAIBOT_API_URL', 'http://192.168.8.124:8000/api/message')

# Redis 配置
REDIS_URL = os.getenv('REDIS_URL', 'redis://192.168.8.124:6379')
REDIS_QUEUE_KEY = os.getenv('REDIS_QUEUE_KEY', 'autoText')

# 消息队列生产者（FastAPI）配置
API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', '8000'))

# 日志配置
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'wepush.log')
LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s - %(levelname)s - %(message)s')
LOG_DATE_FORMAT = os.getenv('LOG_DATE_FORMAT', '%Y-%m-%d %H:%M:%S')

# 平台标识
PLATFORM_ID = os.getenv('PLATFORM_ID', 'wxauto')

# 配置信息打印
def print_config_info():
    """打印当前加载的配置信息"""
    logger = logging.getLogger(__name__)
    logger.info("\n=== WePush 配置信息 ===")
    logger.info(f"\u5fae信监听目标: {WX_TARGET_CHATS}")
    logger.info(f"\u76d1听所有聊天: {WX_LISTEN_ALL_IF_EMPTY}")
    logger.info(f"\u6392除的聊天: {WX_EXCLUDED_CHATS}")
    logger.info(f"MaiBot API URL: {MAIBOT_API_URL}")
    logger.info(f"Redis URL: {REDIS_URL}")
    logger.info(f"Redis 队列键: {REDIS_QUEUE_KEY}")
    logger.info(f"API 监听地址: {API_HOST}:{API_PORT}")
    logger.info(f"\u65e5志级别: {LOG_LEVEL}")
    logger.info(f"\u5e73台标识: {PLATFORM_ID}")
    logger.info("==========================\n")

# 如果直接运行该模块，打印配置信息
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print_config_info()
