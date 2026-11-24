# Copyright (c) iGroup.
# All rights reserved.
"""
托盘主程序：菜单、悬浮详情、开门、设置。

@author Kai
@date 2026/08/31 17:40
@description 无桌面常驻挂件；左键详情，双击开门，右键菜单也可开门
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMenu,
    QSystemTrayIcon,
)

from ..achievements import ensure_achievements
from ..activity_tracker import get_activity_tracker
from ..attendance import (
    AttendanceSummary,
    apply_leave_hours_to_summary,
    build_menu_secondary_text,
    build_menu_status_text,
    build_tooltip,
    get_attendance_summary,
    live_tick_summary,
    progress_tone,
    write_status_file,
)
from ..cache_store import cache_mark_once, get_leave_hours, set_leave_hours
from ..config import (
    MAX_LEAVE_HOURS,
    S,
    has_attendance_login,
    reload_settings,
    save_config_dict,
)
from ..db import init_db
from ..display_strategy import (
    MODE_ALWAYS,
    MODE_LABELS,
    MODE_NEAR,
    MODE_QUIET,
    apply_display_preset,
    normalize_display_mode,
    should_auto_popup_detail,
)
from ..daily_remind import evaluate_takeout_reminder
from ..door import open_door
from ..holiday import is_workday
from ..fun_copy import (
    build_fun_tooltip,
    fun_situation_line,
)
from ..hotkey import GlobalHotkeys
from ..icons import make_tray_icon, resolve_persona_tone
from ..item_remind import evaluate_item_reminders
from ..items_store import count_open
from ..paths import LOG
from ..playground import claim_growth
from ..remind import (
    clock_in_poll_start,
    next_interval_seconds,
    seconds_until_next_clock_in_poll,
    within_remind_window,
)
from ..remind_logic import evaluate_reminders
from ..runtime_state import (
    get_latest_summary,
    is_celebrating,
    mark_door_opened_today,
    set_latest_summary,
)
from ..tray_pet import TRAY_ICON_MIN_INTERVAL_MS, connect_pet_animation, make_pet_tray_icon
from .activity_dialog import ActivityDialog
from .chat_dialog import ChatDialog
from .detail_popup import TrayDetailPopup
from .diagnostics_dialog import DiagnosticsDialog
from .items_dialog import ItemsDialog
from .reminder_toast import ReminderToast
from .settings_dialog import SettingsDialog
from .setup_wizard import FirstRunWizard
from .stats_dialog import StatsDialog
from ..startup import disable_startup, enable_startup, is_startup_enabled


def ensure_single_instance() -> bool:
    """
    保证只运行一个实例。

    @return True 表示当前进程可继续
    @author Kai
    @date 2026/07/23 15:25
    """
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\AttendanceHelper_SingleInstance")
    ensure_single_instance._handle = handle  # type: ignore[attr-defined]
    return kernel32.GetLastError() != 183


class Checker(QObject):
    """
    后台轮询打卡接口。

    只拉上班卡：拉到后倒计时本地走，次日 7:00 再开始；下班卡不轮询。

    @author Kai
    @date 2026/09/02 16:37
    @description 仅负责拉打卡与提醒判定基准数据
    """

    notify_signal = Signal(str, str)
    tooltip_signal = Signal(str)
    status_signal = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.paused_today = False
        self.paused_date = ""
        self.running = True
        self._wake = threading.Event()
        self._latest: Optional[AttendanceSummary] = None
        self._force_refresh = False

    def start(self) -> None:
        """启动后台检查线程。"""
        threading.Thread(target=self.loop, daemon=True, name="att-loop").start()

    def stop(self) -> None:
        """停止后台循环。"""
        self.running = False
        self._wake.set()

    def trigger_refresh(self) -> None:
        """立即唤醒并强制打一次接口（含手动刷新）。"""
        self._force_refresh = True
        self._wake.set()

    def loop(self) -> None:
        """主循环：未到上班卡时轮询，拉到后等到次日 7:00 再拉。"""
        while self.running:
            now = datetime.now()
            date_str = now.date().isoformat()
            force = self._force_refresh
            self._force_refresh = False

            if self.paused_today and self.paused_date != date_str:
                self.paused_today = False
                self.paused_date = ""

            if not is_workday(now.date()):
                # 非工作日也推一条状态，供详情卡展示
                self.status_signal.emit(
                    AttendanceSummary(ok=True, error="NON_WORKDAY")
                )
                self._sleep(3600)
                continue

            have_clock_in = (
                self._latest is not None
                and self._latest.ok
                and self._latest.has_clock_in
                and self._latest.date == date_str
            )
            if not force and have_clock_in:
                tomorrow = clock_in_poll_start(now) + timedelta(days=1)
                self._sleep(max(60, int((tomorrow - now).total_seconds())))
                continue

            if not force and now < clock_in_poll_start(now):
                self._sleep(seconds_until_next_clock_in_poll(now))
                continue

            summary = get_attendance_summary(now)
            self._latest = summary
            write_status_file(summary)
            self.status_signal.emit(summary)

            if summary.token_expired:
                if cache_mark_once(f"token-expired-notify-{date_str}"):
                    self.notify_signal.emit(
                        "登录已过期",
                        "自动登录未成功，请在设置中核对账号密码",
                    )

            self._sleep(next_interval_seconds(now, summary))

    def _sleep(self, seconds: int) -> None:
        """可被 refresh 唤醒的等待。"""
        self._wake.clear()
        self._wake.wait(timeout=max(1, seconds))


class DoorBridge(QObject):
    """
    开门结果切回主线程，避免在后台线程里操作 Qt。

    @author Kai
    @date 2026/08/31 17:50
    @description worker 只 emit，气泡在槽函数里弹
    """

    finished = Signal(bool, str)


def request_open_door(bridge: DoorBridge) -> None:
    """
    直接开门，无确认框；结果用托盘气泡提示。

    冷却由 open_door 内部处理。双击托盘或菜单「一键开门」走这里。

    @param bridge 主线程信号桥
    @author Kai
    @date 2026/09/01 10:55
    """

    def worker() -> None:
        ok, msg = open_door()
        if ok:
            mark_door_opened_today()
        bridge.finished.emit(ok, msg)

    threading.Thread(target=worker, daemon=True, name="open-door").start()


def build_tray_app() -> QApplication:
    """
    组装托盘菜单 + 悬浮详情 + 设置 + AI 对话。

    @return QApplication
    @author Kai
    @date 2026/08/05 16:12
    """
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # 后台换票遇到未登记设备时，滑块和验证码输入要回到这个界面线程
    from .device_verify_dialog import install_device_verify_invoker

    install_device_verify_invoker()
    app.setApplicationName("AttendanceHelper")

    # SQLite / 成就预置 / 使用时长
    init_db()
    ensure_achievements()
    usage = get_activity_tracker()

    app_icon = make_tray_icon()
    app.setWindowIcon(app_icon)

    tray = QSystemTrayIcon(app_icon, app)
    tray.setToolTip(f"{S.company_name} 考勤助手\n左键详情 · 双击开门 · 右键菜单")

    detail = TrayDetailPopup()

    menu = QMenu()
    act_refresh = QAction("刷新", menu)
    act_status = QAction("今日打卡：加载中…", menu)
    act_status.setEnabled(False)
    act_secondary = QAction("可走时间：--", menu)
    act_secondary.setEnabled(False)
    act_secondary.setVisible(False)
    act_chat = QAction("AI 对话…", menu)
    act_items = QAction("今日事项…", menu)
    act_usage = QAction("今日使用：统计中…", menu)
    act_usage.setEnabled(False)
    act_usage_open = QAction("今日使用详情…", menu)
    act_usage_pause = QAction("暂停今日使用统计", menu)
    act_open = QAction("一键开门", menu)
    act_leave = QAction("请假时长…", menu)
    act_week = QAction("本周统计", menu)
    act_month = QAction("本月统计", menu)
    act_diag = QAction("诊断…", menu)
    act_settings = QAction("设置…", menu)
    act_startup = QAction("一键开机自启", menu)
    act_pause = QAction("暂停今日提醒", menu)
    act_exit = QAction("退出", menu)

    # 显示模式子菜单（三档预设，互斥勾选）
    menu_display = QMenu("显示模式", menu)
    act_mode_quiet = QAction(MODE_LABELS[MODE_QUIET], menu_display)
    act_mode_near = QAction(MODE_LABELS[MODE_NEAR], menu_display)
    act_mode_always = QAction(MODE_LABELS[MODE_ALWAYS], menu_display)
    for act in (act_mode_quiet, act_mode_near, act_mode_always):
        act.setCheckable(True)
    mode_group = QActionGroup(menu_display)
    mode_group.setExclusive(True)
    mode_group.addAction(act_mode_quiet)
    mode_group.addAction(act_mode_near)
    mode_group.addAction(act_mode_always)
    menu_display.addAction(act_mode_quiet)
    menu_display.addAction(act_mode_near)
    menu_display.addAction(act_mode_always)

    def sync_display_mode_actions() -> None:
        """根据当前配置勾选显示模式菜单。"""
        mode = normalize_display_mode(S.display_mode)
        act_mode_quiet.setChecked(mode == MODE_QUIET)
        act_mode_near.setChecked(mode == MODE_NEAR)
        act_mode_always.setChecked(mode == MODE_ALWAYS)

    def sync_startup_action() -> None:
        """根据当前自启状态刷新菜单文案。"""
        if is_startup_enabled():
            act_startup.setText("取消开机自启")
        else:
            act_startup.setText("一键开机自启")

    def sync_usage_actions() -> None:
        """刷新使用时长摘要和暂停文案。"""
        act_usage.setText(usage.menu_text())
        if usage.is_paused():
            act_usage_pause.setText("恢复使用统计")
        else:
            act_usage_pause.setText("暂停今日使用统计")

    sync_startup_action()
    sync_display_mode_actions()
    sync_usage_actions()

    menu.addAction(act_refresh)
    menu.addSeparator()
    menu.addAction(act_status)
    menu.addAction(act_secondary)
    menu.addSeparator()
    menu.addAction(act_chat)
    menu.addAction(act_items)
    menu.addAction(act_usage)
    menu.addAction(act_usage_open)
    menu.addAction(act_usage_pause)
    menu.addSeparator()
    menu.addAction(act_open)
    menu.addAction(act_leave)
    menu.addSeparator()
    menu.addAction(act_week)
    menu.addAction(act_month)
    menu.addSeparator()
    menu.addMenu(menu_display)
    menu.addAction(act_diag)
    menu.addAction(act_settings)
    menu.addAction(act_startup)
    menu.addAction(act_pause)
    menu.addSeparator()
    menu.addAction(act_exit)

    tray.setVisible(True)
    tray.show()
    # 用系统托盘原生右键菜单，避免手动 popup 导致菜单项要点两下
    tray.setContextMenu(menu)
    menu.aboutToShow.connect(
        lambda: (
            sync_startup_action(),
            sync_display_mode_actions(),
            sync_usage_actions(),
            detail.dismiss(),
        )
    )

    checker = Checker()
    # 接口基准摘要；倒计时基于它本地秒刷
    live_state: dict[str, object] = {
        "base": None,
        "api_at": None,
        "ignore_tray_until": 0.0,
    }

    def do_refresh() -> None:
        """立即拉取打卡。"""
        LOG.info("执行打卡刷新")
        checker.trigger_refresh()

    toast_refs: list[ReminderToast] = []

    def show_detail() -> None:
        """贴着托盘图标弹出详情，不跟鼠标走。"""
        detail.show_at_tray(tray.geometry())

    def show_app_toast(title: str, msg: str, *, badge: str = "") -> None:
        """
        应用内提醒卡片，不走系统托盘气泡。

        @param title 标题
        @param msg 正文
        @param badge 右上角类型角标
        @author Kai
        @date 2026/08/31 17:45
        """
        toast = ReminderToast(title, msg, badge=badge)
        toast.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        toast_refs.append(toast)

        def _drop(*_args: object) -> None:
            if toast in toast_refs:
                toast_refs.remove(toast)

        toast.destroyed.connect(_drop)
        toast.show()
        toast.raise_()

    def on_notify(title: str, msg: str) -> None:
        """
        事项/外卖走应用内卡片；其它状态提示仍用托盘气泡。

        @param title 标题
        @param msg 正文
        @author Kai
        @date 2026/08/31 17:45
        """
        if title in ("事项提醒", "外卖提醒"):
            show_app_toast(title, msg, badge=title)
            return
        tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 10000)

    def apply_live_ui(summary: AttendanceSummary, *, from_api: bool) -> None:
        """
        刷新托盘图标 / 菜单 / 详情（不访问接口）。

        @param summary 当前展示摘要
        @param from_api 是否刚完成接口拉取
        @author Kai
        @date 2026/07/23 16:35
        """
        if summary.error == "NON_WORKDAY":
            detail.show_non_workday(from_api=from_api)
            act_status.setText("今日：非工作日")
            act_secondary.setVisible(False)
            tray.setToolTip(f"{S.company_name} - 非工作日 / 节假日")
            tray.setIcon(make_tray_icon(0.0, "normal"))
            return

        act_status.setText(build_menu_status_text(summary))
        secondary = build_menu_secondary_text(summary)
        if secondary:
            act_secondary.setText(secondary)
            act_secondary.setVisible(True)
        else:
            act_secondary.setVisible(False)
        leave_label = (
            f"请假时长（{summary.leave_hours:g}h）…"
            if summary.leave_hours > 0
            else "请假时长…"
        )
        act_leave.setText(leave_label)
        detail.update_summary(
            summary, from_api=from_api, paused=checker.paused_today
        )
        progress, tone = progress_tone(summary)
        if checker.paused_today and summary.error != "NON_WORKDAY":
            tone = "paused"
        open_n = count_open()
        overtime = bool(
            summary.target_reached
            and summary.ok
            and summary.has_clock_in
            and summary.worked_seconds - summary.required_seconds
            >= max(0, int(S.overtime_remind_minutes)) * 60
        )
        persona = resolve_persona_tone(
            tone,
            open_items=open_n,
            celebrating=is_celebrating(),
            overtime=overtime,
        )
        icon = make_pet_tray_icon(summary, fallback_tone=persona)
        tray.setIcon(icon)
        app.setWindowIcon(icon)
        tip = build_fun_tooltip(summary)
        fun_line = fun_situation_line(summary)
        tray.setToolTip(
            f"{tip}\n未完成事项 {open_n}"
            + (f"\n{fun_line}" if fun_line and fun_line not in tip else "")
            + "\n（左键详情 · 双击开门）"
        )

    def maybe_remind_live(summary: AttendanceSummary) -> None:
        """
        基于本地倒计时触发分级提醒节点。

        @param summary 当前考勤摘要
        @author Kai
        @date 2026/08/31 17:45
        """
        if checker.paused_today or not summary.ok or not summary.has_clock_in:
            return
        if summary.token_expired:
            return
        now = datetime.now()
        if not within_remind_window(now):
            return
        date_str = now.date().isoformat()
        captured: list[tuple[str, str]] = []

        def capture(title: str, msg: str) -> None:
            captured.append((title, msg))

        fired = evaluate_reminders(summary, date_str, capture)
        if not fired:
            return
        need_popup = False
        if should_auto_popup_detail():
            for item in fired:
                if item == "overtime" or item == 0:
                    need_popup = True
                elif isinstance(item, int) and item <= 20:
                    need_popup = True
        if need_popup:
            # 详情卡本身就是提醒，不再叠系统气泡
            QTimer.singleShot(0, show_detail)
            return
        for title, msg in captured:
            show_app_toast(title, msg, badge="下班提醒")

    def on_status(summary: AttendanceSummary) -> None:
        """接口拉取完成：更新基准，并立刻刷新 UI。"""
        live_state["base"] = summary
        live_state["api_at"] = datetime.now()
        set_latest_summary(summary)
        live = live_tick_summary(summary)
        apply_live_ui(live, from_api=True)
        maybe_remind_live(live)

    def on_live_tick() -> None:
        """每秒本地重算倒计时（不调接口）。"""
        base = live_state.get("base")
        if not isinstance(base, AttendanceSummary):
            return
        if base.error == "NON_WORKDAY":
            return
        live = live_tick_summary(base)
        set_latest_summary(live)
        apply_live_ui(live, from_api=False)
        maybe_remind_live(live)

    def on_item_remind_tick() -> None:
        """
        低频扫描事项提醒与日常外卖提醒（不受「暂停今日下班提醒」影响）。

        @author Kai
        @date 2026/08/06 10:58
        """
        try:
            evaluate_item_reminders(on_notify)
        except Exception:
            LOG.exception("事项提醒扫描失败")
        try:
            evaluate_takeout_reminder(on_notify)
        except Exception:
            LOG.exception("外卖提醒扫描失败")

    # 必须挂到 QApplication 上：build_tray_app 返回后局部 QTimer 会被 GC，到点不再扫描
    live_timer = QTimer(app)
    live_timer.setInterval(1000)
    live_timer.timeout.connect(on_live_tick)
    live_timer.start()

    item_timer = QTimer(app)
    item_timer.setInterval(15_000)
    item_timer.timeout.connect(on_item_remind_tick)
    item_timer.start()
    # 启动后尽快扫一次，便于补弹当天已过期未提醒的事项
    QTimer.singleShot(2500, on_item_remind_tick)


    def on_pet_frame_tick() -> None:
        """
        Sprite 宠物动画刷新托盘图标（节流，避免任务栏闪得过快）。

        @author Kai
        @date 2026/08/05 17:33
        """
        now = time.monotonic()
        last_at = float(live_state.get("pet_icon_at") or 0.0)
        if (now - last_at) * 1000.0 < TRAY_ICON_MIN_INTERVAL_MS:
            return
        live_state["pet_icon_at"] = now
        summary = get_latest_summary()
        if not isinstance(summary, AttendanceSummary):
            return
        icon = make_pet_tray_icon(summary, fallback_tone="normal")
        tray.setIcon(icon)
        app.setWindowIcon(icon)

    connect_pet_animation(on_pet_frame_tick, parent=app)

    checker.notify_signal.connect(on_notify)
    checker.status_signal.connect(on_status)

    act_refresh.triggered.connect(do_refresh)

    door_bridge = DoorBridge(app)

    def on_door_finished(ok: bool, msg: str) -> None:
        """
        主线程提示开门结果（短气泡，不是确认框）。

        @param ok 是否成功
        @param msg 接口或冷却提示
        @author Kai
        @date 2026/08/31 17:50
        """
        tray.showMessage(
            "开门成功" if ok else "开门失败",
            msg,
            QSystemTrayIcon.MessageIcon.Information
            if ok
            else QSystemTrayIcon.MessageIcon.Warning,
            2500,
        )

    door_bridge.finished.connect(
        on_door_finished,
        Qt.ConnectionType.QueuedConnection,
    )
    act_open.triggered.connect(lambda: request_open_door(door_bridge))

    def open_chat() -> None:
        """
        打开 AI 对话（创建事项 / 查考勤等）。

        @author Kai
        @date 2026/08/05 16:12
        """
        if not S.ai_enable_chat:
            on_notify("AI 对话", "已在设置中关闭")
            return
        dlg = ChatDialog()
        dlg.exec()

    def open_items() -> None:
        """打开事项列表。"""
        dlg = ItemsDialog()
        dlg.exec()

    def open_usage() -> None:
        """打开使用时长，关掉后刷新菜单摘要。"""
        dlg = ActivityDialog(usage)
        dlg.exec()
        sync_usage_actions()

    act_chat.triggered.connect(open_chat)
    act_items.triggered.connect(open_items)
    act_usage_open.triggered.connect(open_usage)

    # 全局热键：挂到 app 防 GC；hwnd=NULL 走线程消息队列
    hotkeys = GlobalHotkeys(parent=app)
    app._attendance_hotkeys = hotkeys  # type: ignore[attr-defined]
    app.installNativeEventFilter(hotkeys.filter)
    ok_chat = hotkeys.register(
        1, S.hotkey_chat, lambda: QTimer.singleShot(0, open_chat)
    )
    if not ok_chat:
        LOG.warning(
            "AI 对话热键注册失败 chat=%s（可能被其它程序占用，可在设置改键）",
            S.hotkey_chat,
        )

    def on_leave() -> None:
        """录入今日请假时长。"""
        current = get_leave_hours()
        hours, ok = QInputDialog.getDouble(
            None,
            "请假时长",
            f"今日请假小时数（0 ~ {MAX_LEAVE_HOURS:g}，"
            f"从 {S.target_hours:g}h 应出勤中扣除）",
            current,
            0.0,
            float(MAX_LEAVE_HOURS),
            2,
        )
        if not ok:
            return
        set_leave_hours(hours)
        # 立刻按新请假重算可走时间，不必等下一次接口
        base = live_state.get("base")
        if isinstance(base, AttendanceSummary) and base.error != "NON_WORKDAY":
            patched = apply_leave_hours_to_summary(base, hours)
            live_state["base"] = patched
            set_latest_summary(patched)
            apply_live_ui(patched, from_api=False)
        on_notify(
            "请假已更新",
            f"今日请假 {hours:g} 小时，应出勤 {S.target_hours - hours:g} 小时",
        )
        do_refresh()

    act_leave.triggered.connect(on_leave)

    def on_week_stats() -> None:
        """按日查接口，日历展示本周打卡。"""
        dlg = StatsDialog(kind="week")
        dlg.exec()

    def on_month_stats() -> None:
        """按日查接口，日历展示本月打卡。"""
        dlg = StatsDialog(kind="month")
        dlg.exec()

    act_week.triggered.connect(on_week_stats)
    act_month.triggered.connect(on_month_stats)

    def on_diagnostics() -> None:
        """打开一键诊断。"""
        api_at = live_state.get("api_at")
        last = (
            api_at.strftime("%H:%M:%S")
            if isinstance(api_at, datetime)
            else "--"
        )
        dlg = DiagnosticsDialog(last_update=last)
        dlg.exec()

    act_diag.triggered.connect(on_diagnostics)

    def on_settings() -> None:
        """打开设置弹窗；保存后刷新配置勾选与热键。"""

        def after_saved() -> None:
            sync_display_mode_actions()
            hotkeys.register(
                1, S.hotkey_chat, lambda: QTimer.singleShot(0, open_chat)
            )
            do_refresh()
            base = live_state.get("base")
            if isinstance(base, AttendanceSummary):
                apply_live_ui(live_tick_summary(base), from_api=False)

        dlg = SettingsDialog(on_saved=after_saved)
        dlg.exec()

    act_settings.triggered.connect(on_settings)

    def on_display_mode(mode: str) -> None:
        """
        切换显示模式预设：写回细项并立刻刷新 UI。

        @param mode quiet / near / always
        @author Kai
        @date 2026/07/24 16:55
        """
        fields = apply_display_preset(mode)
        save_config_dict(fields)
        reload_settings()
        sync_display_mode_actions()
        from ..display_strategy import MODE_HINTS

        hint = MODE_HINTS.get(mode, "")
        on_notify(
            "显示模式",
            f"{MODE_LABELS.get(mode, mode)}" + (f"：{hint}" if hint else ""),
        )
        base = live_state.get("base")
        if isinstance(base, AttendanceSummary):
            apply_live_ui(live_tick_summary(base), from_api=False)

    act_mode_quiet.triggered.connect(lambda: on_display_mode(MODE_QUIET))
    act_mode_near.triggered.connect(lambda: on_display_mode(MODE_NEAR))
    act_mode_always.triggered.connect(lambda: on_display_mode(MODE_ALWAYS))

    def on_startup() -> None:
        """一键开关开机自启。"""
        if is_startup_enabled():
            ok, msg = disable_startup()
            on_notify("开机自启", msg if ok else f"取消失败：{msg}")
        else:
            ok, msg = enable_startup()
            on_notify(
                "开机自启",
                "已设置，下次开机自动启动" if ok else f"设置失败：{msg}",
            )
        sync_startup_action()

    act_startup.triggered.connect(on_startup)

    def on_pause() -> None:
        checker.paused_today = not checker.paused_today
        if checker.paused_today:
            checker.paused_date = date.today().isoformat()
            act_pause.setText("恢复今日提醒")
            on_notify("提醒已暂停", "今日不再推送下班提醒")
            # 立刻刷新徽标为「已暂停」
            base = live_state.get("base")
            if isinstance(base, AttendanceSummary):
                apply_live_ui(live_tick_summary(base), from_api=False)
        else:
            checker.paused_date = ""
            act_pause.setText("暂停今日提醒")
            on_notify("提醒已恢复", "将继续检查下班提醒")
            base = live_state.get("base")
            if isinstance(base, AttendanceSummary):
                apply_live_ui(live_tick_summary(base), from_api=False)

    act_pause.triggered.connect(on_pause)

    def on_usage_pause() -> None:
        """暂停或恢复今天的前台软件统计。"""
        usage.set_paused(not usage.is_paused())
        sync_usage_actions()
        if usage.is_paused():
            on_notify("使用统计已暂停", "今天不再记录前台软件")
        else:
            on_notify("使用统计已恢复", "继续记录前台软件")

    act_usage_pause.triggered.connect(on_usage_pause)

    def on_single_click() -> None:
        """过了双击时限仍未第二次点击：切换详情卡。"""
        if detail.isVisible():
            detail.dismiss()
        else:
            show_detail()

    # 单击延迟到系统双击时限之后，才能区分「看详情」和「开门」
    click_timer = QTimer(app)
    click_timer.setSingleShot(True)
    click_timer.setInterval(max(280, int(QApplication.doubleClickInterval())))
    click_timer.timeout.connect(on_single_click)

    def suppress_tray_click(ms: int = 500) -> None:
        """
        吞掉菜单关掉后穿透到托盘的那一下，避免误拉开详情。

        @param ms 忽略托盘激活的毫秒数
        @author Kai
        @date 2026/09/01 10:55
        """
        click_timer.stop()
        live_state["ignore_tray_until"] = time.time() + ms / 1000.0

    menu.aboutToHide.connect(lambda: suppress_tray_click(500))

    def on_tray_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if time.time() < float(live_state.get("ignore_tray_until") or 0):
            return
        # 右键由 setContextMenu 处理，这里不再手动 popup（否则会抢第一次点击）
        if reason == QSystemTrayIcon.ActivationReason.Context:
            click_timer.stop()
            return
        # 双击开门：取消待弹出的详情
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            click_timer.stop()
            if detail.isVisible():
                detail.dismiss()
            request_open_door(door_bridge)
            return
        # 左键：等过双击间隔再出详情
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            click_timer.start()

    tray.activated.connect(on_tray_activated)

    def on_exit() -> None:
        usage.flush()
        checker.stop()
        hotkeys.unregister_all()
        detail.dismiss()
        app.quit()

    act_exit.triggered.connect(on_exit)

    def open_first_run() -> None:
        """未配置时弹出一键向导。"""
        wizard = FirstRunWizard()
        wizard.exec()
        sync_startup_action()
        do_refresh()

    if not S.attendance_token and not has_attendance_login():
        QTimer.singleShot(500, open_first_run)
    elif not is_startup_enabled():
        # 已有配置但未自启：不强弹，仅在首次气泡里提示
        pass

    QTimer.singleShot(
        800,
        lambda: tray.showMessage(
            f"{S.company_name} 考勤助手",
            f"左键详情 · 双击开门 · AI 对话 {S.hotkey_chat}",
            QSystemTrayIcon.MessageIcon.Information,
            7000,
        ),
    )

    checker.start()
    QTimer.singleShot(800, checker.trigger_refresh)
    # 复用使用统计定时器，每分钟自然结算一次成长，不依赖打开卡片。
    usage_growth_at = 0.0

    def on_usage_tick() -> None:
        """
        继续原有采样，并低频结算已归类时长对应的成长。

        @author Kai
        @date 2026/10/15 15:31
        """
        nonlocal usage_growth_at
        usage.tick()
        now = time.monotonic()
        if now - usage_growth_at < 60:
            return
        usage_growth_at = now
        if not (S.fun_enable and S.fun_usage_link and S.fun_card_mode != "off"):
            return
        try:
            claim_growth()
        except ValueError:
            # 没有新增成长或今日已满，不需要额外提示。
            pass
        except Exception:
            LOG.exception("宠物自然成长同步失败")

    usage_timer = QTimer(app)
    usage_timer.setInterval(2000)
    usage_timer.timeout.connect(on_usage_tick)
    usage_timer.start()
    app._usage_timer = usage_timer  # type: ignore[attr-defined]
    return app
