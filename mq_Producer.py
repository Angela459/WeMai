import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import asyncio as aioredis
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

from config import REDIS_URL, REDIS_QUEUE_KEY, API_HOST, API_PORT, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT

# 配置日志
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT
)


logger = logging.getLogger(__name__)


# 使用配置文件中的Redis连接信息
pool = aioredis.ConnectionPool.from_url(REDIS_URL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动前的操作
    redis = aioredis.Redis.from_pool(pool)
    await redis.delete(REDIS_QUEUE_KEY)
    await redis.aclose()
    
    yield
    
    # 关闭时的操作
    await pool.aclose()


app = FastAPI(lifespan=lifespan)


# 自定义全局错误信息
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=200, content={"code": 0, "msg": "请求失败"})


# 自定义全局错误信息
@app.exception_handler(RequestValidationError)
async def request_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=200, content={"code": 0, "msg": "请求失败"})


# 接收来自 MaiBot 的消息
@app.post("/api/message")
async def process_maibot_message(request: Request):
    try:
        # 获取原始请求体
        data = await request.json()
        logger.info(f"接收到 MaiBot 消息: {json.dumps(data, ensure_ascii=False)}")
        
        # 提取消息信息
        message_info = data.get('message_info', {})
        message_segment = data.get('message_segment', {})
        
        # 如果没有消息信息或消息段，返回错误
        if not message_info or not message_segment:
            logger.error("消息格式不正确，缺少必要字段")
            return {"code": 0, "msg": "消息格式不正确"}
        
        # 提取接收者信息
        user_info = message_info.get('user_info', {})
        group_info = message_info.get('group_info', {})
        
        # 提取消息内容
        msg_type = message_segment.get('type')
        msg_data = message_segment.get('data')
        
        if not msg_data or msg_type != 'text':
            logger.error(f"不支持的消息类型或消息内容为空: {msg_type}")
            return {"code": 0, "msg": "不支持的消息类型或消息内容为空"}
        
        # 确定接收者
        # 优先使用群名称，如果有群信息
        if group_info and group_info.get('group_name'):
            receiver = group_info.get('group_name')
        # 如果没有群信息，使用用户昵称
        elif user_info and user_info.get('user_nickname'):
            receiver = user_info.get('user_nickname')
        else:
            logger.error("无法确定消息接收者")
            return {"code": 0, "msg": "无法确定消息接收者"}
        
        # 构造符合 Redis 队列格式的消息
        redis_message = {
            "receiver": receiver,
            "msg": msg_data
        }
        
        # 从应用状态获取连接池
        redis = aioredis.Redis.from_pool(pool)
        
        # 推入到队列
        await redis.lpush(REDIS_QUEUE_KEY, json.dumps(redis_message, ensure_ascii=False))
        queue_size = await redis.llen(REDIS_QUEUE_KEY)
        await redis.aclose()
        
        logger.info(f"消息已添加到队列: {json.dumps(redis_message, ensure_ascii=False)}")
        return {"code": 1, "taskId": queue_size, "msg": "消息已添加到队列"}
        
    except json.JSONDecodeError:
        logger.error("解析 JSON 数据失败")
        return {"code": 0, "msg": "无效的 JSON 格式"}
    except Exception as e:
        logger.error(f"处理 MaiBot 消息时发生错误: {str(e)}")
        return {"code": 0, "msg": f"系统错误: {str(e)}"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=API_HOST, port=API_PORT)
