# Copyright (c) iGroup China.
# All rights reserved.
"""
一键诊断：打卡 / 门禁 / Token / 节假日 / 配置。

@author Kai
@date 2026/07/23 17:05
@description 托盘菜单「诊断…」
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..attendance import get_attendance_summary
from ..config import S, has_attendance_login
from ..holiday import is_workday
from ..paths import CONFIG_PATH, ENV_PATH, LOG
from ..ssl_certs import ca_bundle_path, ensure_ca_bundle
from ..util import mask_token


class _DiagWorker(QThread):
    """后台跑诊断，避免卡住 UI。"""

    finished_text = Signal(str)

    def __init__(self, last_update: str = "--") -> None:
        super().__init__()
        self._last_update = last_update or "--"

    def run(self) -> None:
        lines: list[str] = []
        now = datetime.now()
        token_status = "未配置"
        att_line = "打卡接口：未检测"
        tip_lines: list[str] = []

        # 打卡 + Token
        try:
            if not S.attendance_token and not has_attendance_login():
                att_line = "打卡接口：未配置 Token"
                token_status = "未配置"
            else:
                summary = get_attendance_summary(now)
                if summary.token_expired:
                    att_line = "打卡接口：Token 已过期"
                    token_status = "已过期"
                    tip_lines = [
                        "",
                        "自动登录未成功",
                        "请在设置中核对海康账号和密码",
                    ]
                elif not summary.ok:
                    att_line = f"打卡接口：异常 — {summary.error}"
                    token_status = "可能无效"
                else:
                    att_line = "打卡接口：正常"
                    token_status = "有效"
        except Exception as exc:  # noqa: BLE001
            att_line = f"打卡接口：异常 — {exc}"
            token_status = "检测失败"

        # 门禁：不真实开门，只查配置
        try:
            if not S.attendance_token and not has_attendance_login():
                door_line = "门禁接口：未配置 Token"
            elif not S.door_device_id or not S.door_device_serial:
                door_line = "门禁接口：配置不完整"
            else:
                door_line = "门禁接口：正常"
        except Exception as exc:  # noqa: BLE001
            door_line = f"门禁接口：异常 — {exc}"

        # 节假日
        try:
            wd = is_workday(date.today())
            holiday_line = f"节假日接口：正常（今日{'工作日' if wd else '非工作日'}）"
        except Exception as exc:  # noqa: BLE001
            holiday_line = f"节假日接口：异常 — {exc}"

        # 配置
        try:
            ok_cfg = CONFIG_PATH.exists()
            cfg_line = "配置文件：正常" if ok_cfg else "配置文件：异常（缺少 config.json）"
            if not ENV_PATH.exists() and not S.attendance_token and not has_attendance_login():
                cfg_line = "配置文件：异常（缺少 .env / Token）"
        except Exception as exc:  # noqa: BLE001
            cfg_line = f"配置文件：异常 — {exc}"

        # TLS CA：单文件 exe 的 Temp\\_MEI* 证书可能被系统清掉
        try:
            bundle = ensure_ca_bundle()
            persistent = ca_bundle_path()
            if bundle:
                tls_line = f"TLS 证书：正常（{bundle}）"
            elif persistent.exists():
                tls_line = f"TLS 证书：异常（{persistent} 不可用）"
            else:
                tls_line = "TLS 证书：异常（找不到 CA 证书包，请重启或重新打包）"
        except Exception as exc:  # noqa: BLE001
            tls_line = f"TLS 证书：异常 — {exc}"

        lines.extend(
            [
                att_line,
                door_line,
                f"Token：{token_status}",
                holiday_line,
                cfg_line,
                tls_line,
                f"最近更新：{self._last_update}",
                "",
                f"Token 掩码：{mask_token(S.attendance_token)}",
                f"开门序列号：{S.door_device_serial}",
                f"诊断时刻：{now.strftime('%H:%M:%S')}",
            ]
        )
        lines.extend(tip_lines)
        self.finished_text.emit("\n".join(lines))


class DiagnosticsDialog(QDialog):
    """
    诊断对话框。

    @author Kai
    @date 2026/07/23 17:05
    @description 展示各依赖是否正常
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        last_update: str = "--",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("考勤助手 · 诊断")
        self.setMinimumSize(420, 320)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        tip = QLabel(f"最近业务更新：{last_update}")
        tip.setStyleSheet("color:#666;")
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText("诊断中…")

        self.btn_run = QPushButton("重新诊断")
        self.btn_run.clicked.connect(self._start)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(tip)
        layout.addWidget(self.text)
        layout.addWidget(self.btn_run)
        layout.addWidget(buttons)

        self._last_update = last_update
        self._worker: Optional[_DiagWorker] = None
        self._start()

    def _start(self) -> None:
        """启动后台诊断。"""
        self.btn_run.setEnabled(False)
        self.text.setPlainText("诊断中，请稍候…")
        self._worker = _DiagWorker(self._last_update)
        self._worker.finished_text.connect(self._on_done)
        self._worker.start()

    def _on_done(self, text: str) -> None:
        self.text.setPlainText(text)
        self.btn_run.setEnabled(True)
        LOG.info("诊断完成")
