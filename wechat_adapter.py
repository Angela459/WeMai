import base64
import importlib
import logging
import os
import tempfile
import time
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)

BACKEND_PYWECHAT = "pywechat"
BACKEND_PYWEIXIN = "pyweixin"
SUPPORTED_BACKENDS = {BACKEND_PYWECHAT, BACKEND_PYWEIXIN}
ENV_BACKEND_KEYS = ("WECHAT_BACKEND", "WEMAI_WECHAT_BACKEND")

_BACKEND_CACHE: Optional[str] = None
_MODULE_CACHE: Dict[str, Dict[str, object]] = {}


def _registry_values(subkey: str) -> Dict[str, object]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            values: Dict[str, object] = {}
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                    values[name] = value
                    index += 1
                except OSError:
                    break
            return values
    except OSError:
        return {}


def _read_version_from_registry() -> Optional[str]:
    values = _registry_values(r"Software\Tencent\Weixin")
    raw_version = values.get("Version")
    if raw_version is None:
        return None
    if isinstance(raw_version, str):
        return raw_version
    if isinstance(raw_version, int):
        hex_str = hex(raw_version)[5:]
        if len(hex_str) >= 4:
            return f"{hex_str[0]}.{hex_str[1]}.{hex_str[2]}.{int(hex_str[-2:], 16)}"
    return None


def _detect_backend_from_registry() -> Optional[str]:
    if _registry_values(r"Software\Tencent\Weixin"):
        return BACKEND_PYWEIXIN
    if _registry_values(r"Software\Tencent\WeChat"):
        return BACKEND_PYWECHAT
    return None


