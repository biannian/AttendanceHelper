# Copyright (c) iGroup China.
# All rights reserved.
"""
首次使用向导：填 Token；开门序列号默认 L40858918。

@author Kai
@date 2026/07/23 16:25
@description 给零基础用户的一屏配置
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    DEFAULT_DOOR_DEVICE_ID,
    DEFAULT_DOOR_SERIAL,
    load_config_dict,
    read_env_map,
    reload_settings,
    save_config_dict,
    save_env_map,
)
from ..startup import enable_startup


class FirstRunWizard(QDialog):
    """
    首次启动向导。

    @author Kai
    @date 2026/07/23 16:25
    @description Token 必填；开门 Device ID 默认门禁序列号
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("考勤助手 · 一键设置")
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        title = QLabel("欢迎使用考勤助手")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        tip = QLabel(
            "填写海康登录账号和密码后，Token 会自动获取并在失效时换票。\n"
            "也可以只填已有 Token。\n"
            "开门 Device ID 默认 L40858918，一般不用改。\n"
            "填完点「完成」——勾选开机自启后，下次开机自动跑。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#555; margin-bottom: 8px;")

        self.ed_username = QLineEdit()
        self.ed_username.setClearButtonEnabled(True)
        self.ed_username.setPlaceholderText("海康登录手机号")
        self.ed_password = QLineEdit()
        self.ed_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_password.setClearButtonEnabled(True)
        self.ed_password.setPlaceholderText("登录密码")
        self.ed_token = QLineEdit()
        self.ed_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_token.setClearButtonEnabled(True)
        self.ed_token.setPlaceholderText("可留空，有账号密码时自动获取")
        self.ed_door = QLineEdit()
        self.ed_door.setPlaceholderText(DEFAULT_DOOR_SERIAL)

        form = QFormLayout()
        form.addRow("登录账号", self.ed_username)
        form.addRow("登录密码", self.ed_password)
        form.addRow("登录 Token", self.ed_token)
        form.addRow("开门 Device ID", self.ed_door)

        self.chk_startup = QCheckBox("开机自动启动（推荐，一劳永逸）")
        self.chk_startup.setChecked(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("完成，开始使用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("以后再说")
        buttons.accepted.connect(self._finish)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(tip)
        layout.addLayout(form)
        layout.addWidget(self.chk_startup)
        layout.addWidget(buttons)

        env = read_env_map()
        cfg = load_config_dict()
        door_cfg = cfg.get("door", {}) or {}
        self.ed_username.setText(env.get("ATTENDANCE_USERNAME", ""))
        self.ed_password.setText(env.get("ATTENDANCE_PASSWORD", ""))
        self.ed_token.setText(env.get("ATTENDANCE_TOKEN", ""))
        # 界面上的「开门 Device ID」= 门禁序列号 deviceSerial
        self.ed_door.setText(
            str(door_cfg.get("device_serial") or "").strip() or DEFAULT_DOOR_SERIAL
        )

    def _finish(self) -> None:
        """保存并可选启用自启。"""
        username = self.ed_username.text().strip()
        password = self.ed_password.text().strip()
        token = self.ed_token.text().strip()
        serial = self.ed_door.text().strip() or DEFAULT_DOOR_SERIAL
        if not token and not (username and password):
            QMessageBox.warning(self, "还没填完", "请填写账号密码，或填写 Token。")
            return

        # 账号密码用于自动换票；序列号写入 config
        save_env_map(
            {
                "ATTENDANCE_TOKEN": token,
                "ATTENDANCE_USERNAME": username,
                "ATTENDANCE_PASSWORD": password,
                "DOOR_DEVICE_ID": DEFAULT_DOOR_DEVICE_ID,
            }
        )
        save_config_dict({"door": {"device_serial": serial}})
        reload_settings()

        if self.chk_startup.isChecked():
            ok, msg = enable_startup()
            if not ok:
                QMessageBox.warning(
                    self,
                    "自启没设上",
                    f"凭据已保存，但开机自启失败：\n{msg}\n"
                    "可稍后在托盘右键菜单里再点「一键开机自启」。",
                )
            else:
                QMessageBox.information(
                    self,
                    "搞定",
                    "设置完成！\n已开启开机自启。\n左键看详情，双击开门，右键改设置。",
                )
        else:
            QMessageBox.information(
                self,
                "搞定",
                "凭据已保存。\n需要自启时，右键托盘 →「一键开机自启」。",
            )
        self.accept()
