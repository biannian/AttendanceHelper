# Copyright (c) iGroup China.
# All rights reserved.
"""
打卡摘要拉取与规范化。

@author Kai
@date 2026/07/23 15:25
@description 工时按「上班打卡 → 当前时刻」计算
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from .cache_store import get_leave_hours, save_json_file
from .config import S
from .hikiot_login import (
    AuthFailure,
    ensure_access_token,
    raise_if_auth_failure,
    recover_access_token,
)
from .paths import DEFAULT_USER_AGENT, LOG, STATUS_PATH
from .util import deep_pick, format_duration, format_hm, mask_token, parse_time_on_date

# 先加载 paths 以持久化 CA 证书，再让 requests 缓存 bundle 路径
import requests


@dataclass
class AttendanceSummary:
    """当日打卡摘要。"""

    ok: bool
    error: str = ""
    date: str = ""
    person_name: str = ""
    in_time: Optional[datetime] = None
    latest_out_time: Optional[datetime] = None
    in_status: str = ""
    out_status: str = ""
    # 接口日状态：0 正常；非 0 多为缺卡/异常
    daily_status: Optional[int] = None
    # 是否有效考勤（接口正常 + 有上班卡）
    is_valid_attendance: bool = False
    # 有效性提示：有效 / 缺卡 / 未打卡 / 未满工时 等
    validity_tip: str = ""
    target_time: Optional[datetime] = None
    worked_seconds: int = 0
    remaining_seconds: int = 0
    target_reached: bool = False
    token_expired: bool = False
    leave_hours: float = 0.0
    required_seconds: int = 0
    # 是否来自本地历史缓存（今日不会为 True）
    cached: bool = False

    @property
    def has_clock_in(self) -> bool:
        """是否已上班打卡。"""
        return self.in_time is not None

    @property
    def has_clock_out(self) -> bool:
        """是否已打下班卡。"""
        return self.latest_out_time is not None


def _unwrap_attendance_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """
    从接口响应取出业务 payload。

    @param raw 接口原始 JSON
    @return 业务层字典
    @author Kai
    @date 2026/08/03 08:50
    """
    if not isinstance(raw, dict):
        return {}
    for key in ("data", "result", "content", "response", "body"):
        inner = raw.get(key)
        if isinstance(inner, dict):
            return inner
    return raw


def _coerce_clock_flag(value: Any) -> Optional[bool]:
    """
    将 inClocked / offClocked 转为布尔（1=已打卡）。

    @param value 接口字段值
    @return True/False/None
    @author Kai
    @date 2026/08/03 08:50
    """
    if value is None:
        return None
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return bool(value)


def _extract_shift_clock_fields(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    从 dailyDetail.shiftDetails 提取打卡字段，并尊重 offClocked。

    @param raw 接口原始 JSON
    @return 班次打卡字段；无 shiftDetails 时返回 None
    @author Kai
    @date 2026/08/03 08:50
    """
    payload = _unwrap_attendance_payload(raw)
    detail = payload.get("dailyDetail")
    if not isinstance(detail, dict):
        detail = payload
    shifts = detail.get("shiftDetails")
    if not isinstance(shifts, list) or not shifts:
        return None

    shift = shifts[0]
    if not isinstance(shift, dict):
        return None

    in_clocked = _coerce_clock_flag(shift.get("inClocked"))
    off_clocked = _coerce_clock_flag(shift.get("offClocked"))
    clock_in_raw = shift.get("clockInTime")
    clock_off_raw = shift.get("clockOffTime")

    if in_clocked is False:
        clock_in_raw = None
    if off_clocked is False:
        clock_off_raw = None

    return {
        "clock_in_raw": clock_in_raw,
        "clock_off_raw": clock_off_raw,
        "in_status": str(shift.get("clockInStatusDesc") or ""),
        "out_status": str(shift.get("clockOffStatusDesc") or ""),
        "off_clocked": off_clocked,
    }


