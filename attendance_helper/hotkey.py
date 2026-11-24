# Copyright (c) iGroup China.
# All rights reserved.
"""
Windows 全局热键（RegisterHotKey）。

@author Kai
@date 2026/08/05 14:55
@description NULL hwnd + dispatcher 消息；必须保持 filter 强引用防 GC
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable, Optional

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QObject, Signal

from .paths import LOG

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_VK_MAP = {
    **{c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{str(i): ord(str(i)) for i in range(10)},
    "SPACE": 0x20,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.RegisterHotKey.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.UINT,
]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL


def parse_hotkey(expr: str) -> tuple[int, int]:
    """
    解析热键字符串为 (modifiers, vk)。

    @param expr 如 Ctrl+Shift+R
    @return (mod, vk)
    @author Kai
    @date 2026/08/05 14:55
    """
    parts = [p.strip() for p in (expr or "").replace("-", "+").split("+") if p.strip()]
    mod = 0
    key = ""
    for p in parts:
        up = p.upper()
        if up in ("CTRL", "CONTROL"):
            mod |= MOD_CONTROL
        elif up == "SHIFT":
            mod |= MOD_SHIFT
        elif up in ("ALT", "MENU"):
            mod |= MOD_ALT
        elif up in ("WIN", "META", "SUPER"):
            mod |= MOD_WIN
        else:
            key = up
    vk = _VK_MAP.get(key)
    if vk is None:
        raise ValueError(f"无法解析热键: {expr}")
    return mod, vk


def _as_msg(message: object) -> Optional[wintypes.MSG]:
    """
    将 Qt native message 指针转为 MSG。

    @param message 原生消息指针
    @return MSG 或 None
    @author Kai
    @date 2026/08/05 14:55
    """
    try:
        if isinstance(message, int):
            addr = message
        else:
            addr = int(ctypes.cast(message, ctypes.c_void_p).value or 0)
        if not addr:
            return None
        return wintypes.MSG.from_address(addr)
    except Exception:  # noqa: BLE001
        try:
            return wintypes.MSG.from_address(int(message))  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return None


class HotkeyFilter(QAbstractNativeEventFilter):
    """
    拦截 WM_HOTKEY（含 windows_dispatcher_MSG）。

    @author Kai
    @date 2026/08/05 14:55
    @description 通过 Signal 抛到 Qt 主线程
    """

    def __init__(self, bridge: "GlobalHotkeys") -> None:
        super().__init__()
        self._bridge = bridge

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        """
        Qt 原生事件过滤。

        @param eventType 事件类型
        @param message MSG 指针
        @return (是否过滤, result) 或 bool（视绑定而定）
        @author Kai
        @date 2026/08/05 14:55
        """
        if isinstance(eventType, QByteArray):
            et = bytes(eventType).decode("utf-8", errors="ignore")
        elif isinstance(eventType, (bytes, bytearray)):
            et = bytes(eventType).decode("utf-8", errors="ignore")
        else:
            et = str(eventType)

        # 热键多为 windows_dispatcher_MSG；窗口消息也可能是 generic
        if et not in ("windows_dispatcher_MSG", "windows_generic_MSG"):
            return False, 0

        msg = _as_msg(message)
        if msg is None or int(msg.message) != WM_HOTKEY:
            return False, 0

        hid = int(msg.wParam)
        self._bridge.hotkey_pressed.emit(hid)
        # 返回 False 让其它过滤器也能看到；热键已处理
        return False, 0


class GlobalHotkeys(QObject):
    """
    全局热键注册器（线程消息队列，hwnd=0）。

    @author Kai
    @date 2026/08/05 14:55
    @description 必须挂到 QApplication 上防止被 GC
    """

    hotkey_pressed = Signal(int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._handlers: dict[int, Callable[[], None]] = {}
        self._registered: list[int] = []
        self._filter = HotkeyFilter(self)
        self.hotkey_pressed.connect(self._on_hotkey)

    @property
    def filter(self) -> HotkeyFilter:
        """原生事件过滤器（需 installNativeEventFilter）。"""
        return self._filter

    def _on_hotkey(self, hotkey_id: int) -> None:
        """
        主线程执行热键回调。

        @param hotkey_id 热键 id
        @author Kai
        @date 2026/08/05 14:55
        """
        cb = self._handlers.get(int(hotkey_id))
        if not cb:
            return
        try:
            cb()
        except Exception:  # noqa: BLE001
            LOG.exception("热键回调失败 id=%s", hotkey_id)

    def register(self, hotkey_id: int, expr: str, callback: Callable[[], None]) -> bool:
        """
        注册全局热键到当前线程消息队列。

        @param hotkey_id 应用内唯一 id（0x0000–0xBFFF）
        @param expr 热键表达式
        @param callback 触发回调（主线程）
        @return 是否成功
        @author Kai
        @date 2026/08/05 14:55
        """
        if sys.platform != "win32":
            LOG.warning("全局热键仅支持 Windows")
            return False
        try:
            mod, vk = parse_hotkey(expr)
        except ValueError as exc:
            LOG.warning("%s", exc)
            return False

        # hwnd=NULL：消息进当前线程队列，由 Qt dispatcher 以 windows_dispatcher_MSG 投递
        hwnd = wintypes.HWND(0)
        user32.UnregisterHotKey(hwnd, int(hotkey_id))
        mods = int(mod) | MOD_NOREPEAT
        ok = bool(user32.RegisterHotKey(hwnd, int(hotkey_id), mods, int(vk)))
        if not ok:
            err1 = int(kernel32.GetLastError())
            ok = bool(
                user32.RegisterHotKey(hwnd, int(hotkey_id), int(mod), int(vk))
            )
            if not ok:
                err2 = int(kernel32.GetLastError())
                LOG.warning(
                    "RegisterHotKey 失败 id=%s expr=%s err=%s/%s（可能被其它程序占用）",
                    hotkey_id,
                    expr,
                    err1,
                    err2,
                )
                return False

        self._handlers[int(hotkey_id)] = callback
        if hotkey_id not in self._registered:
            self._registered.append(int(hotkey_id))
        LOG.info("已注册全局热键 id=%s expr=%s vk=0x%X mod=0x%X", hotkey_id, expr, vk, mod)
        return True

    def unregister_all(self) -> None:
        """注销全部热键。"""
        hwnd = wintypes.HWND(0)
        for hid in list(self._registered):
            user32.UnregisterHotKey(hwnd, int(hid))
        self._registered.clear()
        self._handlers.clear()
