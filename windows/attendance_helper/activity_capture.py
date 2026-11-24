# Copyright (c) iGroup China.
# All rights reserved.
"""
读取当前前台窗口与休息状态。

@author Kai
@date 2026/09/29 15:12
@description 锁屏或超过 1 分钟无鼠标键盘操作时只标记休息，不读取窗口标题
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .activity_classify import BROWSER_NAMES, IDLE_REST_SECONDS, needs_window_title
from .paths import LOG

# 查询进程映像名，不需要调试权限
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# 打不开输入桌面时视为锁屏
_DESKTOP_SWITCHDESKTOP = 0x0100

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_user32.OpenInputDesktop.restype = wintypes.HANDLE
_user32.CloseDesktop.argtypes = [wintypes.HANDLE]
_user32.CloseDesktop.restype = wintypes.BOOL
_user32.GetLastInputInfo.restype = wintypes.BOOL

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.GetTickCount.restype = wintypes.DWORD

# 采样失败只记一次，避免每 2 秒刷一条日志
_CAPTURE_ERROR_LOGGED = False
# 地址栏 UI Automation 也只记一次失败
_ADDRESS_ERROR_LOGGED = False
# 复用 UI Automation，避免每 2 秒重新创建
_UIA = None

# 地址栏在辅助功能树里的名字（中英浏览器）
_ADDRESS_NAMES = (
    "地址和搜索栏",
    "Address and search bar",
    "地址栏",
    "Address bar",
    "在此搜索或输入网址",
    "搜索或输入网址",
    "Search or enter web address",
    "Search with Google or enter address",
)
# UI Automation 属性：Name、Value；查找范围是整棵子树
_UIA_NAME_PROPERTY = 30005
_UIA_VALUE_PROPERTY = 30045
_UIA_TREE_DESCENDANTS = 4


class _LASTINPUTINFO(ctypes.Structure):
    """
    GetLastInputInfo 的输入结构。

    @author Kai
    @date 2026/09/29 15:12
    @description dwTime 是上次鼠标或键盘输入的系统滴答
    """

    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]


@dataclass(frozen=True)
class ActivitySample:
    """
    一次桌面采样。

    @author Kai
    @date 2026/09/29 15:12
    @description rest 为真时 exe/title 为空，调用方不应再读窗口
    """

    # 这段时间记为休息（锁屏或长时间无操作）
    rest: bool
    # 前台进程文件名；休息时为空
    exe: str = ""
    # 仅浏览器和资源管理器临时使用的标题，禁止入库
    title: str = ""
    # 浏览器地址栏原文，只用于取域名，禁止入库
    url: str = ""


def sample_activity() -> ActivitySample:
    """
    采样当前是休息还是某个前台程序。

    @return 休息样本或带进程名的样本；失败时返回空的非休息样本（本段不记账）
    @author Kai
    @date 2026/09/29 15:12
    """
    global _CAPTURE_ERROR_LOGGED
    try:
        if _is_input_desktop_locked() or _idle_seconds() >= IDLE_REST_SECONDS:
            return ActivitySample(rest=True)
        exe, title, url = _read_foreground()
        return ActivitySample(rest=False, exe=exe, title=title, url=url)
    except Exception:
        if not _CAPTURE_ERROR_LOGGED:
            LOG.exception("读取前台窗口失败")
            _CAPTURE_ERROR_LOGGED = True
        return ActivitySample(rest=False)


def _is_input_desktop_locked() -> bool:
    """
    输入桌面打不开时视为锁屏。

    @return 是否锁屏
    @author Kai
    @date 2026/09/29 15:12
    """
    desktop = _user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return True
    _user32.CloseDesktop(desktop)
    return False


def _idle_seconds() -> float:
    """
    距上次鼠标或键盘输入的秒数。

    @return 空闲秒数；接口失败时返回 0，避免误记成休息
    @author Kai
    @date 2026/09/29 15:12
    """
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    now = int(_kernel32.GetTickCount())
    elapsed = (now - int(info.dwTime)) & 0xFFFFFFFF
    return elapsed / 1000.0


def _read_foreground() -> tuple[str, str, str]:
    """
    读取前台进程名。浏览器额外读标题和地址栏，资源管理器只读标题。

    @return (exe, title, url)；没有前台窗口时为空
    @author Kai
    @date 2026/09/29 16:20
    """
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return "", "", ""
    exe = _exe_of_hwnd(hwnd)
    if not exe:
        return "", "", ""
    lower = exe.casefold()
    if lower in BROWSER_NAMES:
        return exe, _title_of_hwnd(hwnd), _read_address(hwnd)
    if needs_window_title(exe):
        return exe, _title_of_hwnd(hwnd), ""
    return exe, "", ""


def _read_address(hwnd: int) -> str:
    """
    读取浏览器地址栏。失败时返回空串，调用方改用标签标题。

    @param hwnd 浏览器窗口句柄
    @return 地址栏文本；读不到则为空
    @author Kai
    @date 2026/09/29 16:20
    """
    global _ADDRESS_ERROR_LOGGED
    try:
        uia = _uia_client()
        if uia is None:
            return ""
        root = uia.ElementFromHandle(int(hwnd))
        if root is None:
            return ""
        condition = _address_condition(uia)
        element = root.FindFirst(_UIA_TREE_DESCENDANTS, condition)
        if element is None:
            return ""
        value = element.GetCurrentPropertyValue(_UIA_VALUE_PROPERTY)
        text = getattr(value, "value", value)
        return str(text or "").strip()
    except Exception:
        if not _ADDRESS_ERROR_LOGGED:
            LOG.exception("读取浏览器地址栏失败")
            _ADDRESS_ERROR_LOGGED = True
        return ""


def _uia_client() -> object | None:
    """
    取得带接口定义的 UI Automation 客户端。

    @return IUIAutomation；不可用时为 None
    @author Kai
    @date 2026/09/29 16:25
    """
    global _UIA
    if _UIA is not None:
        return _UIA
    import comtypes
    import comtypes.client

    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    try:
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
    except ImportError:
        # 开发环境第一次没有生成绑定，从系统类型库生成
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
    # ProgID「CUIAutomation」在这台系统上无效，必须按 CLSID 创建并指定接口
    _UIA = comtypes.CoCreateInstance(
        CUIAutomation._reg_clsid_,
        interface=IUIAutomation,
        clsctx=comtypes.CLSCTX_INPROC_SERVER,
    )
    return _UIA


def _address_condition(uia: object) -> object:
    """
    拼出「名字是地址栏」的查找条件。

    @param uia CUIAutomation
    @return Or 条件
    @author Kai
    @date 2026/09/29 16:20
    """
    condition = None
    for name in _ADDRESS_NAMES:
        one = uia.CreatePropertyCondition(_UIA_NAME_PROPERTY, name)
        if condition is None:
            condition = one
            continue
        condition = uia.CreateOrCondition(condition, one)
    return condition


def _exe_of_hwnd(hwnd: int) -> str:
    """
    取窗口所属进程的文件名。

    @param hwnd 窗口句柄
    @return 如 Cursor.exe；失败时为空串
    @author Kai
    @date 2026/09/29 15:12
    """
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = _kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
    )
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        ok = _kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        )
        if not ok:
            return ""
        return Path(buf.value).name
    finally:
        _kernel32.CloseHandle(handle)


def _title_of_hwnd(hwnd: int) -> str:
    """
    读取窗口标题，供站点匹配后立即丢弃。

    @param hwnd 窗口句柄
    @return 标题文本
    @author Kai
    @date 2026/09/29 15:12
    """
    length = int(_user32.GetWindowTextLengthW(hwnd))
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value
