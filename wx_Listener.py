import logging

from config import WX_TARGET_CHATS
from wechat_adapter import AutoWeChatListener, get_backend_description


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


class WeChatListener:
    def __init__(self, target_chats=None, callback=None):
        self.target_chats = target_chats
        self.callback = callback
        self._listener = AutoWeChatListener(target_chats=target_chats, callback=callback)
        logger.info("WeChat listener initialized with backend: %s", get_backend_description())

    def start_listening(self):
        self._listener.start_listening()

    def stop_listening(self):
        self._listener.stop_listening()


global_processor = None


def set_global_processor(processor):
    global global_processor
    global_processor = processor
    print(f"Global processor set: {type(processor)}")


def create_message_processor():
    from wx_Processer import MessageProcessor

    return MessageProcessor()


def message_callback(chat_name, message_data):
    global global_processor

    print(f"\nNew message from {chat_name}:")
    print(f"Sender: {message_data['sender']}")
    print(f"Content: {message_data['content']}")
    print(f"Type: {message_data['type']}")
    print(f"Timestamp: {message_data['timestamp']}")
    print("-" * 50)

    if global_processor:
        result = global_processor.process_message(chat_name, message_data)
        if result.get("success"):
            print("Message forwarded to MaiBot successfully")
        else:
            print(f"Failed to forward message: {result.get('error')}")
    else:
        print("Message processor is not initialized")
        print(f"global_processor: {global_processor}")
        print(f"type: {type(global_processor)}")


if __name__ == "__main__":
    listener = WeChatListener(
        target_chats=WX_TARGET_CHATS,
        callback=message_callback,
    )

    print("WeChat listener started")
    print(f"Current backend: {get_backend_description()}")
    print("Press Ctrl+C to stop listening")
    print("-" * 50)

    listener.start_listening()
