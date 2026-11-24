# Copyright (c) iGroup China.
# All rights reserved.
"""
命令行自检。

@author Kai
@date 2026/07/23 15:25
@description python attendance_tray.py --check [--open-door]
"""

from __future__ import annotations

from datetime import date

from .attendance import get_attendance_summary, write_status_file
from .config import S, has_attendance_login
from .door import open_door
from .holiday import is_workday
from .paths import CONFIG_PATH, STATUS_PATH
from .util import format_duration, format_hm, mask_token


def run_check(do_open_door: bool = False) -> int:
    """
    自检：配置、节假日、打卡；可选真实开门。

    @param do_open_door 是否实际调用开门接口
    @return 进程退出码，0 表示通过
    @author Kai
    @date 2026/07/23 15:25
    """
    print("=== AttendanceHelper 自检 ===")
    print(f"config     : {CONFIG_PATH}")
    if S.attendance_token:
        print(f"token      : {mask_token(S.attendance_token)}")
    elif has_attendance_login():
        print("token      : (未缓存，将用账号自动登录)")
    else:
        print("token      : (empty)")
    print(f"door_device: {S.door_device_id or '(empty)'}")
    print(f"door_serial: {S.door_device_serial}")

    errors: list[str] = []
    if not S.attendance_token and not has_attendance_login():
        errors.append("缺少 ATTENDANCE_TOKEN，且未配置登录账号密码")
    # DOOR_DEVICE_ID 有公司默认值，缺省时会自动填入
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        print("请复制 .env.example 为 .env，或在托盘「设置」中填写。")
        return 1

    today = date.today()
    print(f"\n[1/3] 节假日判断 {today.isoformat()} ...")
    try:
        workday = is_workday(today)
        print(f"[OK]  is_workday={workday}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {exc}")
        return 1

    print("\n[2/3] 打卡接口 ...")
    summary = get_attendance_summary()
    if not summary.ok:
        print(f"[FAIL] {summary.error}")
        return 1
    print(
        f"[OK]  上班={format_hm(summary.in_time)} "
        f"可走={format_hm(summary.target_time)} "
        f"已工作={format_duration(summary.worked_seconds)} "
        f"剩余={summary.remaining_seconds // 60}分钟 "
        f"达标={summary.target_reached}"
    )
    write_status_file(summary)
    print(f"      已写入 {STATUS_PATH.name}")

    print("\n[3/3] 开门接口 ...")
    if not do_open_door:
        print("[SKIP] 默认不真实开门。需要时加参数: --check --open-door")
    else:
        answer = input(f"确认打开门禁 {S.door_device_serial}? [y/N] ").strip().lower()
        if answer != "y":
            print("[SKIP] 已取消开门")
        else:
            ok, msg = open_door()
            print(f"[{'OK' if ok else 'FAIL'}] {msg}")
            if not ok:
                return 1

    print("\n自检完成。启动托盘: python attendance_tray.py")
    return 0
