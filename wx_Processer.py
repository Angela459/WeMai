import json
import logging
import time
import hashlib
import requests
import asyncio
import websockets
import threading
from datetime import datetime
from config import MAIBOT_API_URL, PLATFORM_ID
from maim_message import Router, RouteConfig, TargetConfig, MessageBase, BaseMessageInfo, UserInfo, GroupInfo, Seg
import os # Added for file existence check
from wechat_adapter import send_message as send_wechat_message

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

# MaiBot API 配置已移动到config.py

class MessageProcessor:
    def __init__(self, platform=PLATFORM_ID):
        """
        初始化消息处理器
        
        Args:
            platform (str): 消息平台标识，默认使用配置文件中的PLATFORM_ID
        """
        self.platform = platform
        self.router = None
        self.router_task = None
        # 消息发送队列，确保按顺序发送
        self.send_queue = None  # 将在start_router中初始化
        self.send_task = None
        logger.info(f"消息处理器初始化成功，平台：{platform}")
        
        # 初始化Router
        self._init_router()
    
    def _init_router(self):
        """初始化Router用于与MaiBot通信"""
        try:
            # 配置路由
            route_config = RouteConfig(
                route_config={
                    self.platform: TargetConfig(
                        url=MAIBOT_API_URL,
                        token=None  # 如果需要认证，在这里设置token
                    )
                }
            )
            
            # 创建Router实例
            self.router = Router(route_config)
            
            # 注册消息处理器
            self.router.register_class_handler(self._handle_maibot_response)
            
            logger.info(f"Router初始化成功，平台：{self.platform}")
        except Exception as e:
            logger.error(f"Router初始化失败: {str(e)}")
    
    async def _process_send_queue(self):
        """处理消息发送队列，确保按顺序发送"""
        while True:
            try:
                # 从队列获取消息，等待最多5秒
                receiver, content = await asyncio.wait_for(self.send_queue.get(), timeout=5.0)
                
                # 执行实际的发送操作
                await self._send_to_wechat_sync(receiver, content)
                
                # 标记任务完成
                self.send_queue.task_done()
            except asyncio.TimeoutError:
                # 超时继续循环
                continue
            except Exception as e:
                logger.error(f"处理发送队列时发生错误: {str(e)}")
                import traceback
                logger.error(f"错误详情: {traceback.format_exc()}")
    
    def start_router(self):
        """启动Router"""
        try:
            if self.router:
                # 创建新的事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # 初始化消息发送队列
                self.send_queue = asyncio.Queue()
                
                # 启动消息发送队列处理任务
                self.send_task = loop.create_task(self._process_send_queue())
                logger.info("消息发送队列已启动")
                
                # 启动Router
                self.router_task = loop.run_until_complete(self.router.run())
                logger.info("Router已启动")
        except Exception as e:
            logger.error(f"Router启动失败: {str(e)}")
    
    async def _handle_maibot_response(self, message):
        """处理来自MaiBot的回复消息"""
        try:
            logger.info(f"收到原始消息: {type(message)} - {message}")
            
            # 如果message是字典，转换为MessageBase对象
            if isinstance(message, dict):
                message = MessageBase.from_dict(message)
                logger.info("消息已转换为MessageBase对象")
            
            # 提取消息ID和内容用于日志
            message_info = message.message_info
            message_segment = message.message_segment
            message_id = getattr(message_info, 'message_id', None) if message_info else None
            
            # 提取消息内容预览
            if hasattr(message_segment, 'type') and message_segment.type == 'text':
                content_preview = message_segment.data[:100] if message_segment.data else ''
            else:
                content_preview = str(message_segment)[:100]
            
            logger.info(f"收到来自MaiBot的回复 [消息ID: {message_id}]: {message_segment}")
            logger.info(f"消息内容预览: {content_preview}")
            
            # 提取回复信息
            
            # 获取接收者信息
            user_info = message_info.user_info
            group_info = message_info.group_info
            
            # 确定接收者
            if group_info and group_info.group_name:
                receiver = group_info.group_name
            elif user_info and user_info.user_nickname:
                receiver = user_info.user_nickname
            else:
                logger.error("无法确定回复接收者")
                return
            
            # 处理消息段
            await self._process_message_segments(message_segment, receiver)
                
        except Exception as e:
            logger.error(f"处理MaiBot回复时发生错误: {str(e)}")
            # 添加更详细的错误信息
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
    
    async def _process_message_segments(self, message_segment, receiver):
        """递归处理消息段，支持多段消息"""
        try:
            if hasattr(message_segment, 'type'):
                if message_segment.type == "seglist":
                    # 多段消息，递归处理每个段
                    logger.info(f"处理多段消息，共{len(message_segment.data)}段")
                    for segment in message_segment.data:
                        await self._process_message_segments(segment, receiver)
                elif message_segment.type == "text":
                    # 文字消息
                    reply_content = message_segment.data
                    await self._send_to_wechat(receiver, reply_content)
                    logger.info(f"已处理文字消息: {reply_content[:50]}...")
                elif message_segment.type == "image":
                    # 图片消息
                    image_path = message_segment.data
                    await self._send_to_wechat(receiver, image_path)
                    logger.info(f"已处理图片消息")
                elif message_segment.type == "file":
                    # 文件消息
                    file_path = message_segment.data
                    await self._send_to_wechat(receiver, file_path)
                    logger.info(f"已处理文件消息")
                elif message_segment.type == "emoji":
                    # 表情包消息
                    emoji_data = message_segment.data
                    await self._send_to_wechat(receiver, emoji_data)
                    logger.info(f"已处理表情包消息")
                elif message_segment.type == "reply":
                    # 回复引用消息，只记录日志，不发送到微信
                    logger.info(f"跳过回复引用消息: {message_segment.data}")
                elif message_segment.type == "at":
                    # @消息，转换为文字格式
                    at_content = f"[@{message_segment.data}]"
                    await self._send_to_wechat(receiver, at_content)
                    logger.info(f"已处理@消息: {at_content}")
                elif message_segment.type == "voice":
                    # 语音消息，发送提示文字
                    voice_content = "[发了一段语音，网卡了加载不出来]"
                    await self._send_to_wechat(receiver, voice_content)
                    logger.info(f"已处理语音消息")
                elif message_segment.type == "notify":
                    # 通知消息，通常不需要发送到微信
                    logger.info(f"跳过通知消息: {message_segment.data}")
                else:
                    # 其他类型消息，尝试作为文字发送
                    reply_content = str(message_segment.data)
                    await self._send_to_wechat(receiver, reply_content)
                    logger.info(f"已处理其他类型消息: {message_segment.type}")
            else:
                # 如果没有type属性，尝试直接发送数据
                reply_content = str(message_segment.data)
                await self._send_to_wechat(receiver, reply_content)
                logger.info(f"已处理无类型消息")
                
        except Exception as e:
            logger.error(f"处理消息段时发生错误: {str(e)}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
    
    async def _send_to_wechat(self, receiver, content):
        """发送消息到微信（添加到队列，确保按顺序发送）"""
        try:
            # 检查队列是否已初始化
            if self.send_queue is None:
                logger.warning("消息发送队列未初始化，直接发送消息")
                await self._send_to_wechat_sync(receiver, content)
                return
            
            # 将消息添加到发送队列
            await self.send_queue.put((receiver, content))
            logger.info(f"消息已添加到发送队列: {receiver} - {content[:50]}...")
        except Exception as e:
            logger.error(f"添加消息到发送队列失败: {str(e)}")
            # 如果队列失败，尝试直接发送
            try:
                await self._send_to_wechat_sync(receiver, content)
            except Exception as e2:
                logger.error(f"直接发送消息也失败: {str(e2)}")
    
    async def _send_to_wechat_sync(self, receiver, content):
        """实际执行发送消息到微信的操作"""
        try:
            # 使用asyncio在线程池中执行同步操作
            import asyncio
            import concurrent.futures
            
            def send_message():
                try:
                    msg_type = 'text'
                    if isinstance(content, str) and os.path.exists(content):
                        msg_type = 'file'
                    elif isinstance(content, str) and (content.startswith('data:image/') or len(content) > 1000 and content.replace('+', '').replace('/', '').replace('=', '').isalnum()):
                        msg_type = 'emoji'
                    elif isinstance(content, str) and content.endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                        msg_type = 'image'

                    send_wechat_message(receiver=receiver, content=content, msg_type=msg_type)
                except Exception as e:
                    logger.error(f"????????: {str(e)}")
                    raise e
            
            # ????????????
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                await loop.run_in_executor(executor, send_message)
            
        except Exception as e:
            logger.error(f"发送微信消息时发生错误: {str(e)}")
    
    def process_message(self, chat_name, message_data):
        """
        处理微信消息并转发到 MaiBot
        
        Args:
            chat_name (str): 聊天对象名称
            message_data (dict): 消息数据，包含 sender, content, type, timestamp 等信息
        
        Returns:
            dict: MaiBot 的响应结果
        """
        try:
            # 记录接收到的消息
            logger.info(f"处理消息: {chat_name} - {message_data['sender']}: {message_data['content']}")
            
            # 构建 MaiBot 消息体
            maibot_message = self._build_maibot_message(chat_name, message_data)
            
            # 发送消息到 MaiBot
            response = self._send_to_maibot(maibot_message)
            
            return response
        except Exception as e:
            logger.error(f"处理消息时发生错误: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _is_image_path_message(self, content: str) -> bool:
        """
        检查是否是图片路径消息
        
        Args:
            content (str): 消息内容
        
        Returns:
            bool: 是否是图片路径消息
        """
        if not content:
            return False
        
        # 检查是否包含图片路径特征
        has_path_separator = '\\' in content or '/' in content
        has_image_extension = any(ext in content.lower() for ext in ['.jpg', '.png', '.gif', '.bmp', '.jpeg'])
        has_pywechat_path = '??????????' in content or '????_' in content
        
        return (has_path_separator and has_image_extension) or has_pywechat_path

    def _build_maibot_message(self, chat_name, message_data):
        """
        构建 MaiBot 消息体
        
        Args:
            chat_name (str): 聊天对象名称
            message_data (dict): 消息数据
        
        Returns:
            dict: MaiBot 格式的消息体
        """
        # 提取消息信息
        sender = message_data['sender']
        content = message_data['content']
        msg_type = message_data['type']
        timestamp = time.time()  # 使用当前时间戳
        
        # 判断是群聊还是私聊
        is_group_chat = not (chat_name == sender)
        
        # 生成包含用户特征的消息 ID
        # 结合发送者、聊天名称、时间戳和消息内容前20个字符生成哈希
        id_source = f"{sender}_{chat_name}_{timestamp}_{content[:20]}"
        message_id = hashlib.md5(id_source.encode('utf-8')).hexdigest()
        
        # 使用 MD5 哈希生成用户ID和群组ID
        user_id_hash = hashlib.md5(sender.encode('utf-8')).hexdigest()
        
        # 构建基本消息信息
        message_info = {
            "platform": self.platform,
            "message_id": message_id,
            "time": timestamp,
            "format_info": {
                "content_format": "text",
                "accept_format": "text,emoji"
            }
        }
        
        # 添加用户信息
        message_info["user_info"] = {
            "platform": self.platform,
            "user_id": user_id_hash,  # 使用哈希后的用户ID
            "user_nickname": sender
        }
        
        # 如果是群聊，添加群组信息
        if is_group_chat:
            # 使用 MD5 哈希生成群组ID
            group_id_hash = hashlib.md5(chat_name.encode('utf-8')).hexdigest()
            
            message_info["group_info"] = {
                "platform": self.platform,
                "group_id": group_id_hash,  # 使用哈希后的群组ID
                "group_name": chat_name
            }
            # 在群聊中，添加用户的群昵称
            message_info["user_info"]["user_cardname"] = sender
        
        # 构建消息段
        # 检查是否启用图像识别功能
        import os
        image_recognition_enabled = os.getenv('IMAGE_RECOGNITION_ENABLED', 'true').lower() == 'true'
        
        # 检查是否是图片路径消息且启用了图像识别
        if image_recognition_enabled and self._is_image_path_message(content):
            # 如果是图片路径，读取图片并转换为base64
            try:
                import base64
                import os
                
                if os.path.exists(content):
                    with open(content, 'rb') as f:
                        image_data = f.read()
                    image_base64 = base64.b64encode(image_data).decode('utf-8')
                    
                    # 发送image类型的消息
                    message_segment = {
                        "type": "image",
                        "data": image_base64
                    }
                    logger.info(f"检测到图片路径，发送image类型消息: {content}")
                else:
                    # 文件不存在，发送文本消息
                    message_segment = {
                        "type": "text",
                        "data": f"[图片文件不存在: {content}]"
                    }
                    logger.warning(f"图片文件不存在: {content}")
            except Exception as e:
                # 读取失败，发送文本消息
                message_segment = {
                    "type": "text",
                    "data": f"[图片读取失败: {content}, 错误: {str(e)}]"
                }
                logger.error(f"图片读取失败: {content}, 错误: {e}")
        else:
            # 普通文本消息
            message_segment = {
                "type": "text",
                "data": content
            }
        
        # 组合完整消息体 - 按照maim_message库的格式
        maibot_message = {
            "message_info": message_info,
            "message_segment": message_segment,
            "raw_message": None  # 添加raw_message字段
        }
        
        return maibot_message
    
    def _send_to_maibot(self, message):
        """
        发送消息到 MaiBot API
        
        Args:
            message (dict): MaiBot 格式的消息体
        
        Returns:
            dict: API 响应结果
        """
        try:
            # 记录发送的消息
            logger.info(f"发送消息到 MaiBot: {json.dumps(message, ensure_ascii=False)}")
            logger.info(f"请求URL: {MAIBOT_API_URL}")
            
            # 使用Router发送消息
            if self.router:
                # 创建新的事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # 将字典消息转换为MessageBase对象
                message_base = self._dict_to_message_base(message)
                
                # 发送消息
                result = loop.run_until_complete(self.router.send_message(message_base))
                loop.close()
                
                return {"success": True, "data": "消息已发送"}
            else:
                logger.error("Router未初始化")
                return {"success": False, "error": "Router未初始化"}
        
        except Exception as e:
            logger.error(f"与 MaiBot 通信时发生未知错误: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _dict_to_message_base(self, message_dict):
        """将字典消息转换为MessageBase对象"""
        try:
            # 提取消息信息
            message_info_dict = message_dict["message_info"]
            message_segment_dict = message_dict["message_segment"]
            
            # 构建用户信息
            user_info = UserInfo(
                platform=message_info_dict["user_info"]["platform"],
                user_id=message_info_dict["user_info"]["user_id"],
                user_nickname=message_info_dict["user_info"]["user_nickname"]
            )
            
            # 构建群组信息（如果有）
            group_info = None
            if "group_info" in message_info_dict:
                group_info = GroupInfo(
                    platform=message_info_dict["group_info"]["platform"],
                    group_id=message_info_dict["group_info"]["group_id"],
                    group_name=message_info_dict["group_info"]["group_name"]
                )
            
            # 构建消息段
            message_segment = Seg(
                type=message_segment_dict["type"],
                data=message_segment_dict["data"]
            )
            
            # 构建消息信息
            message_info = BaseMessageInfo(
                platform=message_info_dict["platform"],
                message_id=message_info_dict["message_id"],
                time=message_info_dict["time"],
                user_info=user_info,
                group_info=group_info,
                format_info=message_info_dict["format_info"]
            )
            
            # 构建MessageBase对象
            message_base = MessageBase(
                message_info=message_info,
                message_segment=message_segment,
                raw_message=message_dict.get("raw_message")
            )
            
            return message_base
            
        except Exception as e:
            logger.error(f"转换消息格式失败: {str(e)}")
            raise e
    

    



# 示例：如何使用消息处理器
if __name__ == "__main__":
    # 创建消息处理器实例
    processor = MessageProcessor()
    
    # 模拟消息数据
    chat_name = "测试群"
    message_data = {
        "sender": "张三",
        "content": "你好，机器人",
        "type": "friend",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # 处理消息
    result = processor.process_message(chat_name, message_data)
    print(f"处理结果: {result}")