def _detect_backend_from_processes() -> Optional[str]:
    try:
        import psutil
    except ImportError:
        return None

    for proc in psutil.process_iter(["name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            exe_path = (proc.info.get("exe") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if name == "weixin.exe" or exe_path.endswith("\\weixin.exe"):
            return BACKEND_PYWEIXIN
        if name == "wechat.exe" or exe_path.endswith("\\wechat.exe"):
            return BACKEND_PYWECHAT
    return None


def detect_wechat_backend(force_refresh: bool = False) -> str:
    global _BACKEND_CACHE

    if not force_refresh and _BACKEND_CACHE:
        return _BACKEND_CACHE

    for key in ENV_BACKEND_KEYS:
        override = os.getenv(key, "").strip().lower()
        if not override:
            continue
        if override not in SUPPORTED_BACKENDS:
            raise ValueError(f"{key} must be one of {sorted(SUPPORTED_BACKENDS)}, got {override!r}")
        _BACKEND_CACHE = override
        logger.info("Using WeChat backend override from %s: %s", key, override)
        return override

    version_text = _read_version_from_registry()
    if version_text:
        try:
            parsed_version = Version(version_text)
            _BACKEND_CACHE = BACKEND_PYWEIXIN if parsed_version >= Version("4.1.0") else BACKEND_PYWECHAT
            logger.info("Detected WeChat version %s, selected backend %s", version_text, _BACKEND_CACHE)
            return _BACKEND_CACHE
        except InvalidVersion:
            logger.warning("Could not parse WeChat version %r, falling back to registry/process detection", version_text)

    backend = _detect_backend_from_registry()
    if backend:
        _BACKEND_CACHE = backend
        logger.info("Detected WeChat backend from registry: %s", backend)
        return backend

    backend = _detect_backend_from_processes()
    if backend:
        _BACKEND_CACHE = backend
        logger.info("Detected WeChat backend from running process: %s", backend)
        return backend

    _BACKEND_CACHE = BACKEND_PYWEIXIN
    logger.warning("Could not detect WeChat backend reliably, defaulting to %s", _BACKEND_CACHE)
    return _BACKEND_CACHE


def get_active_backend(force_refresh: bool = False) -> str:
    return detect_wechat_backend(force_refresh=force_refresh)


def get_backend_description(force_refresh: bool = False) -> str:
    backend = detect_wechat_backend(force_refresh=force_refresh)
    version_text = _read_version_from_registry()
    if version_text:
        return f"{backend} (WeChat {version_text})"
    return backend


def _load_backend_modules(backend: Optional[str] = None) -> Dict[str, object]:
    selected_backend = backend or detect_wechat_backend()
    cached = _MODULE_CACHE.get(selected_backend)
    if cached:
        return cached

    if selected_backend == BACKEND_PYWECHAT:
        config_module = importlib.import_module("pywechat.Config")
        auto_module = importlib.import_module("pywechat.WechatAuto")
        tools_module = importlib.import_module("pywechat.WechatTools")
        modules = {
            "GlobalConfig": config_module.GlobalConfig,
            "Files": auto_module.Files,
            "Messages": auto_module.Messages,
            "Monitor": auto_module.Monitor,
            "Navigator": tools_module.Navigator,
        }
    elif selected_backend == BACKEND_PYWEIXIN:
        config_module = importlib.import_module("pyweixin.Config")
        auto_module = importlib.import_module("pyweixin.WeChatAuto")
        tools_module = importlib.import_module("pyweixin.WeChatTools")
        modules = {
            "GlobalConfig": config_module.GlobalConfig,
            "Files": auto_module.Files,
            "Messages": auto_module.Messages,
            "Monitor": auto_module.Monitor,
            "Navigator": tools_module.Navigator,
        }
    else:
        raise ValueError(f"Unsupported backend: {selected_backend}")

    _MODULE_CACHE[selected_backend] = modules
    return modules


def _configure_backend(backend: Optional[str] = None) -> str:
    selected_backend = backend or detect_wechat_backend()
    modules = _load_backend_modules(selected_backend)
    global_config = modules["GlobalConfig"]

    if selected_backend == BACKEND_PYWECHAT:
        global_config.close_wechat = False
    else:
        global_config.close_weixin = False

    global_config.is_maximize = False
    global_config.search_pages = 0
    global_config.send_delay = 0.2
    return selected_backend


def _is_base64_image(content: str) -> bool:
    if not isinstance(content, str):
        return False
    if content.startswith("data:image/"):
        return True
    return len(content) > 1000 and content.replace("+", "").replace("/", "").replace("=", "").isalnum()


def _base64_to_temp_file(content: str) -> str:
    file_extension = ".png"
    if content.startswith("data:image/"):
        header, encoded = content.split(",", 1)
        lowered = header.lower()
        if "gif" in lowered:
            file_extension = ".gif"
        elif "jpeg" in lowered or "jpg" in lowered:
            file_extension = ".jpg"
        image_data = base64.b64decode(encoded)
    else:
        image_data = base64.b64decode(content)
        if image_data.startswith(b"GIF8"):
            file_extension = ".gif"
        elif image_data.startswith(b"\xff\xd8\xff"):
            file_extension = ".jpg"
        elif image_data.startswith(b"\x89PNG"):
            file_extension = ".png"

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
        temp_file.write(image_data)
        return temp_file.name


def _send_text(receiver: str, content: str, backend: str) -> None:
    modules = _load_backend_modules(backend)
    messages = modules["Messages"]
    if backend == BACKEND_PYWECHAT:
        messages.send_messages_to_friend(friend=receiver, messages=[content], close_wechat=False)
    else:
        messages.send_messages_to_friend(friend=receiver, messages=[content], close_weixin=False)


def _send_file(receiver: str, file_path: str, backend: str) -> None:
    modules = _load_backend_modules(backend)
    files = modules["Files"]
    if backend == BACKEND_PYWECHAT:
        files.send_files_to_friend(friend=receiver, files=[file_path], close_wechat=False)
    else:
        files.send_files_to_friend(friend=receiver, files=[file_path], close_weixin=False)


def send_text(receiver: str, content: str) -> None:
    backend = _configure_backend()
    _send_text(receiver, content, backend)


def send_file(receiver: str, file_path: str) -> None:
    backend = _configure_backend()
    _send_file(receiver, file_path, backend)


def send_message(receiver: str, content: str, msg_type: str = "text") -> None:
    backend = _configure_backend()
    temp_file_path: Optional[str] = None
    try:
        if msg_type in {"image", "file"} and isinstance(content, str) and os.path.exists(content):
            _send_file(receiver, content, backend)
            return
        if msg_type == "emoji" or _is_base64_image(content):
            temp_file_path = _base64_to_temp_file(content)
            _send_file(receiver, temp_file_path, backend)
            return
        _send_text(receiver, content, backend)
    finally:
        if temp_file_path:
            try:
                os.unlink(temp_file_path)
            except OSError:
                logger.warning("Failed to delete temporary image file: %s", temp_file_path)


def normalize_message_type(raw_type: str, content: str) -> str:
    type_map = {
        "文本": "text",
        "系统消息": "sys",
        "图片": "image",
        "视频": "video",
        "文件": "file",
        "语音": "voice",
        "动画表情": "emoji",
        "链接": "link",
        "卡片链接": "link",
        "引用消息": "quote",
        "小程序": "app",
    }
    normalized = type_map.get(raw_type, "text")
    if normalized == "text" and isinstance(content, str):
        lowered = content.lower()
        if lowered.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")):
            return "image"
    return normalized


@dataclass
class WeChatMessage:
    chat: str
    sender: str
    type: str
    content: str
    timestamp: str


class AutoWeChatListener:
    def __init__(self, target_chats: Optional[List[str]] = None, callback: Optional[Callable[[str, dict], None]] = None):
        self.backend = _configure_backend()
        self.target_chats = target_chats or []
        self.callback = callback
        self.running = False
        self.dialog_windows: Dict[str, object] = {}

    def start_listening(self) -> None:
        logger.info("Starting WeChat listener with backend %s", self.backend)
        self.running = True
        try:
            for chat_name in self.target_chats:
                self._ensure_dialog_window(chat_name)

            while self.running:
                for chat_name in list(self.dialog_windows.keys()):
                    self._poll_chat(chat_name)
                time.sleep(0.3)
        finally:
            self.stop_listening()

    def stop_listening(self) -> None:
        self.running = False
        for chat_name, dialog_window in list(self.dialog_windows.items()):
            try:
                dialog_window.close()
            except Exception:
                logger.debug("Failed to close listener window for chat %s", chat_name, exc_info=True)
        self.dialog_windows.clear()
        logger.info("WeChat listener stopped for backend %s", self.backend)

    def _ensure_dialog_window(self, chat_name: str):
        existing = self.dialog_windows.get(chat_name)
        if existing is not None:
            try:
                if existing.exists(timeout=0.1):
                    return existing
            except Exception:
                logger.debug("Existing dialog window became invalid, reopening chat %s", chat_name, exc_info=True)

        modules = _load_backend_modules(self.backend)
        navigator = modules["Navigator"]
        kwargs = {
            "friend": chat_name,
            "window_minimize": True,
        }
        if self.backend == BACKEND_PYWECHAT:
            kwargs["close_wechat"] = False
        else:
            kwargs["close_weixin"] = False

        dialog_window = navigator.open_seperate_dialog_window(**kwargs)
        self.dialog_windows[chat_name] = dialog_window
        logger.info("Opened listener dialog window: %s", chat_name)
        return dialog_window

    def _poll_chat(self, chat_name: str) -> None:
        try:
            dialog_window = self._ensure_dialog_window(chat_name)
            if self.backend == BACKEND_PYWECHAT:
                messages = self._listen_with_pywechat(dialog_window)
            else:
                messages = self._listen_with_pyweixin(dialog_window)

            if not messages:
                return

            for message_data in messages:
                if self.callback:
                    self.callback(chat_name, message_data)
        except Exception as exc:
            self.dialog_windows.pop(chat_name, None)
            logger.error("Error while listening to chat %s: %s", chat_name, exc)

    def _listen_with_pywechat(self, dialog_window) -> List[dict]:
        modules = _load_backend_modules(self.backend)
        monitor = modules["Monitor"]
        contents, senders, message_types = monitor.listen_on_chat(
            dialog_window=dialog_window,
            duration="1s",
            save_file=False,
            save_media=False,
            close_wechat=False,
        )

        payloads: List[dict] = []
        for content, sender, raw_type in zip(contents, senders, message_types):
            payloads.append(
                {
                    "chat": dialog_window.window_text(),
                    "sender": sender,
                    "type": normalize_message_type(raw_type, content),
                    "content": content,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "raw_type": raw_type,
                }
            )
        return payloads

    def _listen_with_pyweixin(self, dialog_window) -> List[dict]:
        modules = _load_backend_modules(self.backend)
        monitor = modules["Monitor"]
        details = monitor.listen_on_chat(
            dialog_window=dialog_window,
            duration="1s",
            save_file=False,
            save_media=False,
            close_dialog_window=False,
        )

        contents = details.get("文本内容", []) or []
        senders = details.get("消息发送人", []) or []
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        payloads: List[dict] = []

        for index, content in enumerate(contents):
            sender = senders[index] if index < len(senders) else chat_name_from_window(dialog_window)
            payloads.append(
                {
                    "chat": chat_name_from_window(dialog_window),
                    "sender": sender,
                    "type": "text",
                    "content": content,
                    "timestamp": timestamp,
                    "raw_type": "文本",
                }
            )
        return payloads


def chat_name_from_window(dialog_window) -> str:
    try:
        return dialog_window.window_text()
    except Exception:
        return ""


PyWeChatListener = AutoWeChatListener
