# Copyright (c) iGroup.
# All rights reserved.
"""内置看板生命周期。@author Kai @date 2026/10/26 10:43 @description 同一 EXE 内后台线程提供看板，退出助手时关闭。"""

import os
import sys
import threading
from pathlib import Path


def create_server():
    """创建同进程服务。@return Uvicorn 服务 @author Kai @date 2026/10/26 10:43"""
    # 源码启动时补入项目根目录；打包后模块及静态资源均已内置。
    root = Path(__file__).resolve().parents[1]
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(root.parent))
        os.environ.setdefault("DESK_HUB_SOURCE", str(root))
    import uvicorn
    from desk_hub.server import app
    return uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8765, log_config=None))


def start_dashboard(log):
    """随助手启动并返回关闭函数。@param log 应用日志 @return 关闭回调 @author Kai @date 2026/10/26 10:43"""
    try:
        server = create_server()
    except Exception:
        log.exception("内置看板初始化失败，考勤助手继续运行")
        return lambda: None

    def run():
        """隔离看板异常，不中止考勤主事件循环。@author Kai @date 2026/10/26 10:43"""
        try:
            server.run()
        except (Exception, SystemExit):
            log.exception("内置看板运行失败，请检查 8765 端口")

    # HTTP 和任务采集不占用 Qt 主线程。
    worker = threading.Thread(target=run, name="DeskHub", daemon=True)
    worker.start()

    def stop():
        """退出助手时关闭服务及连接。@author Kai @date 2026/10/26 10:43"""
        server.should_exit = True
        worker.join(timeout=4)

    return stop
