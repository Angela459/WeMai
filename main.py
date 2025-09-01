import argparse
import asyncio
import logging
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

# 导入各个组件
from wx_Listener import WeChatListener, message_callback, set_global_processor, create_message_processor
from mq_Consumer import main as consumer_main
from config import WX_TARGET_CHATS, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT, LOG_FILE, API_HOST, API_PORT

# 配置日志
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

# 全局变量
stop_event = Event()
signal_handled = False

# 微信监听器进程
def run_wx_listener(target_chats=None):
    """
    运行微信消息监听器
    
    Args:
        target_chats (list, optional): 要监听的聊天对象列表
    """
    try:
        logger.info("启动微信消息监听器...")
        
        # 初始化全局消息处理器
        processor = create_message_processor()
        set_global_processor(processor)
        logger.info("全局消息处理器已初始化")
        
        # 启动Router（在后台线程中运行）
        import threading
        router_thread = threading.Thread(target=processor.start_router)
        router_thread.daemon = True
        router_thread.start()
        logger.info("Router已启动")
        
        # 显示监听的聊天对象及其哈希值，便于配置MaiBot的白名单
        if target_chats:
            import hashlib
            logger.info("监听的聊天对象及其ID哈希值（请将需要的群组ID添加到MaiBot的白名单中）：")
            for chat in target_chats:
                chat_id = hashlib.md5(chat.encode('utf-8')).hexdigest()
                logger.info(f"  {chat} -> {chat_id}")
        
        listener = WeChatListener(
            target_chats=target_chats,
            callback=message_callback
        )
        
        # 注册停止事件处理
        def check_stop():
            while not stop_event.is_set():
                time.sleep(1)
            listener.stop_listening()
        
        # 启动停止检查线程
        stop_thread = threading.Thread(target=check_stop)
        stop_thread.daemon = True
        stop_thread.start()
        
        # 开始监听
        listener.start_listening()
        
    except Exception as e:
        logger.error(f"微信监听器发生错误: {str(e)}")
        if not stop_event.is_set():
            logger.info("尝试重启微信监听器...")
            time.sleep(5)  # 等待5秒后重试
            run_wx_listener(target_chats)

# 消息队列消费者进程
async def run_mq_consumer():
    """运行消息队列消费者"""
    try:
        logger.info("启动消息队列消费者...")
        
        # 创建任务
        consumer_task = asyncio.create_task(consumer_main())
        
        # 等待停止事件
        while not stop_event.is_set():
            await asyncio.sleep(1)
        
        # 取消任务
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            logger.info("消息队列消费者已停止")
            
    except Exception as e:
        logger.error(f"消息队列消费者发生错误: {str(e)}")
        if not stop_event.is_set():
            logger.info("尝试重启消息队列消费者...")
            await asyncio.sleep(5)  # 等待5秒后重试
            await run_mq_consumer()

# 消息队列生产者进程（同步版本）
def run_mq_producer():
    """运行消息队列生产者（FastAPI应用）- 同步版本"""
    try:
        logger.info("启动消息队列生产者...")
        
        # 导入并运行FastAPI应用
        from mq_Producer import app
        import uvicorn
        
        # 设置uvicorn日志配置
        log_config = uvicorn.config.LOGGING_CONFIG
        log_config["formatters"]["access"]["fmt"] = LOG_FORMAT
        
        # 在新线程中设置事件循环并启动服务器
        def run_server():
            try:
                # 设置事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # 直接使用 uvicorn.run() 启动服务器
                uvicorn.run(
                    app,
                    host=API_HOST,
                    port=API_PORT,
                    log_config=log_config,
                    access_log=True,
                    loop=loop  # 显式指定事件循环
                )
            except Exception as e:
                logger.error(f"服务器运行错误: {str(e)}")
        
        # 在单独的线程中运行服务器
        server_thread = threading.Thread(target=run_server)
        server_thread.daemon = True
        server_thread.start()
        
        # 等待服务器线程结束
        server_thread.join()
        
    except Exception as e:
        logger.error(f"消息队列生产者发生错误: {str(e)}")
        if not stop_event.is_set():
            logger.info("尝试重启消息队列生产者...")
            time.sleep(5)  # 等待5秒后重试
            run_mq_producer()

