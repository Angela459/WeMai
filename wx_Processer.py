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
import re
from pathlib import Path
import time
from wx_image_watcher import WxImageWatcher
from pathlib import Path
from queue import Queue
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
        self.image_watcher = WxImageWatcher(Path(os.getcwd()) / "wxauto文件")
        self.image_watcher.start()
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
                    from wxauto import WeChat
                    import base64
                    import tempfile
                    import os
                    wechat = WeChat()
                    
                    # 检查是否是base64编码的图片数据
                    if isinstance(content, str) and (content.startswith('data:image/') or len(content) > 1000 and content.replace('+', '').replace('/', '').replace('=', '').isalnum()):
                        # 可能是base64编码的图片
                        try:
                            # 尝试解码base64数据
                            file_extension = '.png'  # 默认扩展名
                            if content.startswith('data:image/'):
                                # 处理data URL格式，提取文件类型
                                header, encoded = content.split(",", 1)
                                if 'gif' in header.lower():
                                    file_extension = '.gif'
                                elif 'jpeg' in header.lower() or 'jpg' in header.lower():
                                    file_extension = '.jpg'
                                elif 'png' in header.lower():
                                    file_extension = '.png'
                                image_data = base64.b64decode(encoded)
                            else:
                                # 处理纯base64编码，尝试检测文件类型
                                image_data = base64.b64decode(content)
                                # 检查GIF文件头
                                if image_data.startswith(b'GIF8'):
                                    file_extension = '.gif'
                                # 检查JPEG文件头
                                elif image_data.startswith(b'\xff\xd8\xff'):
                                    file_extension = '.jpg'
                                # 检查PNG文件头
                                elif image_data.startswith(b'\x89PNG'):
                                    file_extension = '.png'
                            
                            # 创建临时文件，使用正确的扩展名
                            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                                temp_file.write(image_data)
                                temp_file_path = temp_file.name
                            
                            # 发送图片文件
                            wechat.SendFiles(temp_file_path, receiver)
                            logger.info(f"已发送base64图片到微信: {receiver}")
                            
                            # 删除临时文件
                            try:
                                os.unlink(temp_file_path)
                            except:
                                pass
                                
                        except Exception as e:
                            logger.error(f"处理base64图片失败: {str(e)}")
                            # 如果base64解码失败，尝试作为文字发送
                            wechat.SendMsg(content, receiver)
                            logger.info(f"base64解码失败，发送文字内容: {receiver} - {content[:50]}...")
                    
                    # 检查是否是图片/表情包路径
                    elif isinstance(content, str) and (content.endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')) or content.startswith('[') and ']' in content):
                        # 如果是图片路径，使用SendFiles方法
                        if os.path.exists(content):
                            wechat.SendFiles(content, receiver)
                            logger.info(f"已发送图片到微信: {receiver} - {content}")
                        else:
                            # 如果文件不存在，尝试发送文字内容
                            wechat.SendMsg(content, receiver)
                            logger.info(f"图片文件不存在，发送文字内容: {receiver} - {content}")
                    else:
                        # 普通文字消息
                        wechat.SendMsg(content, receiver)
                        logger.info(f"已发送文字消息到微信: {receiver} - {content}")
                        
                except Exception as e:
                    logger.error(f"发送微信消息失败: {str(e)}")
                    raise e
            
            # 在线程池中执行并等待完成
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
            logger.info(f"处理消息: {message_data} ")
            # 转文字失败
            if message_data['content'] == "你的网络较慢，请稍候再试。":
                message_data['content'] = "[语音]"
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
        has_wxauto_path = 'wxauto文件' in content or '微信图片_' in content
        
        return (has_path_separator and has_image_extension) or has_wxauto_path



    def _extract_wechat_time_prefix(self, path: str):
        """
        从 wxauto 给的路径中提取时间前缀
        """
        name = os.path.basename(path)
        m = re.search(r"微信图片_(\d{12})", name)
        return m.group(1) if m else None

    def _find_real_wechat_image(self, fake_path: str, timeout=10):
        """
        在 wxauto文件 目录中查找真实微信图片（Windows 稳定版）
        """
        import time
        import re
        from pathlib import Path

        wxauto_dir = Path(os.getcwd()) / "wxauto文件"
        if not wxauto_dir.exists():
            logger.error(f"wxauto文件目录不存在: {wxauto_dir}")
            return None

        # ✅ 只提取前 14 位时间：YYYYMMDDHHMMSS
        name = os.path.basename(fake_path)
        m = re.search(r"微信图片_(\d{14})", name)
        if not m:
            logger.error(f"无法解析图片时间前缀: {name}")
            return None

        time_prefix = m.group(1)
        logger.warning(f"🔍 在 wxauto文件 中查找图片，时间前缀={time_prefix}")

        start = time.time()
        while time.time() - start < timeout:
            candidates = []

            for f in wxauto_dir.glob(f"微信图片_{time_prefix}*.jpg"):
                try:
                    stat = f.stat()
                    if stat.st_size > 0:
                        candidates.append((stat.st_mtime, f))
                except:
                    continue

            if candidates:
                # 选“最后写入完成”的那个
                candidates.sort(key=lambda x: x[0], reverse=True)
                best = candidates[0][1]
                logger.warning(f"✅ 命中真实微信图片文件: {best}")
                return str(best)

            time.sleep(0.2)

        logger.error(f"❌ 超时仍未找到微信图片: {time_prefix}")
        return None

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
        if self._is_image_path_message(content):
            try:
                real_path = self.image_watcher.queue.get(timeout=10)

                import base64
                import os

                # 读取图片
                with open(real_path, "rb") as f:
                    image_data = f.read()

                image_base64 = base64.b64encode(image_data).decode("utf-8")

                message_segment = {
                    "type": "image",
                    "data": image_base64
                }

                logger.warning(f"✅ 图片已读取并发送给 MaiBot: {real_path}")

                # ✅ 发送完成后删除图片，防止堆积
                try:
                    os.remove(real_path)
                    logger.warning(f"🗑️ 已删除微信图片文件: {real_path}")
                except Exception as e:
                    logger.error(f"删除图片失败（不影响主流程）: {e}")

                logger.warning(f"✅ 使用 watchdog 捕获的图片: {real_path}")

            except Exception as e:
                message_segment = {
                    "type": "text",
                    "data": "[图片接收失败]"
                }
                logger.error(f"watchdog 等待图片失败: {e}")

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
            # logger.info(f"发送消息到 MaiBot: {json.dumps(message, ensure_ascii=False)}")
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
