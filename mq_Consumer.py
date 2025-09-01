import asyncio
import json
import logging
from redis import asyncio as aioredis
from wxauto import WeChat
from config import REDIS_URL, REDIS_QUEUE_KEY, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT
import os

# 配置日志
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT
)

logger = logging.getLogger(__name__)

# 使用配置文件中的Redis连接信息
pool = aioredis.ConnectionPool.from_url(REDIS_URL)

# 微信实例
wx = WeChat()


async def process_task(task_data: str):
    try:
        logger.info("开始处理任务：" + task_data)
        task = json.loads(task_data)
        receiver = task.get('receiver')
        msg = task.get('msg')
        msg_type = task.get('type', 'text')  # 默认为文字类型
        msg_segments = task.get('segments', None)  # 多段消息

        if not receiver or (not msg and not msg_segments):
            logger.error(f"无效的任务数据: {task_data}")
            return

        # 处理多段消息
        if msg_segments:
            logger.info(f"处理多段消息，共{len(msg_segments)}段")
            for segment in msg_segments:
                segment_type = segment.get('type', 'text')
                segment_data = segment.get('data', '')
                await process_single_message(receiver, segment_data, segment_type)
        else:
            # 处理单段消息
            await process_single_message(receiver, msg, msg_type)

        logger.info("处理成功！")

    except json.JSONDecodeError:
        logger.error(f"解析任务数据失败: {task_data}")
    except Exception as e:
        logger.error(f"处理任务时发生错误: {str(e)}")

async def process_single_message(receiver, msg, msg_type):
    """处理单条消息"""
    try:
        # 根据消息类型选择发送方式
        if msg_type == 'image' or msg_type == 'file':
            # 图片或文件消息
            if os.path.exists(msg):
                wx.SendFiles(msg, receiver)
                logger.info(f"已发送文件到微信: {receiver} - {msg}")
            else:
                # 如果文件不存在，发送文字内容
                wx.SendMsg(msg, receiver)
                logger.info(f"文件不存在，发送文字内容: {receiver} - {msg}")
        elif msg_type == 'emoji' or (isinstance(msg, str) and (msg.startswith('data:image/') or len(msg) > 1000 and msg.replace('+', '').replace('/', '').replace('=', '').isalnum())):
            # 表情包或base64编码的图片
            try:
                import base64
                import tempfile
                
                # 尝试解码base64数据
                if msg.startswith('data:image/'):
                    # 处理data URL格式
                    header, encoded = msg.split(",", 1)
                    image_data = base64.b64decode(encoded)
                else:
                    # 处理纯base64编码
                    image_data = base64.b64decode(msg)
                
                # 创建临时文件
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
                    temp_file.write(image_data)
                    temp_file_path = temp_file.name
                
                # 发送图片文件
                wx.SendFiles(temp_file_path, receiver)
                logger.info(f"已发送base64图片到微信: {receiver}")
                
                # 删除临时文件
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
            except Exception as e:
                logger.error(f"处理base64图片失败: {str(e)}")
                # 如果base64解码失败，尝试作为文字发送
                wx.SendMsg(msg, receiver)
                logger.info(f"base64解码失败，发送文字内容: {receiver} - {msg[:50]}...")
        else:
            # 文字消息
            wx.SendMsg(msg, receiver)
            logger.info(f"已发送文字消息到微信: {receiver} - {msg}")

    except Exception as e:
        logger.error(f"处理单条消息时发生错误: {str(e)}")


async def main():
    """主函数：监听消息队列并处理消息"""
    redis = None
    try:
        # 创建Redis连接
        redis = aioredis.Redis.from_pool(pool)
        logger.info("消息队列服务启动成功")

        while True:
            try:
                # 从队列获取消息，设置5秒超时
                task = await redis.brpop([REDIS_QUEUE_KEY], timeout=5)
                if task:
                    await process_task(task[1].decode('utf-8'))
            except asyncio.CancelledError:
                logger.info("收到停止信号，正在关闭服务...")
                break
            except Exception as e:
                logger.error(f"处理消息时发生错误: {str(e)}")
                await asyncio.sleep(1)  # 发生错误时暂停1秒

    except Exception as e:
        logger.error(f"消息队列服务发生错误: {str(e)}")
    finally:
        # 清理资源
        if redis:
            await redis.aclose()
        await pool.aclose()
        logger.info("消息队列服务已关闭")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常退出: {str(e)}")
