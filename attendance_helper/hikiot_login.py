# Copyright (c) iGroup China.
# All rights reserved.
"""
海康互联账号登录。

@author Kai
@date 2026/11/20 09:31
@description Token 缺失或失效时，按网页登录同一套 AES 加密换票并进入团队
"""

from __future__ import annotations

import base64
import re
import threading
from typing import Any, Callable, Optional

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .config import (
    DEFAULT_LOGIN_DEVICE_ID,
    S,
    normalize_token,
    save_env_map,
)
from .paths import LOG
from .util import mask_token


# 密码登录。成功时 data.token 是新的 Bearer Token
LOGIN_URL = "https://api.hikiot.com/api-saas/open/v1/pwdLogin"
# 网页端固定客户端标识，不是用户 Token
LOGIN_BASIC = "Basic bGluay13ZWI6bGluaw=="
# 账号详情，用来确定团队编号
ACCOUNT_DETAIL_URL = "https://api.hikiot.com/api-saas/v1/account/detail"
# 选定团队。未选团队时，打卡接口会返回登录状态已失效
TEAM_CHANGE_URL = "https://api.hikiot.com/api-link-saas/v3/team/change"
# 新设备发短信。请求体带手机号和滑块参数 captchaVerifyParam
SEND_MESSAGE_URL = "https://api.hikiot.com/api-saas/open/v3/sendMessage"
# 短信验证码登录。新设备通过后 data.token 才是可用 Token
CODE_LOGIN_URL = "https://api.hikiot.com/api-saas/open/v1/codeLogin"
# 密码登录命中未登记设备时的业务码，网页会进入安全验证
NEW_DEVICE_CODE = 104004
# 网页登录页 AES-256 密钥，按 UTF-8 字节使用
LOGIN_AES_KEY = b"I0YmM5NTgtY2IyYi00OWIzLWFkZTktZj"
# 网页登录页 AES 初始向量
LOGIN_AES_IV = b"BjNzhiZDctOGMxOS"
# 与 iOS 登录头一致，沿用已登记设备的客户端标识
LOGIN_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "Html5Plus/1.0 (Immersed/47) uni-app"
)

_AUTH_TEXT = re.compile(
    r"access token|token expired|invalid access token|登录状态已?失效|请重新登录",
    re.IGNORECASE,
)
_LOGIN_LOCK = threading.Lock()
# 测试或无界面场景注入的滑块参数和短信验证码
_captcha_provider: Optional[Callable[[], str]] = None
_sms_provider: Optional[Callable[[str], str]] = None


class AuthFailure(Exception):
    """
    登录态失效。

    @author Kai
    @date 2026/11/20 09:31
    @description 带业务码，用来决定是进入团队还是重新登录
    """

    def __init__(self, message: str, auth_code: int = 0) -> None:
        super().__init__(message)
        # 接口业务码；HTTP 401 且没有业务码时为 401
        self.auth_code = int(auth_code or 0)


def set_device_verify_input(
    captcha_provider: Optional[Callable[[], str]],
    sms_provider: Optional[Callable[[str], str]],
) -> None:
    """
    注入新设备验证所需的滑块参数和短信验证码。

    @param captcha_provider 返回 captchaVerifyParam；界面登录时不传
    @param sms_provider 按手机号返回 6 位验证码；界面登录时不传
    @author Kai
    @date 2026/11/24 14:50
    """
    global _captcha_provider, _sms_provider
    _captcha_provider = captcha_provider
    _sms_provider = sms_provider


def has_login_account() -> bool:
    """
    是否已配置可用于自动换票的账号和密码。

    @return 账号和密码都有时返回 True
    @author Kai
    @date 2026/11/20 09:31
    """
    return bool((S.attendance_username or "").strip() and (S.attendance_password or "").strip())


