# Copyright (c) iGroup China.
# All rights reserved.
"""
新设备安全验证窗口。

@author Kai
@date 2026/11/24 14:50
@description 嵌入网页同款滑块，取出 captchaVerifyParam，再让用户填写短信验证码
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QVBoxLayout,
)

# 与登录页 MessageSafeValidate 一致的阿里云验证码参数
_CAPTCHA_REGION = "cn"
_CAPTCHA_PREFIX = "1jgloq"
_CAPTCHA_SCENE = "1w0ysb3s"

# 滑块页。成功后把参数交给 Qt
_CAPTCHA_HTML = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
window.AliyunCaptchaConfig = {{region: "{_CAPTCHA_REGION}", prefix: "{_CAPTCHA_PREFIX}"}};
</script>
<script src="https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js"></script>
</head>
<body style="font-family:sans-serif;margin:12px;">
<p>请完成下方验证。通过后会发送短信验证码。</p>
<div id="captcha-element"></div>
<button id="captcha-button" style="display:none"></button>
<script>
function boot() {{
  if (!window.qt || !window.initAliyunCaptcha) {{
    setTimeout(boot, 200);
    return;
  }}
  new QWebChannel(qt.webChannelTransport, function(channel) {{
    var bridge = channel.objects.bridge;
    initAliyunCaptcha({{
      SceneId: "{_CAPTCHA_SCENE}",
      mode: "embed",
      element: "#captcha-element",
      button: "#captcha-button",
      success: function(value) {{
        bridge.acceptCaptcha(String(value || ""));
      }},
      fail: function() {{}},
      getInstance: function() {{
        var timer = setInterval(function() {{
          var body = document.getElementById("aliyunCaptcha-captcha-body");
          if (!body) {{
            return;
          }}
          body.dispatchEvent(new Event("click"));
          clearInterval(timer);
        }}, 200);
      }}
    }});
  }});
}}
boot();
</script>
</body>
</html>
"""

# 把后台线程的弹窗切回界面线程
_invoker: Optional["_UiInvoker"] = None


class _UiInvoker(QObject):
    """
    界面线程调度器。

    @author Kai
    @date 2026/11/24 14:50
    @description 登录发生在后台线程时，把滑块和输入框切回主线程
    """

    requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.requested.connect(self._run)

    def _run(self, action: Callable[[], None]) -> None:
        """
        在界面线程执行一次弹窗动作。

        @param action 无参动作
        @author Kai
        @date 2026/11/24 14:50
        """
        action()


class _CaptchaBridge(QObject):
    """
    接收网页滑块结果。

    @author Kai
    @date 2026/11/24 14:50
    @description 阿里云验证通过后，把 captchaVerifyParam 交回对话框
    """

    received = Signal(str)

    @Slot(str)
    def acceptCaptcha(self, value: str) -> None:
        """
        网页回调，滑块已经通过。

        @param value captchaVerifyParam
        @author Kai
        @date 2026/11/24 14:50
        """
        self.received.emit(value or "")


class _CaptchaDialog(QDialog):
    """
    新设备滑块验证。

    @author Kai
    @date 2026/11/24 14:50
    @description 展示与网页登录相同的阿里云滑块
    """

    def __init__(self) -> None:
        super().__init__()
        # 滑块通过后的 captchaVerifyParam
        self.param = ""
        self.setWindowTitle("新设备安全验证")
        self.resize(460, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("这台设备还未登记。完成验证后，短信验证码会发到登录手机。"))
        view = QWebEngineView(self)
        settings = view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True,
        )
        bridge = _CaptchaBridge(view)
        bridge.received.connect(self._accept_param)
        channel = QWebChannel(view.page())
        channel.registerObject("bridge", bridge)
        view.page().setWebChannel(channel)
        view.setHtml(_CAPTCHA_HTML, QUrl("https://www.hikiot.com/"))
        layout.addWidget(view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_param(self, value: str) -> None:
        """
        记下滑块参数并关闭窗口。

        @param value captchaVerifyParam
        @author Kai
        @date 2026/11/24 14:50
        """
        self.param = (value or "").strip()
        self.accept()


def install_device_verify_invoker() -> None:
    """
    在界面线程创建弹窗调度器。

    @author Kai
    @date 2026/11/24 14:50
    """
    global _invoker
    _invoker = _UiInvoker()


def collect_captcha_param() -> str:
    """
    弹出滑块，返回网页发短信用的 captchaVerifyParam。

    @return 滑块参数；用户取消时返回空串
    @author Kai
    @date 2026/11/24 14:50
    """

    def ask() -> str:
        dialog = _CaptchaDialog()
        dialog.exec()
        return dialog.param

    return str(_on_ui_thread(ask) or "")


def collect_sms_code() -> str:
    """
    让用户填写短信验证码。

    @return 用户输入；取消时返回空串
    @author Kai
    @date 2026/11/24 14:50
    """

    def ask() -> str:
        text, ok = QInputDialog.getText(
            None,
            "新设备安全验证",
            "验证码已发送到登录手机，请输入 6 位短信验证码",
        )
        if not ok:
            return ""
        return str(text or "").strip()

    return str(_on_ui_thread(ask) or "")


def _on_ui_thread(action: Callable[[], str]) -> str:
    """
    保证弹窗发生在界面线程。

    @param action 返回字符串的界面动作
    @return 动作结果
    @author Kai
    @date 2026/11/24 14:50
    """
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("新设备需要安全验证，请在桌面程序里完成")
    if QThread.currentThread() == app.thread():
        return action()
    if _invoker is None:
        raise RuntimeError("新设备需要安全验证，请重新打开桌面程序后再试")
    box: dict[str, object] = {}
    done = threading.Event()

    def wrapped() -> None:
        try:
            box["value"] = action()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            done.set()

    _invoker.requested.emit(wrapped)
    done.wait()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return str(box.get("value") or "")
