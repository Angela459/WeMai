# mq_Consumer.py
import time
import threading
import traceback
from queue import Queue, Empty
from wxauto import WeChat

# ======================================================
# 单线程微信发送器（核心）
# ======================================================

class WxSendWorker(threading.Thread):
    """
    独占一个 WeChat 实例
    串行处理所有发送任务
    """

    def __init__(self, task_queue: Queue):
        super().__init__(daemon=True)
        self.queue = task_queue
        self.wx = None
        self.running = True
        self._init_wx()

    def _init_wx(self):
        print("[WxWorker] 初始化 WeChat 实例")
        self.wx = WeChat()
        time.sleep(1)

    def _rebuild_wx(self, reason="unknown"):
        print(f"[WxWorker] ⚠️ 重建 WeChat 实例，原因: {reason}")
        try:
            del self.wx
        except Exception:
            pass
        self._init_wx()

    def run(self):
        print("[WxWorker] 发送线程已启动")

        while self.running:
            try:
                task = self.queue.get(timeout=1)
            except Empty:
                continue

            who = task["who"]
            content = task["content"]
            retry = task.get("retry", 1)

            success = self._send_with_retry(who, content, retry)

            if not success:
                print(f"[WxWorker] ⛔ 消息最终发送失败 -> {who}")

            self.queue.task_done()

    def _send_with_retry(self, who, content, retry):
        attempt = 0
        while attempt <= retry:
            attempt += 1
            try:
                print(f"[WxWorker] ▶ 发送尝试 {attempt} -> {who}")
                self.wx.ChatWith(who)
                time.sleep(0.3)
                self.wx.SendMsg(content)
                time.sleep(0.2)
                print(f"[WxWorker] ✅ 发送成功 -> {who}")
                return True

            except Exception as e:
                print(f"[WxWorker] ❌ 发送失败 -> {who}")
                print(f"[WxWorker] 异常类型: {type(e).__name__}")
                print(f"[WxWorker] 异常信息: {e}")
                traceback.print_exc()

                if attempt <= retry:
                    self._rebuild_wx(reason=type(e).__name__)
                    time.sleep(1)

        return False


# ======================================================
# 全局发送队列（缓冲高峰消息）
# ======================================================

send_queue = Queue(maxsize=5000)

# 启动单线程发送 worker
wx_worker = WxSendWorker(send_queue)
wx_worker.start()


# ======================================================
# 对外接口：消息入队
# ======================================================

def consume_msg(msg: dict):
    """
    msg 示例:
    {
        "from": "张三",
        "content": "你好"
    }
    """
    who = msg.get("from")
    content = msg.get("content")

    if not who or not content:
        print("[consume_msg] ⚠️ 非法消息:", msg)
        return

    task = {
        "who": who,
        "content": content,
        "retry": 1
    }

    try:
        send_queue.put(task, timeout=1)
        print(f"[consume_msg] ➕ 已入队 -> {who} | 队列长度: {send_queue.qsize()}")
    except Exception:
        print("[consume_msg] 🚨 发送队列已满，消息丢弃:", task)



def main(redis_client=None):
    print("[mq_Consumer] consumer main started")

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
            print("[mq_Consumer] 主循环异常:", e)
            traceback.print_exc()
            time.sleep(2)