def effective_required_seconds(leave_hours: float) -> int:
    """
    计算扣除请假后的应出勤秒数。

    @param leave_hours 请假小时
    @return 应出勤秒数（至少 0）
    @author Kai
    @date 2026/07/23 15:25
    """
    return max(0, int(round((S.target_hours - max(0.0, leave_hours)) * 3600)))


def fetch_attendance(day: date) -> dict[str, Any]:
    """
    请求个人日打卡统计接口。Token 失效时自动登录一次并重试。

    @param day 查询日期
    @return 接口 JSON
    @author Kai
    @date 2026/11/20 09:31
    """
    token = ensure_access_token()
    try:
        return _request_daily(day, token)
    except AuthFailure as exc:
        try:
            token = recover_access_token(token, exc)
            return _request_daily(day, token)
        except (AuthFailure, RuntimeError) as retry_exc:
            raise PermissionError(str(retry_exc) or "登录已过期，请更新 Token") from retry_exc


def _request_daily(day: date, token: str) -> dict[str, Any]:
    """
    用指定 Token 拉取一天打卡。

    @param day 查询日期
    @param token Bearer Token，不要带 Bearer 前缀
    @return 接口 JSON
    @author Kai
    @date 2026/11/20 09:31
    """
    # 考勤查询不传 deviceid，仅依赖 Token + appno
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "authorization": f"Bearer {token}",
        "authperm": "undefined",
        "devicename": "Chrome 150.0",
        "appno": S.att_app_no,
        "terminal": "2",
        "origin": "https://www.hikiot.com",
        "referer": "https://www.hikiot.com/",
        "stn-phonetype": "Android",
        "user-agent": DEFAULT_USER_AGENT,
    }
    params = {"date": day.isoformat(), "ID": S.att_id}
    resp = requests.get(S.att_api, headers=headers, params=params, timeout=10)
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
    code = data.get("code")
    if code not in (0, 200, None):
        raise RuntimeError(str(message or f"code={code}")[:120])
    return data