def encrypt_login_password(plain_text: str) -> str:
    """
    把登录密码加密成网页登录接口要的密文。

    @param plain_text 登录密码明文
    @return Base64 密文
    @author Kai
    @date 2026/11/20 09:31
    """
    padder = padding.PKCS7(128).padder()
    padded = padder.update((plain_text or "").encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(LOGIN_AES_KEY), modes.CBC(LOGIN_AES_IV)).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def auth_code_of(status_code: int, payload: Optional[dict[str, Any]]) -> int:
    """
    取出登录失效业务码。

    @param status_code HTTP 状态码
    @param payload 接口 JSON；没有响应体时传 None
    @return 业务码；只有 HTTP 401 时返回 401
    @author Kai
    @date 2026/11/20 09:31
    """
    if isinstance(payload, dict) and payload.get("code") is not None:
        try:
            return int(payload.get("code"))
        except (TypeError, ValueError):
            pass
    if status_code == 401:
        return 401
    return int(status_code or 0)


def is_auth_failure(
    status_code: int,
    payload: Optional[dict[str, Any]],
    message: str = "",
) -> bool:
    """
    判断这次失败是不是 Token 过期或失效。

    @param status_code HTTP 状态码
    @param payload 接口 JSON；没有响应体时传 None
    @param message 异常文案
    @return 需要重新登录时返回 True
    @author Kai
    @date 2026/11/20 09:31
    """
    code = auth_code_of(status_code, payload) if isinstance(payload, dict) else 0
    text = ""
    if isinstance(payload, dict):
        text = str(payload.get("msg") or payload.get("message") or "")
    text = text or message or ""
    if status_code in (401, 403) or code in (401, 999999, 999998, 999997, 999996):
        return True
    return bool(_AUTH_TEXT.search(text))


def raise_if_auth_failure(
    status_code: int,
    payload: Any,
    message: str = "",
) -> None:
    """
    登录失效时抛出带业务码的错误。

    @param status_code HTTP 状态码
    @param payload 接口 JSON
    @param message 异常文案
    @author Kai
    @date 2026/11/20 09:31
    """
    body = payload if isinstance(payload, dict) else None
    if not is_auth_failure(status_code, body, message):
        return
    text = message
    if body is not None:
        text = str(body.get("msg") or body.get("message") or message or "")
    raise AuthFailure(text or "登录已过期，请更新 Token", auth_code_of(status_code, body))


def ensure_access_token() -> str:
    """
    返回当前可用 Token。没有缓存时用账号密码登录。

    @return Bearer Token，不带 Bearer 前缀
    @author Kai
    @date 2026/11/20 09:31
    """
    token = normalize_token(S.attendance_token)
    if token:
        return token
    if not has_login_account():
        raise RuntimeError("未配置 ATTENDANCE_TOKEN")
    return refresh_access_token()


def recover_access_token(previous: str, failure: AuthFailure) -> str:
    """
    Token 失效后的恢复：先尝试进入团队，不行再重新登录。

    @param previous 刚刚失败的 Token
    @param failure 打卡或开门返回的登录失效错误
    @return 可继续使用的 Token
    @author Kai
    @date 2026/11/20 09:31
    """
    # 999999 表示 Token 还在，但这次登录还没进入团队
    if int(failure.auth_code) == 999999 and previous:
        try:
            select_current_team(previous)
            return previous
        except AuthFailure:
            pass
    return refresh_access_token(previous=previous)


def refresh_access_token(previous: str = "") -> str:
    """
    用账号密码登录并保存新 Token。

    @param previous 调用前手里的旧 Token；其他线程已换票时直接复用
    @return 新的 Bearer Token
    @author Kai
    @date 2026/11/20 09:31
    """
    with _LOGIN_LOCK:
        current = normalize_token(S.attendance_token)
        # 并发请求里只要有一次换票成功，其余请求沿用新 Token
        if current and current != normalize_token(previous):
            return current
        if not has_login_account():
            raise RuntimeError("缺少账号或密码，无法更新 Token")
        token = _password_login()
        _store_token(token)
        select_current_team(token)
        return token