# 消息队列生产者进程（异步版本）
async def run_mq_producer_async():
    """运行消息队列生产者（FastAPI应用）- 异步版本"""
    try:
        logger.info("启动消息队列生产者...")
        
        # 导入并运行FastAPI应用
        from mq_Producer import app
        import uvicorn
        
        # 设置uvicorn日志配置
        log_config = uvicorn.config.LOGGING_CONFIG
        log_config["formatters"]["access"]["fmt"] = LOG_FORMAT
        
        # 创建服务器配置
        config = uvicorn.Config(
            app,
            host=API_HOST,
            port=API_PORT,
            log_config=log_config,
            access_log=True
        )
        
        # 创建服务器实例
        server = uvicorn.Server(config)
        
        # 注册停止事件处理
        def check_stop():
            while not stop_event.is_set():
                time.sleep(1)
            logger.info("正在关闭FastAPI服务器...")
            server.should_exit = True
        
        # 启动停止检查线程
        import threading
        stop_thread = threading.Thread(target=check_stop)
        stop_thread.daemon = True
        stop_thread.start()
        
        # 启动服务器
        await server.serve()
        
    except Exception as e:
        logger.error(f"消息队列生产者发生错误: {str(e)}")
        if not stop_event.is_set():
            logger.info("尝试重启消息队列生产者...")
            await asyncio.sleep(5)  # 等待5秒后重试
            await run_mq_producer_async()

# 信号处理函数
def handle_signal(sig, frame):
    """处理终止信号"""
    # 防止重复处理信号
    global signal_handled
    if signal_handled:
        return
    
    signal_handled = True
    logger.info(f"收到信号 {sig}，正在优雅停止...")
    stop_event.set()
    
    # 设置强制退出定时器（30秒后强制退出）
    def force_exit():
        logger.warning("程序未能在30秒内正常退出，强制终止...")
        import os
        os._exit(1)
    
    import threading
    force_timer = threading.Timer(30.0, force_exit)
    force_timer.daemon = True
    force_timer.start()

# 主函数
async def main(args):
    """
    主函数
    
    Args:
        args: 命令行参数
    """
    # 注册信号处理
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    # 创建线程池
    with ThreadPoolExecutor(max_workers=3) as executor:
        tasks = []
        
        # 根据参数启动相应的服务
        if args.all or args.wx_to_maibot:
            # 启动微信监听器
            wx_future = executor.submit(
                run_wx_listener, 
                args.target_chats.split(',') if args.target_chats else WX_TARGET_CHATS
            )
            tasks.append(wx_future)
        
        if args.all or args.maibot_to_wx:
            # 启动消息队列消费者
            consumer_task = asyncio.create_task(run_mq_consumer())
            
            # 启动消息队列生产者（在主线程中运行）
            producer_task = asyncio.create_task(run_mq_producer_async())
        
        # 等待停止事件
        try:
            while not stop_event.is_set():
                await asyncio.sleep(1)
                
                # 检查任务状态
                for i, future in enumerate(tasks):
                    if future.done() and not stop_event.is_set():
                        # 如果任务异常终止，记录错误
                        try:
                            future.result()
                        except Exception as e:
                            logger.error(f"任务 {i} 异常终止: {str(e)}")
        except asyncio.CancelledError:
            logger.info("主任务被取消")
        
        # 设置停止事件（以防万一）
        stop_event.set()
        
        logger.info("正在等待所有任务完成...")
        
        # 取消消费者和生产者任务
        if args.all or args.maibot_to_wx:
            consumer_task.cancel()
            producer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass
            try:
                await producer_task
            except asyncio.CancelledError:
                pass
        
        # 等待最多10秒让其他任务完成
        timeout = time.time() + 10
        while time.time() < timeout:
            if all(future.done() for future in tasks):
                break
            await asyncio.sleep(0.5)
        
        # 如果还有任务未完成，记录警告
        for i, future in enumerate(tasks):
            if not future.done():
                logger.warning(f"任务 {i} 未能正常结束")
        
        logger.info("所有服务已停止")

if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="WePush - 微信消息转发服务")
    
    # 服务选择参数
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--all', action='store_true', help='启动所有服务（默认）')
    group.add_argument('--wx-to-maibot', action='store_true', help='仅启动微信到MaiBot的消息转发')
    group.add_argument('--maibot-to-wx', action='store_true', help='仅启动MaiBot到微信的消息转发')
    
    # 其他参数
    parser.add_argument('--target-chats', type=str, help='要监听的微信聊天对象，多个用逗号分隔')
    
    # 解析参数
    args = parser.parse_args()
    
    # 如果没有指定服务，默认启动所有服务
    if not (args.all or args.wx_to_maibot or args.maibot_to_wx):
        args.all = True
    
    # 打印启动信息
    logger.info("=" * 50)
    logger.info("WePush - 微信消息转发服务")
    logger.info("=" * 50)
    
    if args.all:
        logger.info("启动模式: 全部服务")
    elif args.wx_to_maibot:
        logger.info("启动模式: 仅微信到MaiBot")
    elif args.maibot_to_wx:
        logger.info("启动模式: 仅MaiBot到微信")
    
    if args.target_chats:
        logger.info(f"监听聊天: {args.target_chats}")
    else:
        logger.info("监听聊天: 所有聊天")
    
    logger.info("=" * 50)
    
    # 运行主函数
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常退出: {str(e)}")
        sys.exit(1)
