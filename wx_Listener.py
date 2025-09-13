import asyncio
import json
import logging
import time
from datetime import datetime
from wxauto import WeChat
from config import WX_TARGET_CHATS, WX_LISTEN_ALL_IF_EMPTY, WX_EXCLUDED_CHATS

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

class WeChatListener:
    def __init__(self, target_chats=None, callback=None):
        """
        初始化微信消息监听器
        
        Args:
            target_chats (list, optional): 要监听的聊天对象列表，如果为None则监听所有聊天
            callback (function, optional): 收到新消息时的回调函数，接收参数为(chat_name, message_data)
        """
        self.wx = WeChat()
        self.target_chats = target_chats
        self.callback = callback
        self.listen_chats = {}
        self.running = False
        logger.info(f"微信监听器初始化成功，登录账号：{self.wx.nickname}")
        
    def start_listening(self):
        """开始监听微信消息"""
        logger.info("开始监听微信消息...")
        self.running = True
        
        # 如果指定了目标聊天，则只监听这些聊天
        if self.target_chats:
            for chat in self.target_chats:
                self._add_listen_chat(chat)
        elif WX_LISTEN_ALL_IF_EMPTY:
            # 监听当前所有聊天窗口，但排除指定的聊天
            session_list = self.wx.GetSessionList(reset=True)
            for chat in session_list:
                if chat not in WX_EXCLUDED_CHATS:
                    self._add_listen_chat(chat)
        else:
            logger.info("未指定目标聊天且未启用监听所有聊天，将不会监听任何聊天")
        
        # 开始监听循环
        try:
            while self.running:
                self._check_new_messages()
                time.sleep(1)  # 每秒检查一次新消息
        except KeyboardInterrupt:
            logger.info("监听被用户中断")
        except Exception as e:
            logger.error(f"监听过程中发生错误: {str(e)}")
        finally:
            self.stop_listening()
    
    def stop_listening(self):
        """停止监听微信消息"""
        self.running = False
        logger.info("停止监听微信消息")
    
    def _add_listen_chat(self, chat_name):
        """添加监听的聊天对象"""
        try:
            # 尝试打开聊天窗口
            chat_result = self.wx.ChatWith(chat_name)
            if chat_result:
                # 添加到监听列表，不自动保存图片和文件，因为我们不需要
                self.wx.AddListenChat(chat_name, savepic=False, savefile=False, savevoice=False)
                logger.info(f"添加监听聊天: {chat_name}")
                return True
            else:
                logger.warning(f"无法找到聊天对象: {chat_name}")
                return False
        except Exception as e:
            logger.error(f"添加监听聊天 {chat_name} 时发生错误: {str(e)}")
            return False
    
    def _check_new_messages(self):
        """检查所有监听的聊天是否有新消息"""
        try:
            # 获取所有监听聊天的新消息
            all_messages = self.wx.GetListenMessage()
            
            if all_messages:
                for chat, messages in all_messages.items():
                    chat_name = chat.who
                    if messages:
                        logger.info(f"收到来自 {chat_name} 的 {len(messages)} 条新消息")
                        
                        # 处理每条消息
                        for msg in messages:
                            self._process_message(chat_name, msg)
        except Exception as e:
            logger.error(f"检查新消息时发生错误: {str(e)}")
    
    def _process_message(self, chat_name, message):
        """处理单条消息"""
        try:
            # 提取消息信息
            msg_type = message.type
            sender = message.sender
            content = message.content
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 过滤系统消息，如"以下为新消息"等
            if msg_type == "sys" and ("以下为新消息" in content or "新消息" in content):
                return None
                
            # 过滤自己发送的消息
            if msg_type == "self" or sender == "Self":
                logger.info(f"过滤自己发送的消息: {chat_name} - {sender}: {content}")
                return None
            
            # 过滤纯时间系统消息
            if msg_type == "sys" and len(content.strip()) <= 10 and ":" in content:
                return None
            
            # 构建消息数据
            message_data = {
                "chat": chat_name,
                "sender": sender,
                "type": msg_type,
                "content": content,
                "timestamp": timestamp
            }
            
            # 记录消息
            logger.info(f"消息: {chat_name} - {sender}: {content} ({msg_type})")
            
            # 如果有回调函数，则调用回调函数
            if self.callback:
                self.callback(chat_name, message_data)
                
            return message_data
        except Exception as e:
            logger.error(f"处理消息时发生错误: {str(e)}")
            return None


# 全局消息处理器实例
global_processor = None

def set_global_processor(processor):
    """设置全局消息处理器"""
    global global_processor
    global_processor = processor
    print(f"全局消息处理器已设置: {type(processor)}")

def create_message_processor():
    """创建消息处理器实例"""
    from wx_Processer import MessageProcessor
    return MessageProcessor()

# 消息处理回调函数
def message_callback(chat_name, message_data):
    """
    收到新消息的回调函数，将消息转发到 MaiBot
    
    Args:
        chat_name (str): 聊天对象名称
        message_data (dict): 消息数据
    """
    global global_processor
    
    print(f"\n收到新消息 - {chat_name}:")
    print(f"发送者: {message_data['sender']}")
    print(f"内容: {message_data['content']}")
    print(f"类型: {message_data['type']}")
    print(f"时间: {message_data['timestamp']}")
    print("-" * 50)
    
    # 使用全局消息处理器处理消息并转发到 MaiBot
    if global_processor:
        result = global_processor.process_message(chat_name, message_data)
        
        # 打印处理结果
        if result.get("success"):
            print(f"消息已成功转发到 MaiBot")
        else:
            print(f"消息转发失败: {result.get('error')}")
    else:
        print("消息处理器未初始化")
        print(f"global_processor: {global_processor}")
        print(f"type: {type(global_processor)}")


# 主程序入口
if __name__ == "__main__":
    # 使用全局消息处理器实例（已在main.py中创建）
    # 创建监听器实例，使用配置文件中的目标聊天列表
    # 同时设置回调函数，将消息转发到 MaiBot
    listener = WeChatListener(
        target_chats=WX_TARGET_CHATS,
        callback=message_callback
    )
    
    print("微信消息监听器已启动，消息将转发到 MaiBot")
    print("WebSocket监听器将接收MaiBot的回复并发送到微信")
    print("按 Ctrl+C 停止监听")
    print("请确保已打开要监听的聊天窗口")
    print("-" * 50)
    
    # Router已在main.py中启动，这里不需要重复启动
    
    # 开始监听
    listener.start_listening()
