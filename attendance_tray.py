# Copyright (c) iGroup.
# All rights reserved.
"""
考勤助手（Windows 托盘版）

给同事：先运行 build_exe.ps1 打出 dist/AttendanceHelper.exe，对方双击即可。

开发启动：
  python attendance_tray.py
  wscript //nologo start.vbs

@author Kai
@date 2026/07/23 15:35
@description 入口脚本；业务在 attendance_helper 包
"""

from __future__ import annotations

import sys

# 必须在 import requests 之前绑定 CA 证书，避免路径被缓存到 Temp\\_MEI*
from attendance_helper.ssl_certs import ensure_ca_bundle

ensure_ca_bundle()

from attendance_helper.cli import run_check
from attendance_helper.config import S
from attendance_helper.paths import LOG
from attendance_helper.util import mask_token


def main() -> None:
    """
    程序入口。

    @author Kai
    @date 2026/07/23 15:35
    """
    args = set(sys.argv[1:])
    # @author Kai @date 2026/10/26 10:43：仅供打包烟测的内置服务入口，不启动第二个 EXE。
    if "--desk-hub-only" in args:
        from attendance_helper.desk_hub_runtime import create_server
        create_server().run()
        return
    if "--check" in args:
        code = run_check(do_open_door=("--open-door" in args))
        sys.exit(code)

    try:
        from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon
        from attendance_helper.ui.tray_app import build_tray_app, ensure_single_instance
    except Exception as exc:  # noqa: BLE001
        # @author Kai @date 2026/10/26 10:43：无控制台版也落盘启动异常，方便定位 DLL 与模块依赖。
        LOG.exception("托盘界面初始化失败")
        if sys.stdout is not None:
            print(f"请先安装依赖: pip install -r requirements.txt\n{exc}")
        sys.exit(1)

    if not ensure_single_instance():
        LOG.info("已有实例在运行，本次启动退出")
        sys.exit(0)

    app = build_tray_app()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "无法启动", "当前系统不支持托盘图标")
        sys.exit(1)

    LOG.info(
        "AttendanceHelper 启动 company=%s token=%s door_device=%s",
        S.company_name,
        mask_token(S.attendance_token),
        S.door_device_id or "(empty)",
    )
    # @author Kai @date 2026/10/26 10:43：桌面助手统一拥有看板生命周期，CLI 检查模式不启动服务。
    from attendance_helper.desk_hub_runtime import start_dashboard
    stop_dashboard = start_dashboard(LOG)
    app.aboutToQuit.connect(stop_dashboard)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