def normalize_attendance(
    raw: dict[str, Any],
    now: datetime,
    *,
    day_hint: Optional[date] = None,
) -> AttendanceSummary:
    """
    将接口响应规范为打卡摘要。

    @param raw 接口原始 JSON
    @param now 当前时间（今日工时参照）
    @param day_hint 查询日（历史日用工卡/日末估算工时）
    @return AttendanceSummary
    @author Kai
    @date 2026/07/23 17:15
    """
    date_str = (
        deep_pick(raw, ["date", "workDate", "attendanceDate", "statisticsDate"])
        or (day_hint.isoformat() if day_hint else None)
        or now.date().isoformat()
    )
    person_name = deep_pick(raw, ["personName", "userName", "employeeName"]) or ""

    shift_fields = _extract_shift_clock_fields(raw)
    if shift_fields:
        clock_in_raw = shift_fields["clock_in_raw"]
        # offClocked=0 时不得用 deep_pick 误取计划下班时间
        if shift_fields["off_clocked"] is False:
            clock_off_raw = None
        else:
            clock_off_raw = shift_fields["clock_off_raw"]
        in_status = shift_fields["in_status"] or deep_pick(
            raw, ["clockInStatusDesc", "inStatusDesc"]
        ) or ""
        out_status = shift_fields["out_status"] or deep_pick(
            raw, ["clockOffStatusDesc", "outStatusDesc"]
        ) or ""
    else:
        clock_in_raw = deep_pick(
            raw,
            ["clockInTime", "inTime", "onClockTime", "checkInTime", "signInTime"],
        )
        clock_off_raw = deep_pick(
            raw,
            [
                "clockOffTime",
                "clockOutTime",
                "outTime",
                "checkOutTime",
                "signOutTime",
            ],
        )
        in_status = deep_pick(raw, ["clockInStatusDesc", "inStatusDesc"]) or ""
        out_status = deep_pick(raw, ["clockOffStatusDesc", "outStatusDesc"]) or ""
    daily_status_raw = deep_pick(raw, ["dailyStatus"])
    try:
        daily_status = (
            int(daily_status_raw) if daily_status_raw is not None else None
        )
    except (TypeError, ValueError):
        daily_status = None

    in_time = parse_time_on_date(str(date_str)[:10], clock_in_raw)
    latest_out = parse_time_on_date(str(date_str)[:10], clock_off_raw)

    try:
        day_obj = date.fromisoformat(str(date_str)[:10])
    except ValueError:
        day_obj = day_hint or now.date()
    leave_h = get_leave_hours(day_obj)
    required = effective_required_seconds(leave_h)

    worked = 0
    remaining = 0
    target_time = None
    reached = False

    if in_time:
        target_time = in_time + timedelta(seconds=required)
        # 倒计时/工时：今日按「现在」；历史日仅有下班卡才计工时（无卡不估到日末）
        if day_obj < now.date():
            ref = latest_out
        elif day_obj > now.date():
            ref = in_time
        else:
            ref = now
        if ref is not None:
            worked = max(0, int((ref - in_time).total_seconds()))
        else:
            worked = 0
        reached = worked >= required if required > 0 else True
        if not reached and day_obj <= now.date():
            # 今日倒计时相对当前时间；历史日相对已算工时
            if day_obj == now.date():
                remaining = max(0, int((target_time - now).total_seconds()))
            elif ref is not None:
                remaining = max(0, required - worked)
            else:
                remaining = 0

        # 有效考勤用工时：有下班卡则按打卡时段（含今日早退），与倒计时分离
        if latest_out is not None:
            worked_for_validity = max(
                0, int((latest_out - in_time).total_seconds())
            )
        else:
            worked_for_validity = worked
        reached_for_validity = (
            worked_for_validity >= required if required > 0 else True
        )
    else:
        worked_for_validity = 0
        reached_for_validity = False

    is_valid, validity_tip = evaluate_attendance_validity(
        day=day_obj,
        now=now,
        in_time=in_time,
        out_time=latest_out,
        in_status=str(in_status),
        out_status=str(out_status),
        daily_status=daily_status,
        target_reached=reached_for_validity,
        worked_seconds=worked_for_validity,
        required_seconds=required,
    )

    return AttendanceSummary(
        ok=True,
        date=day_obj.isoformat(),
        person_name=str(person_name),
        in_time=in_time,
        latest_out_time=latest_out,
        in_status=str(in_status),
        out_status=str(out_status),
        daily_status=daily_status,
        is_valid_attendance=is_valid,
        validity_tip=validity_tip,
        target_time=target_time,
        worked_seconds=worked,
        remaining_seconds=remaining,
        target_reached=reached,
        leave_hours=leave_h,
        required_seconds=required,
    )


