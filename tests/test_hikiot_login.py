# Copyright (c) iGroup China.
# All rights reserved.
"""
海康自动换票。

@author Kai
@date 2026/11/20 09:31
@description 校验密码加密，以及 Token 失效后只自动登录一次
"""

from __future__ import annotations

import base64
import unittest
from datetime import date
from unittest.mock import patch

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from attendance_helper.config import S, reload_settings
from attendance_helper.hikiot_login import (
    CODE_LOGIN_URL,
    LOGIN_AES_IV,
    LOGIN_AES_KEY,
    SEND_MESSAGE_URL,
    encrypt_login_password,
    is_auth_failure,
    refresh_access_token,
    set_device_verify_input,
)
from attendance_helper.attendance import fetch_attendance


def _decrypt_login_password(cipher_text: str) -> str:
    """
    解密登录密文，用来确认和网页 AES-256-CBC 一致。

    @param cipher_text Base64 密文
    @return 明文密码
    @author Kai
    @date 2026/11/20 09:31
    """
    raw = base64.b64decode(cipher_text)
    decryptor = Cipher(algorithms.AES(LOGIN_AES_KEY), modes.CBC(LOGIN_AES_IV)).decryptor()
    padded = decryptor.update(raw) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")


class _Response:
    """测试用 HTTP 响应。"""

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        """返回预设 JSON。"""
        return self._payload

    def raise_for_status(self) -> None:
        """4xx/5xx 视为失败。"""
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class LoginCryptoTest(unittest.TestCase):
    """
    登录密码加密。

    @author Kai
    @date 2026/11/20 09:31
    @description 密文必须能按同一密钥解回原文
    """

    def test_encrypt_roundtrip(self) -> None:
        """明文加密后再解密，应得到原密码。"""
        plain = "desk-login-secret"
        self.assertEqual(_decrypt_login_password(encrypt_login_password(plain)), plain)

    def test_auth_failure_codes(self) -> None:
        """业务码 999999 和登录失效文案都要触发换票。"""
        self.assertTrue(is_auth_failure(200, {"code": 999999, "msg": "登录状态已失效"}))
        self.assertTrue(is_auth_failure(401, None, "unauthorized"))
        self.assertFalse(is_auth_failure(200, {"code": 0, "msg": "ok"}))


class RefreshTokenTest(unittest.TestCase):
    """
    Token 失效后的自动登录。

    @author Kai
    @date 2026/11/20 09:31
    @description 不访问真实接口
    """

    def tearDown(self) -> None:
        """恢复磁盘上的配置，避免测试改写内存中的账号。"""
        set_device_verify_input(None, None)
        reload_settings()

    @patch("attendance_helper.hikiot_login.save_env_map")
    @patch("attendance_helper.hikiot_login.requests.request")
    @patch("attendance_helper.hikiot_login.requests.post")
    @patch("attendance_helper.attendance.requests.get")
    def test_expired_token_logs_in_once(
        self,
        attendance_get,
        login_post,
        authorized_request,
        _save_env,
    ) -> None:
        """打卡返回 999998 时登录、选团队，再用新 Token 重试。"""
        S.attendance_username = "13000000000"
        S.attendance_password = "secret"
        S.attendance_token = "old-token"
        S.attendance_team_no = "TEAM-1"
        login_post.return_value = _Response(200, {"code": 0, "data": {"token": "new-token"}})
        authorized_request.return_value = _Response(200, {"code": 0, "data": {}})
        attendance_get.side_effect = [
            _Response(200, {"code": 999998, "msg": "access token expired"}),
            _Response(200, {"code": 0, "data": {"dailyDetail": {}}}),
        ]

        payload = fetch_attendance(date(2026, 11, 20))

        self.assertEqual(payload.get("code"), 0)
        self.assertEqual(S.attendance_token, "new-token")
        self.assertEqual(login_post.call_count, 1)
        self.assertEqual(attendance_get.call_count, 2)
        self.assertIn("new-token", attendance_get.call_args.kwargs["headers"]["authorization"])

    @patch("attendance_helper.hikiot_login.save_env_map")
    @patch("attendance_helper.hikiot_login.requests.request")
    @patch("attendance_helper.hikiot_login.requests.post")
    def test_new_device_sends_sms_then_code_login(
        self,
        login_post,
        authorized_request,
        _save_env,
    ) -> None:
        """
        未登记设备要先发短信，再用验证码换 Token。

        @author Kai
        @date 2026/11/24 14:50
        """
        S.attendance_username = "13000000000"
        S.attendance_password = "secret"
        S.attendance_token = ""
        S.attendance_team_no = "TEAM-1"
        set_device_verify_input(lambda: "captcha-param", lambda _phone: "123456")
        login_post.side_effect = [
            _Response(200, {"code": 104004, "msg": "新设备"}),
            _Response(200, {"code": 0, "msg": "ok"}),
            _Response(200, {"code": 0, "data": {"token": "sms-token"}}),
        ]
        authorized_request.return_value = _Response(200, {"code": 0, "data": {}})

        token = refresh_access_token()

        self.assertEqual(token, "sms-token")
        urls = [call.args[0] for call in login_post.call_args_list]
        self.assertEqual(urls[1], SEND_MESSAGE_URL)
        self.assertEqual(urls[2], CODE_LOGIN_URL)
        self.assertEqual(
            login_post.call_args_list[1].kwargs["json"]["captchaVerifyParam"],
            "captcha-param",
        )
        self.assertEqual(login_post.call_args_list[2].kwargs["json"]["code"], "123456")


if __name__ == "__main__":
    unittest.main()
