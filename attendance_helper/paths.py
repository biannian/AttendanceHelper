# Copyright (c) iGroup.
# All rights reserved.
"""
路径与日志（支持 PyInstaller 单文件打包）。

@author Kai
@date 2026/07/23 15:35
@description 运行时数据写在 exe 旁；内置资源从 _MEIPASS 读取；启动时持久化 TLS CA 证书
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def is_frozen() -> bool:
    """是否为打包后的可执行文件。"""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """
    用户数据根目录（.env / config.json / logs）。

    开发：windows/；打包：exe 所在目录。

    @return 根路径
    @author Kai
    @date 2026/07/23 15:35
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """
    只读内置资源目录（config.example.json 等）。

    @return 资源路径
    @author Kai
    @date 2026/07/23 15:35
    """
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


ROOT = app_root()
RESOURCE_ROOT = resource_root()
CONFIG_PATH = ROOT / "config.json"
CONFIG_EXAMPLE_PATH = RESOURCE_ROOT / "config.example.json"
# 开发时也可用 windows/config.example.json 作为回退
CONFIG_EXAMPLE_FALLBACK = app_root() / "config.example.json"
CACHE_PATH = ROOT / "cache.json"
STATUS_PATH = ROOT / "status.json"
# 历史打卡按日缓存，避免周/月/对话工具重复打接口
ATT_CACHE_PATH = ROOT / "attendance_cache.json"
# AI 事项 / 对话 / 成就统一库
DB_PATH = ROOT / "helper.db"
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "app.log"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36"
)

# 内置默认 config，防止打包漏带 example 时无法启动
DEFAULT_CONFIG_JSON = """{
  "target_hours": 9,
  "near_minutes": 20,
  "remind_nodes_minutes": [60, 30, 20, 5, 0],
  "overtime_remind_minutes": 30,
  "display_mode": "near",
  "far_display": "today_normal",
  "company_name": "iGroup China",
  "attendance": {
    "api_base": "https://api.hikiot.com/api-attendance/v1/statistics/v2/individual/single/daily",
    "id": "myStatic",
    "app_no": "UNI__89A1A02"
  },
  "door": {
    "api": "https://api.hikiot.com/api-visual/v1/team/team-info/oneClickOpenDoor",
    "device_serial": "L40858918",
    "app_no": "UNI__E32B021",
    "authperm": "ACCESSSETUPFUN"
  },
  "low_freq_interval_seconds": 300,
  "high_freq_interval_seconds": 60,
  "high_freq_start_hour": 12,
  "clock_in_poll_hour": 7,
  "clock_in_poll_minute": 0,
  "remind_stop_hour": 20,
  "remind_stop_minute": 30,
  "door_cooldown_seconds": 10,
  "holiday_cache_hours": 12,
  "ai": {
    "base_url": "https://sh.igroupnet.com.cn:8443/ollama-api/v1/chat/completions",
    "model": "qwen36-27b:latest",
    "reasoning_effort": "none",
    "enable_ai": true,
    "enable_agent": true,
    "enable_chat": true,
    "enable_web_search": false,
    "enable_read_file": false,
    "agent_max_rounds": 5,
    "chat_context_messages": 20,
    "file_whitelist_dirs": [],
    "search_endpoint": "",
    "hotkey_chat": "Ctrl+Shift+A",
    "chat_pin": false
  }
}
"""


def setup_logger() -> logging.Logger:
    """
    初始化滚动日志。

    @return 应用日志器
    @author Kai
    @date 2026/07/23 15:35
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("AttendanceHelper")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=512 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)
    return logger


LOG = setup_logger()

# 打包单文件后尽早把 certifi 证书拷出 Temp，避免托盘常驻时被系统清掉
try:
    from attendance_helper.ssl_certs import ensure_ca_bundle

    ensure_ca_bundle()
except Exception as exc:  # noqa: BLE001
    LOG.warning("初始化 TLS CA 证书失败: %s", exc)

