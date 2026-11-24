# Copyright (c) iGroup.
# All rights reserved.
"""
运行时配置：读取/保存 .env 与 config.json，支持设置弹窗热更新。

@author Kai
@date 2026/08/31 17:15
@description 敏感项写 .env，业务项写 config.json
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from dotenv import load_dotenv

from .paths import (
    CONFIG_EXAMPLE_FALLBACK,
    CONFIG_EXAMPLE_PATH,
    CONFIG_PATH,
    DEFAULT_CONFIG_JSON,
    ENV_PATH,
    LOG,
)


# 单日请假上限（小时）
MAX_LEAVE_HOURS = 8.0

# 开门请求头 deviceid（接口用，同事不用管）
DEFAULT_DOOR_DEVICE_ID = "uf0kU9ZcgfKrmTn8"
# 登录 deviceid。未登记时自动走短信安全验证
DEFAULT_LOGIN_DEVICE_ID = (
    "050309CD-F3D6-4F9E-AE03-729615B05E8A-73263-00002858645B11BC"
)
# 门禁序列号 deviceSerial（大家说的「开门 Device ID」）
DEFAULT_DOOR_SERIAL = "L40858918"

# 默认分级提醒节点（分钟）；0 = 已满应出勤
DEFAULT_REMIND_NODES = [60, 30, 20, 5, 0]

# 显示策略默认值（与 display_strategy 预设 near 一致）
DEFAULT_DISPLAY_MODE = "near"
DEFAULT_FAR_DISPLAY = "today_normal"

# 本地 AI / Agent 默认
DEFAULT_AI_BASE_URL = (
    "https://sh.igroupnet.com.cn:8443/ollama-api/v1/chat/completions"
)
DEFAULT_AI_MODEL = "qwen36-27b:latest"
DEFAULT_AI_AGENT_MAX_ROUNDS = 5
DEFAULT_AI_CHAT_CONTEXT = 20
DEFAULT_HOTKEY_CHAT = "Ctrl+Shift+A"
# AI 思考程度：none / low / medium / high
DEFAULT_AI_REASONING_EFFORT = "none"
AI_REASONING_EFFORTS = {"none", "low", "medium", "high"}
# 思考程度选项（值, 界面文案）
AI_REASONING_OPTIONS: tuple[tuple[str, str], ...] = (
    ("none", "关闭"),
    ("low", "低"),
    ("medium", "中"),
    ("high", "高"),
)
# 宠物短句后台润色默认不思考，避免被聊天框的高思考拖慢
DEFAULT_FUN_POLISH_REASONING = "none"

# 趣味默认
DEFAULT_FUN_PERSONA = "secretary"
DEFAULT_FUN_PET = "shiba"
# 人格短句 AI 润色刷新间隔（分钟）
DEFAULT_FUN_LINE_POLISH_MINUTES = 12
# 日常外卖提醒默认 10:40
DEFAULT_TAKEOUT_HOUR = 10
DEFAULT_TAKEOUT_MINUTE = 40
DEFAULT_TAKEOUT_TEXT = "该点外卖啦，别饿着干活～"


@dataclass
class AppSettings:
    """
    应用运行时配置（内存副本）。

    @author Kai
    @date 2026/07/24 16:55
    @description 供接口与 UI 统一读取；保存后可 reload
    """

    # --- .env 敏感项 ---
    attendance_token: str = ""
    # 海康登录账号。Token 失效时用来自动换票
    attendance_username: str = ""
    # 海康登录密码明文，只写在 .env
    attendance_password: str = ""
    # 已登记的登录 deviceid，与开门请求头不是同一个值
    login_device_id: str = ""
    # 登录后要进入的团队编号；空则用账号当前团队
    attendance_team_no: str = ""
    door_device_id: str = ""

    # --- config.json 业务项 ---
    company_name: str = "iGroup China"
    target_hours: float = 9.0
    near_minutes: int = 20
    # 分级提醒节点（分钟），含 0=已满
    remind_nodes_minutes: list[int] = field(
        default_factory=lambda: list(DEFAULT_REMIND_NODES)
    )
    # 到点后加班多久再提醒一次
    overtime_remind_minutes: int = 30
    # 显示策略：托盘/设置三档预设；倒计时露出由 display_mode + near_minutes 决定
    display_mode: str = DEFAULT_DISPLAY_MODE
    # 远离下班时详情：hidden / today_normal / clock_in / full
    far_display: str = DEFAULT_FAR_DISPLAY
    att_api: str = (
        "https://api.hikiot.com/api-attendance/v1/statistics/v2/"
        "individual/single/daily"
    )
    att_id: str = "myStatic"
    att_app_no: str = "UNI__89A1A02"
    door_api: str = (
        "https://api.hikiot.com/api-visual/v1/team/team-info/oneClickOpenDoor"
    )
    door_device_serial: str = "L40858918"
    door_app_no: str = "UNI__E32B021"
    door_authperm: str = "ACCESSSETUPFUN"
    # 已废弃：实际轮询用 low/high_freq_interval_seconds
    check_interval_seconds: int = 300
    # 尚未拉到上班卡时的轮询间隔（秒），默认 5 分钟
    low_freq_interval_seconds: int = 300
    # 保留兼容：下班卡不再轮询
    high_freq_interval_seconds: int = 60
    high_freq_start_hour: int = 12
    # 开始找上班卡的时刻（次日 7:00 再拉）
    clock_in_poll_hour: int = 7
    clock_in_poll_minute: int = 0
    remind_stop_hour: int = 20
    remind_stop_minute: int = 30
    door_cooldown_seconds: int = 10
    holiday_cache_hours: int = 12

    # --- AI / Agent ---
    ai_base_url: str = DEFAULT_AI_BASE_URL
    ai_model: str = DEFAULT_AI_MODEL
    ai_api_token: str = ""
    ai_enable: bool = True
    ai_enable_agent: bool = True
    ai_enable_chat: bool = True
    ai_enable_web_search: bool = False
    ai_enable_read_file: bool = False
    ai_agent_max_rounds: int = DEFAULT_AI_AGENT_MAX_ROUNDS
    ai_chat_context_messages: int = DEFAULT_AI_CHAT_CONTEXT
    # 对话模型思考程度；none 保持快速响应
    ai_reasoning_effort: str = DEFAULT_AI_REASONING_EFFORT
    # 聊天窗口是否置顶
    ai_chat_pin: bool = False
    # 聊天窗口几何（Qt saveGeometry 的 Base64）；空则用默认大小
    ai_chat_geometry: str = ""
    ai_file_whitelist_dirs: list[str] = field(default_factory=list)
    ai_search_endpoint: str = ""
    ai_search_api_key: str = ""
    hotkey_chat: str = DEFAULT_HOTKEY_CHAT

    # --- 趣味：宠物 / 人格 ---
    fun_enable: bool = True
    fun_pet_enable: bool = True
    fun_pet: str = DEFAULT_FUN_PET
    fun_persona: str = DEFAULT_FUN_PERSONA
    # 左键以海龟汤为主，旧冒险模式迁移为 puzzle；off 只看考勤。
    fun_card_mode: str = "puzzle"
    # 兼容既有冒险存档的出行方式，新版界面不再提供冒险入口。
    fun_trip_kind: str = "explore"
    # 保留旧冒险故事配置，不作为新版轻推理的开关。
    fun_story_ai: bool = True
    # 使用分类时长参与自然成长；关闭后海龟汤仍可独立使用。
    fun_usage_link: bool = True
    # 木鱼默认显示在宠物旁，声音默认关闭。
    fun_woodfish_enable: bool = True
    fun_woodfish_sound: bool = False
    # 带薪回血为可选娱乐估算，时薪由用户手动填写。
    fun_salary_enable: bool = False
    fun_hourly_rate: float = 0.0
    # 默认计入摸鱼和休息，未分类需主动选择。
    fun_salary_slack: bool = True
    fun_salary_rest: bool = True
    fun_salary_unknown: bool = False
    # 人格短句后台润色刷新间隔（分钟）
    fun_line_polish_minutes: int = DEFAULT_FUN_LINE_POLISH_MINUTES
    # 宠物短句润色思考程度，与聊天框独立
    fun_polish_reasoning_effort: str = DEFAULT_FUN_POLISH_REASONING

    # --- 日常：定点外卖提醒 ---
    takeout_remind_enable: bool = True
    takeout_remind_hour: int = DEFAULT_TAKEOUT_HOUR
    takeout_remind_minute: int = DEFAULT_TAKEOUT_MINUTE
    takeout_remind_text: str = DEFAULT_TAKEOUT_TEXT

    # 原始 config 字典，保存时保留未知字段
    raw_config: dict[str, Any] = field(default_factory=dict)


# 全局单例：业务代码统一读 S
S = AppSettings()


def normalize_hourly_rate(raw: Any) -> float:
    """
    规范化手动时薪，防止非法数值影响设置或金额绘制。

    @param raw 配置中的原始时薪，单位元/小时
    @return 0 至 1000000 的有限时薪，非法输入回落为零
    @author Kai
    @date 2026/10/15 16:16
    """
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return min(1000000.0, max(0.0, value)) if math.isfinite(value) else 0.0


def ensure_config_file() -> None:
    """
    若缺少 config.json，则从 example / 内置默认生成。

    @author Kai
    @date 2026/07/23 15:35
    """
    if CONFIG_PATH.exists():
        return
    for src in (CONFIG_EXAMPLE_PATH, CONFIG_EXAMPLE_FALLBACK):
        if src.exists():
            CONFIG_PATH.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            LOG.info("已从 %s 生成 config.json", src.name)
            return
    CONFIG_PATH.write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
    LOG.info("已写入内置默认 config.json")


def load_config_dict() -> dict[str, Any]:
    """
    读取 config.json。

    @return 配置字典
    @author Kai
    @date 2026/07/23 15:25
    """
    ensure_config_file()
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def has_attendance_login() -> bool:
    """
    是否可以用账号密码自动获取打卡 Token。

    @return 已配置账号和密码时返回 True
    @author Kai
    @date 2026/11/20 09:31
    """
    return bool((S.attendance_username or "").strip() and (S.attendance_password or "").strip())


def normalize_token(raw: str) -> str:
    """
    规范化 Token：去掉首尾空白，以及误粘贴的 Bearer 前缀。

    @param raw 用户输入或请求头原值
    @return 纯 Token
    @author Kai
    @date 2026/07/23 16:20
    """
    token = (raw or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def reload_settings() -> AppSettings:
    """
    从磁盘重新加载 .env + config.json 到全局 S。

    @return 更新后的 AppSettings
    @author Kai
    @date 2026/07/23 15:25
    """
    load_dotenv(ENV_PATH, override=True)
    cfg = load_config_dict()
    att = cfg.get("attendance", {}) or {}
    door = cfg.get("door", {}) or {}

    S.attendance_token = normalize_token(os.getenv("ATTENDANCE_TOKEN") or "")
    S.attendance_username = (os.getenv("ATTENDANCE_USERNAME") or "").strip()
    S.attendance_password = (os.getenv("ATTENDANCE_PASSWORD") or "").strip()
    S.login_device_id = (
        (os.getenv("ATTENDANCE_LOGIN_DEVICE_ID") or "").strip()
        or DEFAULT_LOGIN_DEVICE_ID
    )
    S.attendance_team_no = (os.getenv("ATTENDANCE_TEAM_NO") or "").strip()
    # 请求头 deviceid：固定默认，一般不改
    S.door_device_id = (
        (os.getenv("DOOR_DEVICE_ID") or "").strip() or DEFAULT_DOOR_DEVICE_ID
    )

    S.company_name = str(cfg.get("company_name", "iGroup China"))
    S.target_hours = float(cfg.get("target_hours", 9))
    S.near_minutes = int(cfg.get("near_minutes", 20))
    nodes_raw = cfg.get("remind_nodes_minutes", DEFAULT_REMIND_NODES)
    try:
        S.remind_nodes_minutes = sorted(
            {int(x) for x in list(nodes_raw)}, reverse=True
        )
    except Exception:  # noqa: BLE001
        S.remind_nodes_minutes = list(DEFAULT_REMIND_NODES)
    S.overtime_remind_minutes = int(cfg.get("overtime_remind_minutes", 30))
    # 延迟导入，避免与 display_strategy 循环依赖
    from .display_strategy import (
        infer_display_mode,
        normalize_display_mode,
        normalize_far_display,
    )

    S.far_display = normalize_far_display(
        str(cfg.get("far_display", DEFAULT_FAR_DISPLAY))
    )
    if "display_mode" in cfg:
        S.display_mode = normalize_display_mode(str(cfg.get("display_mode")))
    else:
        # 旧配置无 display_mode：按远离样式反推
        S.display_mode = infer_display_mode(S.far_display)
    S.att_api = str(
        att.get(
            "api_base",
            "https://api.hikiot.com/api-attendance/v1/statistics/v2/"
            "individual/single/daily",
        )
    )
    S.att_id = str(att.get("id", "myStatic"))
    S.att_app_no = str(att.get("app_no", "UNI__89A1A02"))
    S.door_api = str(
        door.get(
            "api",
            "https://api.hikiot.com/api-visual/v1/team/"
            "team-info/oneClickOpenDoor",
        )
    )
    S.door_device_serial = str(
        door.get("device_serial") or DEFAULT_DOOR_SERIAL
    ) or DEFAULT_DOOR_SERIAL
    S.door_app_no = str(door.get("app_no", "UNI__E32B021"))
    S.door_authperm = str(door.get("authperm", "ACCESSSETUPFUN"))
    S.low_freq_interval_seconds = int(cfg.get("low_freq_interval_seconds", 300))
    S.high_freq_interval_seconds = int(cfg.get("high_freq_interval_seconds", 60))
    S.high_freq_start_hour = int(cfg.get("high_freq_start_hour", 12))
    S.clock_in_poll_hour = int(cfg.get("clock_in_poll_hour", 7))
    S.clock_in_poll_minute = int(cfg.get("clock_in_poll_minute", 0))
    S.remind_stop_hour = int(cfg.get("remind_stop_hour", 20))
    S.remind_stop_minute = int(cfg.get("remind_stop_minute", 30))
    S.door_cooldown_seconds = int(cfg.get("door_cooldown_seconds", 10))
    S.holiday_cache_hours = int(cfg.get("holiday_cache_hours", 12))

    # AI 段
    ai = cfg.get("ai", {}) or {}
    S.ai_base_url = str(ai.get("base_url") or DEFAULT_AI_BASE_URL).strip()
    S.ai_model = str(ai.get("model") or DEFAULT_AI_MODEL).strip()
    S.ai_api_token = normalize_token(os.getenv("AI_API_TOKEN") or "")
    S.ai_enable = bool(ai.get("enable_ai", True))
    S.ai_enable_agent = bool(ai.get("enable_agent", True))
    S.ai_enable_chat = bool(ai.get("enable_chat", True))
    S.ai_enable_web_search = bool(ai.get("enable_web_search", False))
    S.ai_enable_read_file = bool(ai.get("enable_read_file", False))
    S.ai_agent_max_rounds = int(
        ai.get("agent_max_rounds", DEFAULT_AI_AGENT_MAX_ROUNDS)
    )
    S.ai_chat_context_messages = int(
        ai.get("chat_context_messages", DEFAULT_AI_CHAT_CONTEXT)
    )
    S.ai_reasoning_effort = normalize_reasoning_effort(ai.get("reasoning_effort"))
    S.ai_chat_pin = bool(ai.get("chat_pin", False))
    S.ai_chat_geometry = str(ai.get("chat_geometry") or "").strip()
    dirs_raw = ai.get("file_whitelist_dirs") or []
    if isinstance(dirs_raw, str):
        dirs_raw = [x.strip() for x in dirs_raw.replace(";", "\n").splitlines()]
    S.ai_file_whitelist_dirs = [
        str(x).strip() for x in list(dirs_raw) if str(x).strip()
    ]
    S.ai_search_endpoint = str(ai.get("search_endpoint") or "").strip()
    S.ai_search_api_key = (os.getenv("SEARCH_API_KEY") or "").strip()
    S.hotkey_chat = str(ai.get("hotkey_chat") or DEFAULT_HOTKEY_CHAT).strip()

    fun = cfg.get("fun", {}) or {}
    S.fun_enable = bool(fun.get("enable", True))
    S.fun_pet_enable = bool(fun.get("pet_enable", True))
    S.fun_pet = str(fun.get("pet") or DEFAULT_FUN_PET).strip()
    S.fun_persona = str(fun.get("persona") or DEFAULT_FUN_PERSONA).strip()
    card_mode = str(fun.get("card_mode") or "puzzle")
    S.fun_card_mode = "off" if card_mode == "off" else "puzzle"
    trip_kind = str(fun.get("trip_kind") or "explore")
    S.fun_trip_kind = trip_kind if trip_kind in {"stall", "explore", "shop"} else "explore"
    S.fun_story_ai = bool(fun.get("story_ai", True))
    S.fun_usage_link = bool(fun.get("usage_link", True))
    S.fun_woodfish_enable = bool(fun.get("woodfish_enable", True))
    S.fun_woodfish_sound = bool(fun.get("woodfish_sound", False))
    S.fun_salary_enable = bool(fun.get("salary_enable", False))
    S.fun_hourly_rate = normalize_hourly_rate(fun.get("hourly_rate", 0))
    S.fun_salary_slack = bool(fun.get("salary_slack", True))
    S.fun_salary_rest = bool(fun.get("salary_rest", True))
    S.fun_salary_unknown = bool(fun.get("salary_unknown", False))
    polish_mins = int(
        fun.get("line_polish_minutes", DEFAULT_FUN_LINE_POLISH_MINUTES)
    )
    S.fun_line_polish_minutes = max(5, min(180, polish_mins))
    S.fun_polish_reasoning_effort = normalize_reasoning_effort(
        fun.get("polish_reasoning_effort", DEFAULT_FUN_POLISH_REASONING)
    )

    takeout = cfg.get("takeout_remind", {}) or {}
    S.takeout_remind_enable = bool(takeout.get("enable", True))
    S.takeout_remind_hour = max(
        0, min(23, int(takeout.get("hour", DEFAULT_TAKEOUT_HOUR)))
    )
    S.takeout_remind_minute = max(
        0, min(59, int(takeout.get("minute", DEFAULT_TAKEOUT_MINUTE)))
    )
    S.takeout_remind_text = str(
        takeout.get("text") or DEFAULT_TAKEOUT_TEXT
    ).strip() or DEFAULT_TAKEOUT_TEXT

    S.raw_config = cfg
    return S


def read_env_map() -> dict[str, str]:
    """
    读取当前 .env 键值（不存在的键返回空串）。

    @return 环境变量字典
    @author Kai
    @date 2026/07/23 15:25
    """
    load_dotenv(ENV_PATH, override=True)
    keys = (
        "ATTENDANCE_TOKEN",
        "ATTENDANCE_USERNAME",
        "ATTENDANCE_PASSWORD",
        "ATTENDANCE_LOGIN_DEVICE_ID",
        "ATTENDANCE_TEAM_NO",
        "DOOR_DEVICE_ID",
        "AI_API_TOKEN",
        "SEARCH_API_KEY",
    )
    return {k: (os.getenv(k) or "").strip() for k in keys}


def save_env_map(values: dict[str, str]) -> None:
    """
    写入 .env（账号、Token、开门 deviceid、AI Token）。

    @param values 要写入的键值
    @author Kai
    @date 2026/11/20 09:31
    """
    # 合并已有值，避免漏写未在表单展示的键
    current = read_env_map()
    current.update({k: (v or "").strip() for k, v in values.items()})
    token = normalize_token(current.get("ATTENDANCE_TOKEN", ""))
    username = (current.get("ATTENDANCE_USERNAME") or "").strip()
    password = (current.get("ATTENDANCE_PASSWORD") or "").strip()
    login_device = (
        (current.get("ATTENDANCE_LOGIN_DEVICE_ID") or "").strip()
        or DEFAULT_LOGIN_DEVICE_ID
    )
    team_no = (current.get("ATTENDANCE_TEAM_NO") or "").strip()
    door_id = (current.get("DOOR_DEVICE_ID") or "").strip() or DEFAULT_DOOR_DEVICE_ID
    ai_token = normalize_token(current.get("AI_API_TOKEN", ""))
    search_key = (current.get("SEARCH_API_KEY") or "").strip()
    lines = [
        "# AttendanceHelper 敏感配置（由设置弹窗生成，请勿提交到 Git）",
        "",
        "# 打卡查询与开门共用同一 Token（不要带 Bearer 前缀）",
        f"ATTENDANCE_TOKEN={token}",
        "",
        "# 海康账号。Token 失效时按网页登录同一套加密自动换票",
        f"ATTENDANCE_USERNAME={username}",
        f"ATTENDANCE_PASSWORD={password}",
        f"ATTENDANCE_LOGIN_DEVICE_ID={login_device}",
        f"ATTENDANCE_TEAM_NO={team_no}",
        "",
        "# 开门请求头 deviceid（接口用，一般不用改）",
        f"DOOR_DEVICE_ID={door_id}",
        "",
        "# 本地 Ollama / AI 网关 Authorization Token",
        f"AI_API_TOKEN={ai_token}",
        "",
        "# 可选：搜网 API Key",
        f"SEARCH_API_KEY={search_key}",
        "",
    ]
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    LOG.info("已保存 .env")


def save_config_dict(updates: dict[str, Any]) -> None:
    """
    合并写入 config.json。

    @param updates 顶层字段更新（可含 attendance/door/ai/fun/takeout_remind 子字典）
    @author Kai
    @date 2026/08/06 10:58
    """
    cfg = load_config_dict()
    for key, value in updates.items():
        if key in ("attendance", "door", "ai", "fun", "takeout_remind") and isinstance(
            value, dict
        ):
            nested = dict(cfg.get(key) or {})
            nested.update(value)
            cfg[key] = nested
        else:
            cfg[key] = value
    # 已移除功能的残留字段
    cfg.pop("show_dashboard", None)
    cfg.pop("countdown_within_minutes", None)
    cfg.pop("check_interval_seconds", None)
    fun_cfg = cfg.get("fun")
    if isinstance(fun_cfg, dict):
        for stale in (
            "ritual_enable",
            "ritual_theme",
            "ritual_ms",
            "quiet_after_ritual",
        ):
            fun_cfg.pop(stale, None)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(CONFIG_PATH)
    LOG.info("已保存 config.json")


def normalize_reasoning_effort(value: Any) -> str:
    """
    规范化思考程度。

    @param value 配置或界面传入值
    @return none / low / medium / high
    @author Kai
    @date 2026/09/01 10:30
    """
    text = str(value or "").strip().lower()
    if text in AI_REASONING_EFFORTS:
        return text
    return DEFAULT_AI_REASONING_EFFORT


def persist_ai_reasoning_effort(effort: str) -> str:
    """
    将聊天框选择的思考程度写入内存并落盘（不影响宠物短句）。

    @param effort none / low / medium / high
    @return 实际生效的思考程度
    @author Kai
    @date 2026/09/01 10:30
    """
    value = normalize_reasoning_effort(effort)
    S.ai_reasoning_effort = value
    save_config_dict({"ai": {"reasoning_effort": value}})
    return value


def persist_chat_window_state(
    *,
    pin: Optional[bool] = None,
    geometry: Optional[str] = None,
) -> None:
    """
    记住聊天窗口置顶开关与大小位置。

    @param pin 是否置顶；None 表示不改
    @param geometry Qt saveGeometry 的 Base64；None 表示不改
    @author Kai
    @date 2026/09/01 10:30
    """
    updates: dict[str, Any] = {}
    if pin is not None:
        S.ai_chat_pin = bool(pin)
        updates["chat_pin"] = S.ai_chat_pin
    if geometry is not None:
        S.ai_chat_geometry = str(geometry or "").strip()
        updates["chat_geometry"] = S.ai_chat_geometry
    if updates:
        save_config_dict({"ai": updates})


# 启动时加载一次
reload_settings()
