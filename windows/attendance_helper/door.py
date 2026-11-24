# Copyright (c) iGroup China.
# All rights reserved.
"""
一键开门。

@author Kai
@date 2026/09/01 10:12
@description 仅开门成功后记冷却；失败可立刻重试
"""

from __future__ import annotations

import threading
import time

from .config import S
from .hikiot_login import AuthFailure, ensure_access_token, raise_if_auth_failure, recover_access_token
from .paths import DEFAULT_USER_AGENT, LOG
from .util import mask_token

# 先加载 paths 以持久化 CA 证书，再让 requests 缓存 bundle 路径
import requests

_last_door_at = 0.0
_door_lock = threading.Lock()


def open_door() -> tuple[bool, str]:
    """
    调用一键开门接口。

    @return (是否成功, 简短消息)
    @author Kai
    @date 2026/09/01 10:12
    """
    global _last_door_at

    with _door_lock:
        now_ts = time.time()
        elapsed = now_ts - _last_door_at
        if elapsed < S.door_cooldown_seconds:
            wait = int(S.door_cooldown_seconds - elapsed)
            return False, f"请 {wait} 秒后再试"

        if not S.door_device_id:
            return False, "未配置 DOOR_DEVICE_ID"

        try:
            token = ensure_access_token()
            data = _post_door(token)
        except AuthFailure as exc:
            try:
                token = recover_access_token(token, exc)
                data = _post_door(token)
            except (AuthFailure, RuntimeError) as retry_exc:
                return False, str(retry_exc)[:60]
        except RuntimeError as exc:
            return False, str(exc)[:60]
        except Exception as exc:  # noqa: BLE001
            LOG.warning("开门异常: %s", exc)
            return False, str(exc)[:60]

        if isinstance(data, dict) and data.get("code") == 0:
            # 只在真正发出成功后再记冷却，失败可立刻重试
            _last_door_at = time.time()
            return True, "开门请求已发送，请确认门禁状态"
        msg = ""
        if isinstance(data, dict):
            msg = str(data.get("msg") or data.get("message") or "")
        return False, (msg or "开门失败")[:60]


def _post_door(token: str) -> dict:
    """
    用指定 Token 调用一键开门。

    @param token Bearer Token，不要带 Bearer 前缀
    @return 接口 JSON
    @author Kai
    @date 2026/11/20 09:31
    """
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "authperm": S.door_authperm,
        "deviceid": S.door_device_id,
        "appno": S.door_app_no,
        "terminal": "2",
        "origin": "https://www.hikiot.com",
        "referer": "https://www.hikiot.com/",
        "stn-phonetype": "Android",
        "user-agent": DEFAULT_USER_AGENT,
    }
    LOG.info(
        "开门请求 deviceSerial=%s token=%s",
        S.door_device_serial,
        mask_token(token),
    )
    resp = requests.post(
        S.door_api,
        headers=headers,
        json={"deviceSerial": S.door_device_serial},
        timeout=8,
    )
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        data = None
    message = ""
    if isinstance(data, dict):
        message = str(data.get("msg") or data.get("message") or "")
    raise_if_auth_failure(resp.status_code, data, message)
    resp.raise_for_status()
    if not isinstance(data, dict):
        raise RuntimeError("接口无返回")
    return data
