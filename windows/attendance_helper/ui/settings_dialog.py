# Copyright (c) iGroup.
# All rights reserved.
"""
设置弹窗：编辑 .env 与 config.json。

@author Kai
@date 2026/09/01 10:12
@description 凭据 / 业务 / AI / 趣味 / 接口 分页
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..ai_client import test_connection
from .. import playground
from ..config import (
    DEFAULT_DOOR_DEVICE_ID,
    DEFAULT_DOOR_SERIAL,
    DEFAULT_FAR_DISPLAY,
    DEFAULT_HOTKEY_CHAT,
    DEFAULT_TAKEOUT_HOUR,
    DEFAULT_TAKEOUT_MINUTE,
    DEFAULT_TAKEOUT_TEXT,
    load_config_dict,
    normalize_hourly_rate,
    read_env_map,
    reload_settings,
    save_config_dict,
    save_env_map,
)
from ..fun_copy import PERSONA_LABELS
from ..tray_pet import MOOD_TYPE, PET_LABELS, paint_tray_pet
from ..display_strategy import (
    DISPLAY_MODES,
    MODE_HINTS,
    MODE_LABELS,
    MODE_NEAR,
    PRESET_FIELDS,
    FAR_CLOCK_IN,
    FAR_FULL,
    FAR_HIDDEN,
    FAR_TODAY_NORMAL,
    normalize_display_mode,
    normalize_far_display,
)
from ..paths import CONFIG_PATH, ENV_PATH


# 远离下班时显示
_FAR_OPTIONS: list[tuple[str, str]] = [
    (FAR_HIDDEN, "隐藏倒计时"),
    (FAR_TODAY_NORMAL, "仅显示今日正常"),
    (FAR_CLOCK_IN, "显示上班时间"),
    (FAR_FULL, "显示完整信息"),
]


class SettingsDialog(QDialog):
    """
    设置对话框。

    @author Kai
    @date 2026/07/23 15:25
    @description 保存后写盘并 reload，可选回调通知托盘刷新
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_saved: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        创建设置窗口，并将低频趣味配置放入可滚动的分页。

        @param parent 父窗口
        @param on_saved 保存并重新加载配置后的回调
        @author Kai
        @date 2026/10/15 16:16
        """
        super().__init__(parent)
        self._on_saved = on_saved
        self.setWindowTitle("考勤助手 · 设置")
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        tip = QLabel(
            f"凭据写入 {ENV_PATH.name}；业务写入 {CONFIG_PATH.name}。"
            "保存后立即生效。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #666; margin-bottom: 6px;")

        tabs = QTabWidget()
        tabs.addTab(self._build_credentials_tab(), "凭据 (.env)")
        tabs.addTab(self._build_business_tab(), "业务 (config)")
        tabs.addTab(self._build_ai_tab(), "AI")
        # 趣味选项按需滚动，不把整个设置窗口撑出屏幕。
        fun_scroll = QScrollArea()
        fun_scroll.setWidgetResizable(True)
        fun_scroll.setFrameShape(QFrame.Shape.NoFrame)
        fun_scroll.setWidget(self._build_fun_tab())
        tabs.addTab(fun_scroll, "趣味")
        tabs.addTab(self._build_api_tab(), "接口 (config)")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tip)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self._load_values()

    def _line(self, password: bool = False) -> QLineEdit:
        """创建行编辑框。"""
        edit = QLineEdit()
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setClearButtonEnabled(True)
        return edit

    def _build_credentials_tab(self) -> QWidget:
        """凭据分页。"""
        w = QWidget()
        form = QFormLayout(w)
        # 看板独立访问凭据，保存至业务配置供看板服务读取。
        # OLED 保护开关由看板读取，切换为无固定文字的动态场景。
        self.ck_hub_oled = QCheckBox("开启看板防烧屏模式")
        self.ck_hub_oled.setToolTip("动态 Token 用量屏保；重要事件切回监控。网页无法真正关闭手机屏幕，请使用手机自动锁屏。")
        form.addRow(self.ck_hub_oled)
        # 不用的 AI 可以关掉，看板不再查询它的额度和任务。
        # @author Kai @date 2026/11/20 09:40
        self.ck_hub_codex = QCheckBox("监听 Codex")
        self.ck_hub_cursor = QCheckBox("监听 Cursor")
        self.ck_hub_codex.setToolTip("关闭后不再读取 Codex 额度和会话。")
        self.ck_hub_cursor.setToolTip("关闭后不再读取 Cursor 额度和会话。")
        provider_row = QWidget()
        provider_layout = QHBoxLayout(provider_row)
        provider_layout.setContentsMargins(0, 0, 0, 0)
        provider_layout.addWidget(self.ck_hub_codex)
        provider_layout.addWidget(self.ck_hub_cursor)
        provider_layout.addStretch(1)
        form.addRow("看板监听", provider_row)
        self.ed_hub_token = self._line(password=True)
        self.ed_hub_token.setPlaceholderText("留空沿用看板自动生成的令牌")
        form.addRow("看板访问令牌", self.ed_hub_token)
        hub_hint = QLabel("配置后看板立即使用此令牌；留空恢复看板默认令牌。手机端需重新连接。")
        hub_hint.setWordWrap(True)
        form.addRow(hub_hint)
        self.ed_username = self._line()
        self.ed_username.setPlaceholderText("海康登录手机号")
        self.ed_password = self._line(password=True)
        self.ed_password.setPlaceholderText("Token 失效时自动登录")
        self.ed_token = self._line(password=True)
        self.ed_token.setPlaceholderText("可留空，有账号密码时自动获取")
        # 同事说的「开门 Device ID」= 门禁序列号 L40858918
        self.ed_door_serial_cred = self._line()
        form.addRow("登录账号", self.ed_username)
        form.addRow("登录密码", self.ed_password)
        form.addRow("ATTENDANCE_TOKEN", self.ed_token)
        form.addRow("开门 Device ID", self.ed_door_serial_cred)
        hint = QLabel(
            "填写账号密码后，Token 缺失或失效会按网页登录自动换票。"
            "也可以继续手填 Token。开门 Device ID 默认 L40858918，一般不用改。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        form.addRow(hint)
        return w

    def _build_business_tab(self) -> QWidget:
        """业务分页。"""
        w = QWidget()
        form = QFormLayout(w)
        self.ed_company = self._line()
        self.sp_target = QDoubleSpinBox()
        self.sp_target.setRange(1.0, 16.0)
        self.sp_target.setSingleStep(0.5)
        self.sp_target.setSuffix(" 小时")
        self.sp_near = QSpinBox()
        # @author Kai @date 2026/10/23 15:46：取消两小时业务上限，仅保留 Qt 整数输入范围。
        self.sp_near.setRange(1, 2_147_483_647)
        self.sp_near.setSuffix(" 分钟")
        self.sp_near.setToolTip(
            "剩余工时 ≤ 该值时显示倒计时并标橙；始终显示模式不受此限制"
        )
        self.ed_remind_nodes = self._line()
        self.ed_remind_nodes.setPlaceholderText("60,30,20,5,0")
        self.sp_overtime = QSpinBox()
        self.sp_overtime.setRange(0, 240)
        self.sp_overtime.setSuffix(" 分钟")
        self.sp_cooldown = QSpinBox()
        self.sp_cooldown.setRange(0, 120)
        self.sp_cooldown.setSuffix(" 秒")
        self.sp_low = QSpinBox()
        self.sp_low.setRange(60, 7200)
        self.sp_low.setSuffix(" 秒")
        self.sp_low.setToolTip("尚未拉到上班卡时的轮询间隔；拉到后倒计时本地走，不再打接口")
        self.sp_high = QSpinBox()
        self.sp_high.setRange(30, 3600)
        self.sp_high.setSuffix(" 秒")
        self.sp_high_start = QSpinBox()
        self.sp_high_start.setRange(0, 23)
        self.sp_high_start.setSuffix(" 时")
        self.sp_poll_h = QSpinBox()
        self.sp_poll_h.setRange(0, 23)
        self.sp_poll_m = QSpinBox()
        self.sp_poll_m.setRange(0, 59)
        poll_row = QHBoxLayout()
        poll_row.addWidget(self.sp_poll_h)
        poll_row.addWidget(QLabel(":"))
        poll_row.addWidget(self.sp_poll_m)
        poll_row.addStretch(1)
        self.sp_stop_h = QSpinBox()
        self.sp_stop_h.setRange(0, 23)
        self.sp_stop_m = QSpinBox()
        self.sp_stop_m.setRange(0, 59)
        stop_row = QHBoxLayout()
        stop_row.addWidget(self.sp_stop_h)
        stop_row.addWidget(QLabel(":"))
        stop_row.addWidget(self.sp_stop_m)
        stop_row.addStretch(1)
        self.sp_holiday = QSpinBox()
        self.sp_holiday.setRange(1, 72)
        self.sp_holiday.setSuffix(" 小时")

        form.addRow("公司名称", self.ed_company)
        form.addRow("目标工时", self.sp_target)
        form.addRow("临近阈值（≤）", self.sp_near)
        form.addRow("提醒节点(分钟)", self.ed_remind_nodes)
        form.addRow("加班提醒阈值", self.sp_overtime)

        # ---- 显示策略：三档模式决定倒计时何时露出，远离样式可单独微调 ----
        self.cb_display_mode = QComboBox()
        for mode in DISPLAY_MODES:
            self.cb_display_mode.addItem(MODE_LABELS[mode], mode)
        self.cb_far = QComboBox()
        for value, label in _FAR_OPTIONS:
            self.cb_far.addItem(label, value)
        self.lbl_mode_hint = QLabel("")
        self.lbl_mode_hint.setWordWrap(True)
        self.lbl_mode_hint.setStyleSheet("color:#666;")
        self.cb_display_mode.currentIndexChanged.connect(self._on_display_mode_changed)

        form.addRow(QLabel("—— 显示策略 ——"))
        form.addRow("显示模式", self.cb_display_mode)
        form.addRow("远离下班时显示", self.cb_far)
        form.addRow("", self.lbl_mode_hint)

        form.addRow("开门冷却", self.sp_cooldown)
        form.addRow("上班卡轮询间隔", self.sp_low)
        form.addRow("开始找上班卡", poll_row)
        form.addRow("提醒截止", stop_row)
        form.addRow("节假日缓存", self.sp_holiday)
        hint = QLabel(
            "提醒节点示例：60,30,20,5,0（到点=0；加班提醒在到点后再弹一次）。"
            "显示模式也可在托盘右键切换；临近阈值同时控制倒计时露出与橙色标示。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        form.addRow(hint)
        return w

    def _build_ai_tab(self) -> QWidget:
        """
        AI 对话 / Agent 分页。

        @return 分页控件
        @author Kai
        @date 2026/08/05 16:12
        """
        w = QWidget()
        form = QFormLayout(w)
        self.ed_ai_token = self._line(password=True)
        self.ed_ai_base = self._line()
        self.ed_ai_model = self._line()
        self.ck_ai = QCheckBox("启用 AI")
        self.ck_agent = QCheckBox("启用 Agent 工具")
        self.ck_chat = QCheckBox("启用 AI 对话")
        self.ck_web = QCheckBox("启用搜网工具")
        self.ck_read = QCheckBox("启用读文件 / 列目录")
        self.sp_rounds = QSpinBox()
        self.sp_rounds.setRange(1, 10)
        self.sp_ctx = QSpinBox()
        self.sp_ctx.setRange(4, 60)
        self.ed_hotkey_chat = self._line()
        self.ed_search_ep = self._line()
        self.ed_search_key = self._line(password=True)
        self.ed_whitelist = QPlainTextEdit()
        self.ed_whitelist.setPlaceholderText("每行一个目录，例如 D:\\Notes。列目录与读文件不限扩展名。")
        self.ed_whitelist.setMaximumHeight(80)
        self.btn_ai_test = QPushButton("测试 AI 连接")
        self.btn_ai_test.clicked.connect(self._test_ai)

        form.addRow("AI_API_TOKEN", self.ed_ai_token)
        form.addRow("API Base", self.ed_ai_base)
        form.addRow("Model", self.ed_ai_model)
        form.addRow(self.ck_ai)
        form.addRow(self.ck_agent)
        form.addRow(self.ck_chat)
        form.addRow(self.ck_web)
        form.addRow(self.ck_read)
        form.addRow("Agent 最大轮次", self.sp_rounds)
        form.addRow("对话上下文条数", self.sp_ctx)
        form.addRow("AI 对话热键", self.ed_hotkey_chat)
        form.addRow("搜网 endpoint", self.ed_search_ep)
        form.addRow("SEARCH_API_KEY", self.ed_search_key)
        form.addRow("读文件白名单", self.ed_whitelist)
        form.addRow(self.btn_ai_test)
        hint = QLabel(
            "用 AI 对话创建事项、查考勤、搜网或读文件。"
            "思考程度在聊天窗口输入框旁切换，只影响对话，下一轮立即生效。"
            "宠物短句润色的思考程度在「趣味」页单独设置，默认关闭。"
            "搜网与读文件默认关闭，启用后才出现在工具列表。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        form.addRow(hint)
        return w

    def _build_fun_tab(self) -> QWidget:
        """
        趣味：宠物 / 人格。

        @return 分页
        @author Kai
        @date 2026/08/31 17:15
        """
        w = QWidget()
        form = QFormLayout(w)
        self.ck_fun = QCheckBox("启用趣味功能")
        self.ck_pet = QCheckBox("启用托盘宠物")
        self.cb_pet = QComboBox()
        for pid, label in PET_LABELS.items():
            self.cb_pet.addItem(label, pid)
        self.lbl_pet_preview = QLabel()
        self.lbl_pet_preview.setFixedSize(72, 72)
        self.lbl_pet_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cb_pet.currentIndexChanged.connect(self._refresh_pet_preview)
        pet_row = QHBoxLayout()
        pet_row.addWidget(self.cb_pet, 1)
        pet_row.addWidget(self.lbl_pet_preview)
        pet_wrap = QWidget()
        pet_wrap.setLayout(pet_row)
        self.cb_persona = QComboBox()
        for pid, label in PERSONA_LABELS.items():
            self.cb_persona.addItem(label, pid)
        # 左键只展示一种轻互动，玩法及请求偏好集中在此配置。
        self.cb_fun_card = QComboBox()
        self.cb_fun_card.addItem("海龟汤 · 随时来一题", "puzzle")
        self.cb_fun_card.addItem("只看考勤", "off")
        self.ck_fun_usage = QCheckBox("宠物随今日使用时长自然成长")
        self.btn_pet_history = QPushButton("查看宠物足迹")
        self.btn_pet_history.clicked.connect(self._show_pet_history)

        # 木鱼为宠物旁的小按钮，声音独立且默认关闭。
        self.ck_woodfish = QCheckBox("显示在宠物旁")
        self.ck_woodfish_sound = QCheckBox("声音")
        woodfish_row = QHBoxLayout()
        woodfish_row.addWidget(self.ck_woodfish)
        woodfish_row.addWidget(self.ck_woodfish_sound)
        woodfish_row.addStretch()
        woodfish_wrap = QWidget()
        woodfish_wrap.setLayout(woodfish_row)

        # 时薪只用于本地娱乐估算，不从月薪推断，也不发送给模型。
        self.ck_salary = QCheckBox("显示估算金额")
        self.sp_hourly_rate = QDoubleSpinBox()
        self.sp_hourly_rate.setRange(0.0, 1000000.0)
        self.sp_hourly_rate.setDecimals(2)
        self.sp_hourly_rate.setPrefix("¥ ")
        self.sp_hourly_rate.setSuffix(" / 小时")
        self.sp_hourly_rate.setToolTip("手动填写估算时薪；仅保存在本地配置。")
        salary_row = QHBoxLayout()
        salary_row.addWidget(self.ck_salary)
        salary_row.addWidget(self.sp_hourly_rate)
        salary_wrap = QWidget()
        salary_wrap.setLayout(salary_row)
        self.ck_salary_slack = QCheckBox("摸鱼")
        self.ck_salary_rest = QCheckBox("休息")
        self.ck_salary_unknown = QCheckBox("未分类")
        self.ck_salary_unknown.setToolTip("未分类可能包含未识别的工作软件，是否计入由你决定。")
        scope_row = QHBoxLayout()
        for checkbox in (self.ck_salary_slack, self.ck_salary_rest, self.ck_salary_unknown):
            scope_row.addWidget(checkbox)
        scope_row.addStretch()
        scope_wrap = QWidget()
        scope_wrap.setLayout(scope_row)

        self.ck_takeout = QCheckBox("启用工作日外卖提醒")
        self.sp_takeout_h = QSpinBox()
        self.sp_takeout_h.setRange(0, 23)
        self.sp_takeout_h.setSuffix(" 时")
        self.sp_takeout_m = QSpinBox()
        self.sp_takeout_m.setRange(0, 59)
        self.sp_takeout_m.setSuffix(" 分")
        takeout_time = QHBoxLayout()
        takeout_time.addWidget(self.sp_takeout_h)
        takeout_time.addWidget(self.sp_takeout_m)
        takeout_time.addStretch(1)
        takeout_wrap = QWidget()
        takeout_wrap.setLayout(takeout_time)
        self.ed_takeout_text = self._line()
        self.ed_takeout_text.setPlaceholderText(DEFAULT_TAKEOUT_TEXT)

        form.addRow(self.ck_fun)
        form.addRow(self.ck_pet)
        form.addRow("宠物形象", pet_wrap)
        form.addRow("提醒人格", self.cb_persona)
        form.addRow("左键轻互动", self.cb_fun_card)
        form.addRow(self.ck_fun_usage)
        form.addRow(self.btn_pet_history)
        form.addRow("电子木鱼", woodfish_wrap)
        form.addRow("带薪回血", salary_wrap)
        form.addRow("计算范围", scope_wrap)
        form.addRow(self.ck_takeout)
        form.addRow("外卖提醒时刻", takeout_wrap)
        form.addRow("外卖提醒文案", self.ed_takeout_text)
        hint = QLabel(
            "海龟汤揭晓后可直接再来一题，一轮内不会重复；没有做完的题下次接着看。"
            "题库用完后重新洗牌，进度与推理足迹保存在本地。"
            "带薪回血按选中分类时长和手动时薪估算，不代表实际工资到账。"
            "外卖提醒仅工作日触发，每天一次。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        form.addRow(hint)
        self._refresh_pet_preview()
        self.cb_fun_card.currentIndexChanged.connect(self._sync_fun_options)
        self.ck_fun.toggled.connect(self._sync_fun_options)
        self.ck_pet.toggled.connect(self._sync_fun_options)
        self.ck_woodfish.toggled.connect(self._sync_fun_options)
        self.ck_salary.toggled.connect(self._sync_fun_options)
        return w

    def _sync_fun_options(self, *_args: object) -> None:
        """
        按所选轻玩法启用相应配置，避免无效选项干扰。

        @param _args Qt 选项变化参数
        @author Kai
        @date 2026/10/15 15:25
        """
        self.ck_fun_usage.setEnabled(self.ck_fun.isChecked() and self.cb_fun_card.currentData() != "off")
        enabled = self.ck_fun.isChecked()
        self.ck_woodfish.setEnabled(enabled and self.ck_pet.isChecked())
        self.ck_woodfish_sound.setEnabled(enabled and self.ck_pet.isChecked() and self.ck_woodfish.isChecked())
        self.ck_salary.setEnabled(enabled)
        for control in (self.sp_hourly_rate, self.ck_salary_slack, self.ck_salary_rest, self.ck_salary_unknown):
            control.setEnabled(enabled and self.ck_salary.isChecked())

    def _show_pet_history(self) -> None:
        """
        按需显示近期足迹与养成摘要，保留历史存档。

        @author Kai
        @date 2026/10/15 15:25
        """
        state = playground.snapshot()
        growth = state["growth"]
        traits = " · ".join(f"{label} {growth['traits'][key]}" for key, label in playground.TRAIT_LABELS.items())
        lines = [f"海龟汤已揭晓 {state['puzzle_completed']} 题", "",
                 f"Lv.{1 + growth['xp'] // playground.GROWTH_LEVEL_XP} · {traits}",
                 f"零花钱：{state['coins']} 金币", "",
                 "最近的道具：" + ("、".join(state["bag"][-5:]) or "还没出门寻宝"), ""]
        for record in state["puzzle_session"]["history"][-8:]:
            lines.append(f"{record['day']} · {record['title']}")
        for event in state["journal"][-3:]:
            lines.extend((event["day"], event["story"], ""))
        QMessageBox.information(self, "宠物足迹", "\n".join(lines))

    def _refresh_pet_preview(self) -> None:
        """
        刷新设置页宠物预览图。

        @author Kai
        @date 2026/08/05 15:50
        """
        if not hasattr(self, "lbl_pet_preview"):
            return
        from PySide6.QtCore import QRectF

        pid = str(self.cb_pet.currentData() or "shiba")
        size = 72
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        paint_tray_pet(painter, QRectF(0, 0, size, size), pet=pid, mood=MOOD_TYPE)
        painter.end()
        self.lbl_pet_preview.setPixmap(pix)

    def _test_ai(self) -> None:
        """
        使用当前表单参数测试 AI 连通性。

        @author Kai
        @date 2026/08/24 15:14
        """
        # 临时把表单 token 注入环境供本次测试
        import os

        token = self.ed_ai_token.text().strip()
        if token:
            os.environ["AI_API_TOKEN"] = token
        from ..config import S as settings

        settings.ai_base_url = self.ed_ai_base.text().strip() or settings.ai_base_url
        settings.ai_model = self.ed_ai_model.text().strip() or settings.ai_model
        settings.ai_api_token = token or settings.ai_api_token
        settings.ai_enable = True
        ok, msg = test_connection()
        if ok:
            QMessageBox.information(self, "AI 连接成功", msg)
        else:
            QMessageBox.warning(self, "AI 连接失败", msg)

    def _on_display_mode_changed(self) -> None:
        """
        切换显示模式时同步远离样式预设，并刷新说明文案。

        @author Kai
        @date 2026/08/31 17:15
        """
        mode = str(self.cb_display_mode.currentData() or MODE_NEAR)
        self.lbl_mode_hint.setText(MODE_HINTS.get(mode, ""))
        far = str((PRESET_FIELDS.get(mode) or {}).get("far_display") or "")
        if not far:
            return
        idx = self.cb_far.findData(far)
        if idx >= 0:
            self.cb_far.setCurrentIndex(idx)

    def _build_api_tab(self) -> QWidget:
        """接口分页。"""
        w = QWidget()
        form = QFormLayout(w)
        self.ed_att_api = self._line()
        self.ed_att_id = self._line()
        self.ed_att_app = self._line()
        self.ed_door_api = self._line()
        self.ed_door_header_id = self._line()
        self.ed_door_serial = self._line()
        self.ed_door_app = self._line()
        self.ed_door_auth = self._line()
        form.addRow("打卡 API", self.ed_att_api)
        form.addRow("打卡 ID", self.ed_att_id)
        form.addRow("打卡 app_no", self.ed_att_app)
        form.addRow("开门 API", self.ed_door_api)
        form.addRow("开门请求头 deviceid", self.ed_door_header_id)
        form.addRow("门禁序列号", self.ed_door_serial)
        form.addRow("开门 app_no", self.ed_door_app)
        form.addRow("开门 authperm", self.ed_door_auth)
        return w

    def _load_values(self) -> None:
        """从磁盘填充表单。"""
        env = read_env_map()
        # 回填看板独立令牌，避免覆盖考勤和 AI 凭据。
        hub_config = load_config_dict()
        self.ck_hub_oled.setChecked(bool(hub_config.get("desk_hub_oled", False)))
        self.ed_hub_token.setText(str(hub_config.get("desk_hub_token", "")))
        providers = hub_config.get("desk_hub_providers", ["codex", "cursor"])
        if not isinstance(providers, list):
            providers = ["codex", "cursor"]
        self.ck_hub_codex.setChecked("codex" in providers)
        self.ck_hub_cursor.setChecked("cursor" in providers)
        self.ed_username.setText(env.get("ATTENDANCE_USERNAME", ""))
        self.ed_password.setText(env.get("ATTENDANCE_PASSWORD", ""))
        self.ed_token.setText(env.get("ATTENDANCE_TOKEN", ""))

        cfg = load_config_dict()
        att = cfg.get("attendance", {}) or {}
        door = cfg.get("door", {}) or {}
        serial = str(door.get("device_serial") or "").strip() or DEFAULT_DOOR_SERIAL
        self.ed_door_serial_cred.setText(serial)
        self.ed_company.setText(str(cfg.get("company_name", "")))
        self.sp_target.setValue(float(cfg.get("target_hours", 9)))
        self.sp_near.setValue(int(cfg.get("near_minutes", 20)))
        nodes = cfg.get("remind_nodes_minutes", [60, 30, 20, 5, 0])
        self.ed_remind_nodes.setText(",".join(str(int(x)) for x in nodes))
        self.sp_overtime.setValue(int(cfg.get("overtime_remind_minutes", 30)))
        mode = normalize_display_mode(str(cfg.get("display_mode") or MODE_NEAR))
        self.cb_display_mode.blockSignals(True)
        self.cb_far.blockSignals(True)
        idx_m = self.cb_display_mode.findData(mode)
        self.cb_display_mode.setCurrentIndex(idx_m if idx_m >= 0 else 1)
        far = normalize_far_display(
            str(cfg.get("far_display", DEFAULT_FAR_DISPLAY))
        )
        idx_f = self.cb_far.findData(far)
        self.cb_far.setCurrentIndex(idx_f if idx_f >= 0 else 1)
        self.cb_display_mode.blockSignals(False)
        self.cb_far.blockSignals(False)
        self.lbl_mode_hint.setText(MODE_HINTS.get(mode, ""))
        self.sp_cooldown.setValue(int(cfg.get("door_cooldown_seconds", 10)))
        self.sp_low.setValue(int(cfg.get("low_freq_interval_seconds", 300)))
        self.sp_high.setValue(int(cfg.get("high_freq_interval_seconds", 60)))
        self.sp_high_start.setValue(int(cfg.get("high_freq_start_hour", 12)))
        self.sp_poll_h.setValue(int(cfg.get("clock_in_poll_hour", 7)))
        self.sp_poll_m.setValue(int(cfg.get("clock_in_poll_minute", 0)))
        self.sp_stop_h.setValue(int(cfg.get("remind_stop_hour", 20)))
        self.sp_stop_m.setValue(int(cfg.get("remind_stop_minute", 30)))
        self.sp_holiday.setValue(int(cfg.get("holiday_cache_hours", 12)))

        self.ed_att_api.setText(str(att.get("api_base", "")))
        self.ed_att_id.setText(str(att.get("id", "")))
        self.ed_att_app.setText(str(att.get("app_no", "")))
        self.ed_door_api.setText(str(door.get("api", "")))
        self.ed_door_header_id.setText(
            env.get("DOOR_DEVICE_ID", "").strip() or DEFAULT_DOOR_DEVICE_ID
        )
        self.ed_door_serial.setText(serial)
        self.ed_door_app.setText(str(door.get("app_no", "")))
        self.ed_door_auth.setText(str(door.get("authperm", "")))

        # AI
        ai = cfg.get("ai", {}) or {}
        self.ed_ai_token.setText(env.get("AI_API_TOKEN", ""))
        self.ed_ai_base.setText(
            str(
                ai.get("base_url")
                or "https://sh.igroupnet.com.cn:8443/ollama-api/v1/chat/completions"
            )
        )
        self.ed_ai_model.setText(str(ai.get("model") or "qwen36-27b:latest"))
        self.ck_ai.setChecked(bool(ai.get("enable_ai", True)))
        self.ck_agent.setChecked(bool(ai.get("enable_agent", True)))
        self.ck_chat.setChecked(bool(ai.get("enable_chat", True)))
        self.ck_web.setChecked(bool(ai.get("enable_web_search", False)))
        self.ck_read.setChecked(bool(ai.get("enable_read_file", False)))
        self.sp_rounds.setValue(int(ai.get("agent_max_rounds", 5)))
        self.sp_ctx.setValue(int(ai.get("chat_context_messages", 20)))
        self.ed_hotkey_chat.setText(
            str(ai.get("hotkey_chat") or DEFAULT_HOTKEY_CHAT)
        )
        self.ed_search_ep.setText(str(ai.get("search_endpoint") or ""))
        self.ed_search_key.setText(env.get("SEARCH_API_KEY", ""))
        dirs = ai.get("file_whitelist_dirs") or []
        if isinstance(dirs, list):
            self.ed_whitelist.setPlainText("\n".join(str(x) for x in dirs))
        else:
            self.ed_whitelist.setPlainText(str(dirs))

        fun = cfg.get("fun", {}) or {}
        self.ck_fun.setChecked(bool(fun.get("enable", True)))
        self.ck_pet.setChecked(bool(fun.get("pet_enable", True)))
        idx_pet = self.cb_pet.findData(str(fun.get("pet") or "shiba"))
        self.cb_pet.setCurrentIndex(idx_pet if idx_pet >= 0 else 0)
        self._refresh_pet_preview()
        idx_persona = self.cb_persona.findData(str(fun.get("persona") or "secretary"))
        self.cb_persona.setCurrentIndex(idx_persona if idx_persona >= 0 else 0)
        index = self.cb_fun_card.findData("off" if fun.get("card_mode") == "off" else "puzzle")
        self.cb_fun_card.setCurrentIndex(index)
        self.ck_fun_usage.setChecked(bool(fun.get("usage_link", True)))
        self.ck_woodfish.setChecked(bool(fun.get("woodfish_enable", True)))
        self.ck_woodfish_sound.setChecked(bool(fun.get("woodfish_sound", False)))
        self.ck_salary.setChecked(bool(fun.get("salary_enable", False)))
        self.sp_hourly_rate.setValue(normalize_hourly_rate(fun.get("hourly_rate", 0)))
        self.ck_salary_slack.setChecked(bool(fun.get("salary_slack", True)))
        self.ck_salary_rest.setChecked(bool(fun.get("salary_rest", True)))
        self.ck_salary_unknown.setChecked(bool(fun.get("salary_unknown", False)))
        self._sync_fun_options()

        takeout = cfg.get("takeout_remind", {}) or {}
        self.ck_takeout.setChecked(bool(takeout.get("enable", True)))
        self.sp_takeout_h.setValue(int(takeout.get("hour", DEFAULT_TAKEOUT_HOUR)))
        self.sp_takeout_m.setValue(int(takeout.get("minute", DEFAULT_TAKEOUT_MINUTE)))
        self.ed_takeout_text.setText(
            str(takeout.get("text") or DEFAULT_TAKEOUT_TEXT)
        )

    def _save(self) -> None:
        """
        校验凭据及启用中的估算参数，保存后立即生效。

        @author Kai
        @date 2026/10/15 16:16
        """
        salary_enabled = self.ck_fun.isChecked() and self.ck_salary.isChecked()
        if salary_enabled and self.sp_hourly_rate.value() <= 0:
            QMessageBox.warning(self, "请填写时薪", "启用带薪回血前，请填写大于零的估算时薪。")
            return
        if salary_enabled and not any(
            checkbox.isChecked() for checkbox in
            (self.ck_salary_slack, self.ck_salary_rest, self.ck_salary_unknown)
        ):
            QMessageBox.warning(self, "请选择计算范围", "请至少选择摸鱼、休息或未分类中的一项。")
            return
        username = self.ed_username.text().strip()
        password = self.ed_password.text().strip()
        token = self.ed_token.text().strip()
        # 凭据页「开门 Device ID」优先；接口页序列号作兜底
        serial = (
            self.ed_door_serial_cred.text().strip()
            or self.ed_door_serial.text().strip()
            or DEFAULT_DOOR_SERIAL
        )
        header_id = (
            self.ed_door_header_id.text().strip() or DEFAULT_DOOR_DEVICE_ID
        )
        if not token and not (username and password):
            QMessageBox.warning(
                self,
                "配置不完整",
                "请填写登录账号和密码，或手填 ATTENDANCE_TOKEN。",
            )
            return

        # 解析提醒节点
        nodes: list[int] = []
        for part in self.ed_remind_nodes.text().replace("，", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                nodes.append(int(part))
            except ValueError:
                QMessageBox.warning(self, "提醒节点无效", f"无法解析：{part}")
                return
        if not nodes:
            nodes = [60, 30, 20, 5, 0]

        display_mode = str(self.cb_display_mode.currentData() or MODE_NEAR)
        far_display = str(self.cb_far.currentData())

        whitelist = [
            line.strip()
            for line in self.ed_whitelist.toPlainText().splitlines()
            if line.strip()
        ]

        save_env_map(
            {
                "ATTENDANCE_TOKEN": token,
                "ATTENDANCE_USERNAME": username,
                "ATTENDANCE_PASSWORD": password,
                "DOOR_DEVICE_ID": header_id,
                "AI_API_TOKEN": self.ed_ai_token.text().strip(),
                "SEARCH_API_KEY": self.ed_search_key.text().strip(),
            }
        )
        save_config_dict(
            {
                # 看板服务从助手数据目录读取此字段，无需重启。
                "desk_hub_oled": self.ck_hub_oled.isChecked(),
                "desk_hub_token": self.ed_hub_token.text().strip(),
                "desk_hub_providers": [name for name, box in (("codex", self.ck_hub_codex), ("cursor", self.ck_hub_cursor)) if box.isChecked()],
                "company_name": self.ed_company.text().strip() or "iGroup China",
                "target_hours": float(self.sp_target.value()),
                "near_minutes": int(self.sp_near.value()),
                "remind_nodes_minutes": sorted(set(nodes), reverse=True),
                "overtime_remind_minutes": int(self.sp_overtime.value()),
                "display_mode": display_mode,
                "far_display": far_display,
                "door_cooldown_seconds": int(self.sp_cooldown.value()),
                "low_freq_interval_seconds": int(self.sp_low.value()),
                "high_freq_interval_seconds": int(self.sp_high.value()),
                "high_freq_start_hour": int(self.sp_high_start.value()),
                "clock_in_poll_hour": int(self.sp_poll_h.value()),
                "clock_in_poll_minute": int(self.sp_poll_m.value()),
                "remind_stop_hour": int(self.sp_stop_h.value()),
                "remind_stop_minute": int(self.sp_stop_m.value()),
                "holiday_cache_hours": int(self.sp_holiday.value()),
                "attendance": {
                    "api_base": self.ed_att_api.text().strip(),
                    "id": self.ed_att_id.text().strip(),
                    "app_no": self.ed_att_app.text().strip(),
                },
                "door": {
                    "api": self.ed_door_api.text().strip(),
                    "device_serial": serial,
                    "app_no": self.ed_door_app.text().strip(),
                    "authperm": self.ed_door_auth.text().strip(),
                },
                "ai": {
                    "base_url": self.ed_ai_base.text().strip(),
                    "model": self.ed_ai_model.text().strip(),
                    "enable_ai": self.ck_ai.isChecked(),
                    "enable_agent": self.ck_agent.isChecked(),
                    "enable_chat": self.ck_chat.isChecked(),
                    "enable_web_search": self.ck_web.isChecked(),
                    "enable_read_file": self.ck_read.isChecked(),
                    "agent_max_rounds": int(self.sp_rounds.value()),
                    "chat_context_messages": int(self.sp_ctx.value()),
                    "file_whitelist_dirs": whitelist,
                    "search_endpoint": self.ed_search_ep.text().strip(),
                    "hotkey_chat": (
                        self.ed_hotkey_chat.text().strip() or DEFAULT_HOTKEY_CHAT
                    ),
                },
                "fun": {
                    "enable": self.ck_fun.isChecked(),
                    "pet_enable": self.ck_pet.isChecked(),
                    "pet": str(self.cb_pet.currentData() or "shiba"),
                    "persona": str(self.cb_persona.currentData() or "secretary"),
                    "card_mode": str(self.cb_fun_card.currentData() or "puzzle"),
                    "usage_link": self.ck_fun_usage.isChecked(),
                    "woodfish_enable": self.ck_woodfish.isChecked(),
                    "woodfish_sound": self.ck_woodfish_sound.isChecked(),
                    "salary_enable": self.ck_salary.isChecked(),
                    "hourly_rate": float(self.sp_hourly_rate.value()),
                    "salary_slack": self.ck_salary_slack.isChecked(),
                    "salary_rest": self.ck_salary_rest.isChecked(),
                    "salary_unknown": self.ck_salary_unknown.isChecked(),
                },
                "takeout_remind": {
                    "enable": self.ck_takeout.isChecked(),
                    "hour": int(self.sp_takeout_h.value()),
                    "minute": int(self.sp_takeout_m.value()),
                    "text": (
                        self.ed_takeout_text.text().strip() or DEFAULT_TAKEOUT_TEXT
                    ),
                },
            }
        )
        reload_settings()
        if self._on_saved:
            self._on_saved()
        QMessageBox.information(self, "已保存", "配置已写入并生效。")
        self.accept()