def select_current_team(token: str) -> str:
    """
    登录后进入团队。

    @param token 刚登录得到的 Bearer Token
    @return 进入的团队编号
    @author Kai
    @date 2026/11/20 09:31
    """
    detail = _authorized_json(ACCOUNT_DETAIL_URL, "GET", token)
    data = detail.get("data") if isinstance(detail.get("data"), dict) else {}
    teams = data.get("teamInfoList") if isinstance(data.get("teamInfoList"), list) else []
    team_no = (S.attendance_team_no or "").strip() or str(data.get("onLineTeamNo") or "")
    if not team_no and teams:
        first = teams[0]
        if isinstance(first, dict):
            team_no = str(first.get("teamNo") or "")
    if not team_no:
        raise RuntimeError("登录成功，但没有可进入的团队")
    _authorized_json(
        TEAM_CHANGE_URL,
        "POST",
        token,
        {"teamNo": team_no, "terminal": 2},
    )
    LOG.info("已进入团队 %s", team_no)
    return team_no


def _device_id() -> str:
    """
    登录和选团队使用的已登记 deviceid。

    @return deviceid
    @author Kai
    @date 2026/11/20 09:31
    """
    return (S.login_device_id or "").strip() or DEFAULT_LOGIN_DEVICE_ID


def _password_login() -> str:
    """
    调用密码登录接口。

    @return 新 Token
    @author Kai
    @date 2026/11/20 09:31
    """
    resp = requests.post(
        LOGIN_URL,
        json={
            "username": S.attendance_username.strip(),
            "password": encrypt_login_password(S.attendance_password),
            "isAuto": False,
        },
        headers={
            **_open_headers(),
            "login-source": "link-web",
        },
        timeout=15,
    )
    payload = _read_json(resp)
    message = _message_of(payload)
    if not isinstance(payload, dict):
        raise RuntimeError(message or "更新 Token 失败")
    try:
        code = int(payload.get("code"))
    except (TypeError, ValueError):
        code = -1
    # 未登记设备不发 Token，要先发短信再验证
    if code == NEW_DEVICE_CODE:
        return _complete_new_device_login()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    token = normalize_token(str(data.get("token") or ""))
    if code != 0 or not token:
        raise RuntimeError(message or "更新 Token 失败")
    return token


def _complete_new_device_login() -> str:
    """
    新设备：取滑块参数、发送短信、提交验证码并换票。

    @return 验证通过后的 Bearer Token
    @author Kai
    @date 2026/11/24 14:50
    """
    phone = (S.attendance_username or "").strip()
    if not phone:
        raise RuntimeError("新设备需要短信验证，但没有登录手机号")
    captcha = _read_captcha_param()
    _send_login_sms(phone, captcha)
    code = _read_sms_code(phone)
    return _code_login(phone, code)


def _read_captcha_param() -> str:
    """
    读取滑块参数。已注入时直接用，否则弹出验证窗口。

    @return captchaVerifyParam
    @author Kai
    @date 2026/11/24 14:50
    """
    if _captcha_provider is not None:
        value = str(_captcha_provider() or "").strip()
    else:
        from .ui.device_verify_dialog import collect_captcha_param

        value = collect_captcha_param().strip()
    if not value:
        raise RuntimeError("已取消新设备验证")
    return value


def _read_sms_code(phone: str) -> str:
    """
    读取 6 位短信验证码。

    @param phone 接收验证码的登录手机号
    @return 6 位数字验证码
    @author Kai
    @date 2026/11/24 14:50
    """
    if _sms_provider is not None:
        raw = str(_sms_provider(phone) or "")
    else:
        from .ui.device_verify_dialog import collect_sms_code

        raw = collect_sms_code()
    code = re.sub(r"\D", "", raw)
    if len(code) != 6:
        raise RuntimeError("没有填写 6 位短信验证码")
    return code


def _send_login_sms(phone: str, captcha_param: str) -> None:
    """
    调用发短信接口。

    @param phone 登录手机号
    @param captcha_param 滑块返回的 captchaVerifyParam
    @author Kai
    @date 2026/11/24 14:50
    """
    payload = _post_open_json(
        SEND_MESSAGE_URL,
        {"phone": phone, "captchaVerifyParam": captcha_param},
    )
    if _biz_code(payload) != 0:
        raise RuntimeError(_message_of(payload) or "发送验证码失败")
    LOG.info("已向登录手机发送新设备验证码")


