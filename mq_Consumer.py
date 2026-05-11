import asyncio
import json
import logging

from redis import asyncio as aioredis

from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL, REDIS_QUEUE_KEY, REDIS_URL
from wechat_adapter import get_backend_description, send_message


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
)

logger = logging.getLogger(__name__)
pool = aioredis.ConnectionPool.from_url(REDIS_URL)


async def process_task(task_data: str):
    try:
        logger.info("Processing task: %s", task_data)
        task = json.loads(task_data)
        receiver = task.get("receiver")
        msg = task.get("msg")
        msg_type = task.get("type", "text")
        msg_segments = task.get("segments")

        if not receiver or (not msg and not msg_segments):
            logger.error("Invalid task payload: %s", task_data)
            return

        if msg_segments:
            logger.info("Processing segmented message with %s parts", len(msg_segments))
            for segment in msg_segments:
                await process_single_message(
                    receiver=receiver,
                    msg=segment.get("data", ""),
                    msg_type=segment.get("type", "text"),
                )
        else:
            await process_single_message(receiver=receiver, msg=msg, msg_type=msg_type)

        logger.info("Task processed successfully")
    except json.JSONDecodeError:
        logger.error("Failed to parse task payload: %s", task_data)
    except Exception as exc:
        logger.error("Unexpected error while processing task: %s", exc)


async def process_single_message(receiver, msg, msg_type):
    try:
        send_message(receiver=receiver, content=msg, msg_type=msg_type)
        logger.info("Sent message via %s: %s - %s", get_backend_description(), receiver, msg_type)
    except Exception as exc:
        logger.error("Failed to process single message: %s", exc)


async def main():
    redis = None
    try:
        redis = aioredis.Redis.from_pool(pool)
        logger.info("Queue consumer started")

        while True:
            try:
                task = await redis.brpop([REDIS_QUEUE_KEY], timeout=5)
                if task:
                    await process_task(task[1].decode("utf-8"))
            except asyncio.CancelledError:
                logger.info("Shutdown signal received, stopping queue consumer")
                break
            except Exception as exc:
                logger.error("Error while handling queue message: %s", exc)
                await asyncio.sleep(1)
    except Exception as exc:
        logger.error("Queue consumer crashed: %s", exc)
    finally:
        if redis:
            await redis.aclose()
        await pool.aclose()
        logger.info("Queue consumer stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program interrupted by user")
    except Exception as exc:
        logger.error("Program exited with error: %s", exc)