def evaluate_attendance_validity(
    *,
    day: date,
    now: datetime,
    in_time: Optional[datetime],
    out_time: Optional[datetime],
    in_status: str,
    out_status: str,
    daily_status: Optional[int],
    target_reached: bool,
    worked_seconds: int = 0,
    required_seconds: int = 0,
) -> tuple[bool, str]:
    """
    判断是否有效考勤，并给出提示文案。

    核心以应出勤工时为准：
    - 满应出勤 → 有效
    - 未满应出勤 → 无效（提示未满工时）；今日仍在班（无下班卡）→ 进行中
    - 缺卡 / 未打卡 → 无效

    @return (是否有效, 提示)
    @author Kai
    @date 2026/07/23 17:50
    """
    bad_words = ("缺卡", "旷工", "无效", "未打卡")
    in_s = (in_status or "").strip()
    out_s = (out_status or "").strip()

    if in_time is None:
        if any(w in in_s for w in bad_words) or any(w in out_s for w in bad_words):
            return False, in_s or out_s or "缺卡"
        if daily_status not in (None, 0):
            return False, out_s or in_s or "无效考勤"
        return False, "未打卡"

    if any(w in in_s for w in bad_words):
        return False, in_s or "上班异常"
    if any(w in out_s for w in bad_words):
        return False, out_s or "下班异常"

    required = max(0, int(required_seconds))
    worked = max(0, int(worked_seconds))
    if required <= 0:
        return True, "有效"

    # 工时未满
    if worked < required:
        # 今日尚未下班：进行中（不算有效考勤）
        if day == now.date() and out_time is None:
            left_m = max(1, (required - worked + 59) // 60)
            return False, f"进行中·还差{left_m}分"
        # 已下班或历史日：按工时判无效
        worked_h = worked / 3600
        need_h = required / 3600
        return False, f"未满工时({worked_h:g}/{need_h:g}h)"

    # 满工时
    tips: list[str] = []
    if in_s and in_s != "正常":
        tips.append(in_s)
    if out_s and out_s != "正常":
        tips.append(out_s)
    if tips:
        return True, "有效·" + "/".join(tips[:2])
    return True, "有效"


def _dt_to_cache(value: Optional[datetime]) -> Optional[str]:
    """datetime → 可落盘 ISO 字符串。"""
    if value is None:
        return None
    return value.isoformat(sep=" ", timespec="seconds")


def _dt_from_cache(value: Any) -> Optional[datetime]:
    """缓存字符串 → datetime。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("T", " "))
    except ValueError:
        return None


def _summary_to_cache_payload(summary: AttendanceSummary) -> dict[str, Any]:
    """
    打卡摘要 → 缓存字典。

    @param summary 摘要
    @return 可 JSON 序列化字典
    @author Kai
    @date 2026/09/01 10:00
    """
    return {
        "ok": bool(summary.ok),
        "error": str(summary.error or ""),
        "date": str(summary.date or ""),
        "person_name": str(summary.person_name or ""),
        "in_time": _dt_to_cache(summary.in_time),
        "latest_out_time": _dt_to_cache(summary.latest_out_time),
        "in_status": str(summary.in_status or ""),
        "out_status": str(summary.out_status or ""),
        "daily_status": summary.daily_status,
        "is_valid_attendance": bool(summary.is_valid_attendance),
        "validity_tip": str(summary.validity_tip or ""),
        "target_time": _dt_to_cache(summary.target_time),
        "worked_seconds": int(summary.worked_seconds or 0),
        "remaining_seconds": int(summary.remaining_seconds or 0),
        "target_reached": bool(summary.target_reached),
        "token_expired": bool(summary.token_expired),
        "leave_hours": float(summary.leave_hours or 0),
        "required_seconds": int(summary.required_seconds or 0),
    }


def _summary_from_cache_payload(payload: dict[str, Any]) -> AttendanceSummary:
    """
    缓存字典 → 打卡摘要。

    @param payload 缓存中的 summary
    @return AttendanceSummary（cached=True）
    @author Kai
    @date 2026/09/01 10:00
    """
    daily_status = payload.get("daily_status")
    try:
        daily_status_i = int(daily_status) if daily_status is not None else None
    except (TypeError, ValueError):
        daily_status_i = None
    return AttendanceSummary(
        ok=bool(payload.get("ok")),
        error=str(payload.get("error") or ""),
        date=str(payload.get("date") or ""),
        person_name=str(payload.get("person_name") or ""),
        in_time=_dt_from_cache(payload.get("in_time")),
        latest_out_time=_dt_from_cache(payload.get("latest_out_time")),
        in_status=str(payload.get("in_status") or ""),
        out_status=str(payload.get("out_status") or ""),
        daily_status=daily_status_i,
        is_valid_attendance=bool(payload.get("is_valid_attendance")),
        validity_tip=str(payload.get("validity_tip") or ""),
        target_time=_dt_from_cache(payload.get("target_time")),
        worked_seconds=int(payload.get("worked_seconds") or 0),
        remaining_seconds=int(payload.get("remaining_seconds") or 0),
        target_reached=bool(payload.get("target_reached")),
        token_expired=bool(payload.get("token_expired")),
        leave_hours=float(payload.get("leave_hours") or 0),
        required_seconds=int(payload.get("required_seconds") or 0),
        cached=True,
    )


def _should_cache_day(day: date, today: date, summary: AttendanceSummary) -> bool:
    """
    是否把该日写入历史缓存：仅今天之前、且不是登录失效/瞬时网络失败。

    @param day 业务日
    @param today 今天
    @param summary 拉取结果
    @return 是否缓存
    @author Kai
    @date 2026/09/01 10:00
    """
    if day >= today:
        return False
    if summary.token_expired:
        return False
    if summary.error == "FUTURE":
        return False
    if not summary.ok:
        err = (summary.error or "").lower()
        if any(
            token in err
            for token in ("timeout", "timed out", "连接", "网络", "502", "503", "504")
        ):
            return False
    return True


def get_attendance_for_day(
    day: date,
    now: Optional[datetime] = None,
    *,
    persist_cache: bool = True,
    force_refresh: bool = False,
) -> AttendanceSummary:
    """
    按指定日期拉取打卡摘要；历史日优先读本地缓存。

    @param day 业务日期
    @param now 当前时间
    @param persist_cache 拉取后是否立即落盘（批量查询可先关，最后统一 flush）
    @param force_refresh 为 True 时跳过缓存，强制打接口
    @return AttendanceSummary
    @author Kai
    @date 2026/09/01 10:20
    """
    from .attendance_cache import (
        flush_attendance_cache,
        get_settled_payload,
        put_settled_payload,
    )

    now = now or datetime.now()
    today = now.date()
    # 未来日不请求接口
    if day > today:
        return AttendanceSummary(ok=True, date=day.isoformat(), error="FUTURE")
    if day < today and not force_refresh:
        cached = get_settled_payload(day, today=today)
        if cached is not None:
            LOG.debug("考勤缓存命中 %s", day.isoformat())
            return _summary_from_cache_payload(cached)
    try:
        raw = fetch_attendance(day)
        summary = normalize_attendance(raw, now, day_hint=day)
    except PermissionError as exc:
        LOG.warning(
            "Token 失效(%s): %s (token=%s)",
            day.isoformat(),
            exc,
            mask_token(S.attendance_token),
        )
        return AttendanceSummary(
            ok=False,
            error=str(exc),
            token_expired=True,
            date=day.isoformat(),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("拉取打卡失败 %s: %s", day.isoformat(), exc)
        return AttendanceSummary(ok=False, error=str(exc)[:120], date=day.isoformat())

    if _should_cache_day(day, today, summary):
        put_settled_payload(day, _summary_to_cache_payload(summary))
        if persist_cache:
            flush_attendance_cache()
    return summary


def get_attendance_summary(now: Optional[datetime] = None) -> AttendanceSummary:
    """
    拉取并解析今日打卡摘要。

    @param now 可选当前时间
    @return AttendanceSummary
    @author Kai
    @date 2026/07/23 15:25
    """
    now = now or datetime.now()
    return get_attendance_for_day(now.date(), now)


def fetch_attendance_range(
    days: list[date],
    *,
    max_workers: int = 4,
    on_progress: Optional[Callable[[int, int, date], None]] = None,
    force_refresh: bool = False,
) -> dict[str, AttendanceSummary]:
    """
    批量按日拉取打卡（并行，供周/月统计）。

    @param days 日期列表
    @param max_workers 并发数
    @param on_progress 进度回调 (done, total, day)
    @param force_refresh 为 True 时先丢掉范围内缓存再打接口
    @return date_iso → AttendanceSummary
    @author Kai
    @date 2026/09/01 10:20
    """
    now = datetime.now()
    total = len(days)
    results: dict[str, AttendanceSummary] = {}
    if total == 0:
        return results

    if force_refresh:
        from .attendance_cache import drop_days, flush_attendance_cache

        drop_days(days)
        flush_attendance_cache()

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = {
            pool.submit(
                get_attendance_for_day,
                day,
                now,
                persist_cache=False,
                force_refresh=force_refresh,
            ): day
            for day in days
        }
        for fut in as_completed(futures):
            day = futures[fut]
            try:
                summary = fut.result()
            except Exception as exc:  # noqa: BLE001
                summary = AttendanceSummary(
                    ok=False, error=str(exc)[:120], date=day.isoformat()
                )
            results[day.isoformat()] = summary
            done += 1
            if on_progress:
                on_progress(done, total, day)
    from .attendance_cache import flush_attendance_cache

    flush_attendance_cache()
    return results


def write_status_file(summary: AttendanceSummary) -> None:
    """
    写出 status.json，供其它看板读取。

    @param summary 打卡摘要
    @author Kai
    @date 2026/07/23 15:25
    """
    if not summary.ok:
        payload = {
            "ok": False,
            "error": summary.error,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    else:
        remaining_min = summary.remaining_seconds // 60
        payload = {
            "ok": True,
            "date": summary.date,
            "person_name": summary.person_name,
            "in_time": format_hm(summary.in_time),
            "latest_out": format_hm(summary.latest_out_time),
            "target_time": format_hm(summary.target_time),
            "leave_hours": summary.leave_hours,
            "required_hours": summary.required_seconds / 3600,
            "worked": format_duration(summary.worked_seconds),
            "remaining": (
                "已达标"
                if summary.target_reached
                else (f"{remaining_min} 分钟" if summary.has_clock_in else "--")
            ),
            "status": (
                "已满应出勤"
                if summary.target_reached
                else (
                    f"未满应出勤 {summary.required_seconds / 3600:g}h"
                    if summary.has_clock_in
                    else "未打卡"
                )
            ),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    try:
        save_json_file(STATUS_PATH, payload)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("写入 status.json 失败: %s", exc)


def live_tick_summary(
    base: AttendanceSummary,
    now: Optional[datetime] = None,
) -> AttendanceSummary:
    """
    基于上次接口结果，用本地时钟重算工时/倒计时（不访问接口）。

    当日倒计时始终按「现在」推进；有效考勤提示若有下班卡则按打卡时段另算。

    @param base 接口返回的基准摘要（含上班时间、应出勤秒数）
    @param now 当前时间
    @return 刷新后的摘要副本
    @author Kai
    @date 2026/09/01 10:15
    """
    now = now or datetime.now()
    if not base.ok or base.in_time is None:
        return base

    required = max(0, int(base.required_seconds))
    # 当日倒计时逻辑不变：始终相对当前时间
    worked = max(0, int((now - base.in_time).total_seconds()))
    reached = worked >= required if required > 0 else True
    remaining = 0 if reached else max(0, required - worked)
    target_time = base.in_time + timedelta(seconds=required)

    # 有效性：有下班卡用打卡时段，否则跟倒计时一致
    if base.latest_out_time is not None:
        worked_for_validity = max(
            0, int((base.latest_out_time - base.in_time).total_seconds())
        )
    else:
        worked_for_validity = worked
    reached_for_validity = (
        worked_for_validity >= required if required > 0 else True
    )
    day = base.in_time.date()
    is_valid, tip = evaluate_attendance_validity(
        day=day,
        now=now,
        in_time=base.in_time,
        out_time=base.latest_out_time,
        in_status=base.in_status,
        out_status=base.out_status,
        daily_status=base.daily_status,
        target_reached=reached_for_validity,
        worked_seconds=worked_for_validity,
        required_seconds=required,
    )
    return replace(
        base,
        worked_seconds=worked,
        remaining_seconds=remaining,
        target_reached=reached,
        target_time=target_time,
        is_valid_attendance=is_valid,
        validity_tip=tip,
    )


def apply_leave_hours_to_summary(
    base: AttendanceSummary,
    leave_hours: float,
    now: Optional[datetime] = None,
) -> AttendanceSummary:
    """
    按新请假时长立刻重算应出勤与倒计时（不访问接口）。

    @param base 当前基准摘要
    @param leave_hours 今日请假小时
    @param now 当前时间
    @return 重算后的摘要
    @author Kai
    @date 2026/09/01 10:12
    """
    hours = max(0.0, float(leave_hours))
    required = effective_required_seconds(hours)
    patched = replace(base, leave_hours=hours, required_seconds=required)
    if not patched.ok or patched.in_time is None:
        return patched
    return live_tick_summary(patched, now)


def progress_tone(summary: AttendanceSummary) -> tuple[float, str]:
    """
    根据摘要计算进度与色调（托盘状态图标用）。

    @param summary 打卡摘要
    @return (progress 0~1, tone: normal/near/done/error)
    @author Kai
    @date 2026/07/24 16:55
    """
    from .display_strategy import orange_near_threshold

    required = max(1, summary.required_seconds or int(S.target_hours * 3600))
    if summary.error == "NON_WORKDAY":
        return 0.0, "normal"
    if summary.token_expired:
        return 0.0, "token"
    if not summary.ok:
        return 0.0, "error"
    if not summary.has_clock_in:
        return 0.0, "error"
    if summary.target_reached:
        return 1.0, "done"
    progress = min(1.0, summary.worked_seconds / required)
    mins = summary.remaining_seconds // 60
    tone = "near" if mins <= orange_near_threshold() else "normal"
    return progress, tone


def build_menu_status_text(summary: AttendanceSummary) -> str:
    """
    生成托盘菜单状态行（远离时弱化下班导向文案）。

    @param summary 打卡摘要
    @return 状态文案
    @author Kai
    @date 2026/07/24 16:55
    """
    from .display_strategy import show_countdown_ui

    if not summary.ok:
        return f"状态异常：{summary.error[:40]}"
    if not summary.has_clock_in:
        base = "今日状态：未打卡"
    elif summary.target_reached:
        req_h = (summary.required_seconds or int(S.target_hours * 3600)) / 3600
        base = f"今日状态：已满 {req_h:g} 小时"
    elif show_countdown_ui(summary.remaining_seconds):
        remain = summary.remaining_seconds // 60
        base = (
            f"今日打卡：{format_hm(summary.in_time)} / "
            f"可走 {format_hm(summary.target_time)} · 还差 {remain} 分钟"
        )
    else:
        # 远离下班：不强调倒计时
        base = f"今日状态：已打卡 {format_hm(summary.in_time)}"
    if summary.leave_hours > 0:
        base += f" · 假{summary.leave_hours:g}h"
    return base


def build_menu_secondary_text(summary: AttendanceSummary) -> str:
    """
    生成托盘菜单次要行（可走时间；临近时已并入主行则返回空）。

    @param summary 打卡摘要
    @return 次要文案，空串表示隐藏
    @author Kai
    @date 2026/07/24 16:55
    """
    from .display_strategy import show_countdown_ui

    if not summary.ok or not summary.has_clock_in:
        return ""
    if summary.target_reached:
        return f"可走时间：{format_hm(summary.target_time)}"
    if show_countdown_ui(summary.remaining_seconds):
        # 主行已含可走 / 还差
        return ""
    from .display_strategy import is_quiet_mode

    # 安静模式远离时不在菜单次要行强调可走时间
    if is_quiet_mode():
        return ""
    return f"可走时间：{format_hm(summary.target_time)}"


def build_tooltip(summary: AttendanceSummary) -> str:
    """
    生成简短托盘提示（详情见悬浮窗）。

    @param summary 打卡摘要
    @return tooltip 文案
    @author Kai
    @date 2026/07/24 16:55
    """
    from .display_strategy import show_countdown_ui

    leave_tip = f" · 假{summary.leave_hours:g}h" if summary.leave_hours > 0 else ""
    if not summary.ok:
        return f"{S.company_name} - {summary.error[:50]}"
    if not summary.has_clock_in:
        return f"{S.company_name} - 今日未打卡{leave_tip}"
    if summary.target_reached:
        return (
            f"{S.company_name} - 上班 {format_hm(summary.in_time)} "
            f"/ 已满应出勤{leave_tip}"
        )
    if show_countdown_ui(summary.remaining_seconds):
        return (
            f"{S.company_name} - 上班 {format_hm(summary.in_time)} "
            f"/ 可走 {format_hm(summary.target_time)} "
            f"/ 还差 {summary.remaining_seconds // 60} 分钟{leave_tip}"
        )
    # 远离：安静模式少写事实，临近/始终仍可提示上班。
    from .display_strategy import is_quiet_mode

    if is_quiet_mode():
        return f"{S.company_name} - 我在陪你{leave_tip}"
    return (
        f"{S.company_name} - 今日正常 · 上班 {format_hm(summary.in_time)}"
        f"{leave_tip}"
    )
