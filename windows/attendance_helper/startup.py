# Copyright (c) iGroup China.
# All rights reserved.
"""
开机自启动（用户 Startup 快捷方式，无需管理员）。

@author Kai
@date 2026/07/23 15:35
@description 一键启用/取消；兼容 .py 开发与 .exe 打包
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .paths import LOG, ROOT, is_frozen


SHORTCUT_NAME = "AttendanceHelper.lnk"


def startup_dir() -> Path:
    """
    Windows「启动」文件夹。

    @return Startup 目录
    @author Kai
    @date 2026/07/23 15:35
    """
    appdata = os.environ.get("APPDATA", "")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def shortcut_path() -> Path:
    """开机快捷方式完整路径。"""
    return startup_dir() / SHORTCUT_NAME


def launch_target() -> tuple[str, str, str]:
    """
    返回 (目标程序, 参数, 工作目录)。

    @return target, args, cwd
    @author Kai
    @date 2026/07/23 15:35
    """
    if is_frozen():
        return str(Path(sys.executable).resolve()), "", str(ROOT)

    # 开发模式：用 start.vbs 静默启动，避免弹出 CMD
    vbs = ROOT / "start.vbs"
    wscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"
    if vbs.exists() and wscript.exists():
        return str(wscript), f'//nologo "{vbs}"', str(ROOT)

    pythonw = Path(sys.executable)
    # 尽量用 pythonw
    if pythonw.name.lower() == "python.exe":
        candidate = pythonw.with_name("pythonw.exe")
        if candidate.exists():
            pythonw = candidate
    script = ROOT / "attendance_tray.py"
    return str(pythonw), f'"{script}"', str(ROOT)


def is_startup_enabled() -> bool:
    """是否已设置开机自启。"""
    return shortcut_path().exists()


def enable_startup() -> tuple[bool, str]:
    """
    一键写入开机启动项。

    @return (成功, 说明)
    @author Kai
    @date 2026/07/23 15:35
    """
    target, args, cwd = launch_target()
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)

    # 用 PowerShell 创建 .lnk，不依赖额外包
    ps = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$s = $w.CreateShortcut('{_ps_escape(str(link))}'); "
        f"$s.TargetPath = '{_ps_escape(target)}'; "
        f"$s.Arguments = '{_ps_escape(args)}'; "
        f"$s.WorkingDirectory = '{_ps_escape(cwd)}'; "
        "$s.WindowStyle = 7; "
        "$s.Description = 'AttendanceHelper'; "
        "$s.Save()"
    )
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if proc.returncode != 0 or not link.exists():
            err = (proc.stderr or proc.stdout or "创建快捷方式失败").strip()
            LOG.warning("启用自启失败: %s", err)
            return False, err[:120]
        LOG.info("已启用开机自启: %s -> %s %s", link, target, args)
        return True, str(link)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("启用自启异常: %s", exc)
        return False, str(exc)[:120]


def disable_startup() -> tuple[bool, str]:
    """
    取消开机自启。

    @return (成功, 说明)
    @author Kai
    @date 2026/07/23 15:35
    """
    link = shortcut_path()
    try:
        if link.exists():
            link.unlink()
        LOG.info("已取消开机自启")
        return True, "已取消开机自启"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:120]


def _ps_escape(value: str) -> str:
    """PowerShell 单引号字符串转义。"""
    return value.replace("'", "''")