def _code_login(phone: str, sms_code: str) -> str:
    """
    用短信验证码完成新设备登录。

    @param phone 登录手机号
    @param sms_code 6 位短信验证码
    @return 新 Token
    @author Kai
    @date 2026/11/24 14:50
    """
    payload = _post_open_json(
        CODE_LOGIN_URL,
        {"phone": phone, "code": sms_code, "isAuto": False},
        extra_headers={"login-source": "link-web"},
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    token = normalize_token(str(data.get("token") or ""))
    if _biz_code(payload) != 0 or not token:
        raise RuntimeError(_message_of(payload) or "设备验证失败")
    LOG.info("新设备验证已通过")
    return token


def _post_open_json(
    url: str,
    body: dict[str, Any],
    extra_headers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    用登录页同一套客户端头提交开放接口。

    @param url 接口地址
    @param body JSON 请求体
    @param extra_headers 额外请求头
    @return 接口 JSON
    @author Kai
    @date 2026/11/24 14:50
    """
    headers = _open_headers()
    if extra_headers:
        headers.update(extra_headers)
    resp = requests.post(url, json=body, headers=headers, timeout=15)
    payload = _read_json(resp)
    if not isinstance(payload, dict):
        raise RuntimeError(_message_of(payload) or "请求失败")
    return payload


def _open_headers() -> dict[str, str]:
    """
    登录、发短信、验证码登录共用的请求头。

    @return 请求头
    @author Kai
    @date 2026/11/24 14:50
    """
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Authorization": LOGIN_BASIC,
        "deviceid": _device_id(),
        "STN-PhoneType": "Iphone",
        "devicename": "unknow 0",
        "terminal": "2",
        "User-Agent": LOGIN_USER_AGENT,
    }


def _biz_code(payload: Any) -> int:
    """
    读取业务码。

    @param payload 接口 JSON
    @return 业务码；缺失时为 -1
    @author Kai
    @date 2026/11/24 14:50
    """
    if not isinstance(payload, dict):
        return -1
    try:
        return int(payload.get("code"))
    except (TypeError, ValueError):
        return -1


def _authorized_json(
    url: str,
    method: str,
    token: str,
    body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    携带登录 Token 请求账号或团队接口。

    @param url 接口地址
    @param method GET 或 POST
    @param token Bearer Token
    @param body POST 请求体；GET 时不传
    @return 接口 JSON
    @author Kai
    @date 2026/11/20 09:31
    """
    kwargs: dict[str, Any] = {}
    if body is not None:
        kwargs["json"] = body
    resp = requests.request(
        method,
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
            "deviceid": _device_id(),
            "terminal": "2",
            "STN-PhoneType": "Iphone",
            "devicename": "unknow 0",
            "User-Agent": LOGIN_USER_AGENT,
        },
        timeout=15,
        **kwargs,
    )
    payload = _read_json(resp)
    message = _message_of(payload)
    raise_if_auth_failure(resp.status_code, payload, message)
    if resp.status_code >= 400 or not isinstance(payload, dict):
        raise RuntimeError(message or "请求失败")
    code = payload.get("code")
    if code not in (0, 200, None):
        raise RuntimeError(message or "请求失败")
    return payload


def _store_token(token: str) -> None:
    """
    把新 Token 写入内存和 .env。

    @param token 登录接口返回的 Bearer Token
    @author Kai
    @date 2026/11/20 09:31
    """
    import os

    cleaned = normalize_token(token)
    S.attendance_token = cleaned
    os.environ["ATTENDANCE_TOKEN"] = cleaned
    save_env_map({"ATTENDANCE_TOKEN": cleaned})
    LOG.info("已自动更新打卡 Token (%s)", mask_token(cleaned))


def _read_json(resp: requests.Response) -> Any:
    """
    读取响应 JSON。解析失败时返回 None。

    @param resp HTTP 响应
    @return JSON 对象或 None
    @author Kai
    @date 2026/11/20 09:31
    """
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _message_of(payload: Any) -> str:
    """
    取出接口错误文案。

    @param payload 接口 JSON
    @return 文案；没有时返回空串
    @author Kai
    @date 2026/11/20 09:31
    """
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("msg") or payload.get("message") or "")
