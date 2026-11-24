# Copyright (c) iGroup China.
# All rights reserved.
"""
前台软件归类。

@author Kai
@date 2026/09/29 15:12
@description 进程名与站点关键字决定工作/摸鱼/未分类；窗口标题只参与匹配，不进入结果
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# 归类：工作、摸鱼、未分类、休息
CAT_WORK = "work"
CAT_SLACK = "slack"
CAT_UNKNOWN = "unknown"
CAT_REST = "rest"

CAT_LABELS: dict[str, str] = {
    CAT_WORK: "工作",
    CAT_SLACK: "摸鱼",
    CAT_UNKNOWN: "未分类",
    CAT_REST: "休息",
}

# 休息记账用的固定键，不代表某个软件
REST_APP_KEY = "rest:idle"
REST_DISPLAY_NAME = "休息"

# 无鼠标键盘操作达到该秒数后，后续时间记为休息
IDLE_REST_SECONDS = 60
# 间隔不超过这个值时，仍记在当前前台软件上（挡住定时器偶发变慢）
ACTIVE_HOLD_SECONDS = 120.0
# 一次断档超过这个值视为没在观测（过夜睡眠），整段不补
MAX_TRACK_GAP_SECONDS = 4 * 3600.0

# 这些前台窗口不是用户在用的软件
_SKIP_EXES = {
    "dwm.exe",
    "searchhost.exe",
    "searchapp.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "textinputhost.exe",
    "runtimebroker.exe",
    "sihost.exe",
    "applicationframehost.exe",
    "pickerhost.exe",
    "systemsettings.exe",
}

# 锁屏界面
_LOCK_EXES = {
    "lockapp.exe",
    "logonui.exe",
}

# 浏览器：未命中站点时整段记在浏览器上，归类保持未分类
BROWSER_NAMES: dict[str, str] = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "360chrome.exe": "360 极速浏览器",
    "360se.exe": "360 安全浏览器",
    "qqbrowser.exe": "QQ 浏览器",
    "sogouexplorer.exe": "搜狗浏览器",
    "arc.exe": "Arc",
}

# 站点关键字（写在窗口标题里）。命中后只保留站点，不保留标题原文。
# (关键字, app_key, 显示名, 默认归类)
_SITE_KEYWORDS: tuple[tuple[str, str, str, str], ...] = (
    ("bilibili", "site:bilibili", "哔哩哔哩", CAT_SLACK),
    ("哔哩哔哩", "site:bilibili", "哔哩哔哩", CAT_SLACK),
    ("youtube", "site:youtube", "YouTube", CAT_SLACK),
    ("netflix", "site:netflix", "Netflix", CAT_SLACK),
    ("twitch", "site:twitch", "Twitch", CAT_SLACK),
    ("douyu.com", "site:douyu", "斗鱼", CAT_SLACK),
    ("斗鱼", "site:douyu", "斗鱼", CAT_SLACK),
    ("huya.com", "site:huya", "虎牙", CAT_SLACK),
    ("虎牙", "site:huya", "虎牙", CAT_SLACK),
    ("iqiyi", "site:iqiyi", "爱奇艺", CAT_SLACK),
    ("爱奇艺", "site:iqiyi", "爱奇艺", CAT_SLACK),
    ("youku", "site:youku", "优酷", CAT_SLACK),
    ("优酷", "site:youku", "优酷", CAT_SLACK),
    ("v.qq.com", "site:vqq", "腾讯视频", CAT_SLACK),
    ("腾讯视频", "site:vqq", "腾讯视频", CAT_SLACK),
    ("douyin", "site:douyin", "抖音", CAT_SLACK),
    ("抖音", "site:douyin", "抖音", CAT_SLACK),
    ("tiktok", "site:tiktok", "TikTok", CAT_SLACK),
    ("reddit", "site:reddit", "Reddit", CAT_SLACK),
    ("music.163.com", "site:netease-music", "网易云音乐", CAT_SLACK),
    ("y.qq.com", "site:qqmusic", "QQ 音乐", CAT_SLACK),
    ("open.spotify.com", "site:spotify", "Spotify", CAT_SLACK),
    ("github", "site:github", "GitHub", CAT_WORK),
    ("gitlab", "site:gitlab", "GitLab", CAT_WORK),
    ("stackoverflow", "site:stackoverflow", "Stack Overflow", CAT_WORK),
    ("localhost", "site:localhost", "本地页面", CAT_WORK),
    ("office.com", "site:office", "Microsoft 365", CAT_WORK),
    ("sharepoint.com", "site:sharepoint", "SharePoint", CAT_WORK),
    ("office365.com", "site:office365", "Microsoft 365", CAT_WORK),
)

# 常见桌面程序的默认归类。不在表内的记为未分类，等用户自己标。
_PROCESS_DEFAULTS: dict[str, tuple[str, str]] = {
    "winword.exe": ("Word", CAT_WORK),
    "excel.exe": ("Excel", CAT_WORK),
    "powerpnt.exe": ("PowerPoint", CAT_WORK),
    "outlook.exe": ("Outlook", CAT_WORK),
    "olk.exe": ("Outlook", CAT_WORK),
    "onenote.exe": ("OneNote", CAT_WORK),
    "notepad.exe": ("记事本", CAT_WORK),
    "notepad++.exe": ("Notepad++", CAT_WORK),
    "devenv.exe": ("Visual Studio", CAT_WORK),
    "code.exe": ("VS Code", CAT_WORK),
    "cursor.exe": ("Cursor", CAT_WORK),
    "idea64.exe": ("IntelliJ IDEA", CAT_WORK),
    "pycharm64.exe": ("PyCharm", CAT_WORK),
    "windowsterminal.exe": ("终端", CAT_WORK),
    "wt.exe": ("终端", CAT_WORK),
    "powershell.exe": ("PowerShell", CAT_WORK),
    "pwsh.exe": ("PowerShell", CAT_WORK),
    "cmd.exe": ("命令提示符", CAT_WORK),
    "wxwork.exe": ("企业微信", CAT_WORK),
    "dingtalk.exe": ("钉钉", CAT_WORK),
    "feishu.exe": ("飞书", CAT_WORK),
    "lark.exe": ("飞书", CAT_WORK),
    "teams.exe": ("Teams", CAT_WORK),
    "ms-teams.exe": ("Teams", CAT_WORK),
    "notion.exe": ("Notion", CAT_WORK),
    "steam.exe": ("Steam", CAT_SLACK),
    "steamwebhelper.exe": ("Steam", CAT_SLACK),
    "wegame.exe": ("WeGame", CAT_SLACK),
    "epicgameslauncher.exe": ("Epic", CAT_SLACK),
    "battle.net.exe": ("战网", CAT_SLACK),
    "cloudmusic.exe": ("网易云音乐", CAT_SLACK),
    "qqmusic.exe": ("QQ 音乐", CAT_SLACK),
    "spotify.exe": ("Spotify", CAT_SLACK),
    "kugou.exe": ("酷狗音乐", CAT_SLACK),
    "kwmusic.exe": ("酷我音乐", CAT_SLACK),
    "potplayer.exe": ("PotPlayer", CAT_SLACK),
    "potplayermini64.exe": ("PotPlayer", CAT_SLACK),
    "vlc.exe": ("VLC", CAT_SLACK),
    "douyin.exe": ("抖音", CAT_SLACK),
}

_SITE_CATEGORY: dict[str, str] = {
    app_key: category for _, app_key, _, category in _SITE_KEYWORDS
}


@dataclass(frozen=True)
class ActivityIdentity:
    """
    可入库的一条使用身份。

    @author Kai
    @date 2026/09/29 15:12
    @description 只含稳定键和显示名，不含窗口标题
    """

    # 入库主键：exe: 或 site: 或 rest:
    app_key: str
    # 界面上的软件或站点名
    display_name: str
    # 没有手动规则时的归类
    default_category: str


def clip_delta(delta: float) -> float:
    """
    丢掉非正或长到无法观测的采样间隔。

    @param delta 距上次采样的秒数
    @return 可计入的秒数；过夜断档为 0
    @author Kai
    @date 2026/09/29 15:52
    """
    if delta <= 0 or delta > MAX_TRACK_GAP_SECONDS:
        return 0.0
    return float(delta)


def is_rest_moment(locked: bool, idle_seconds: float) -> bool:
    """
    当前是否应记为休息。

    @param locked 是否锁屏
    @param idle_seconds 距上次鼠标或键盘操作的秒数
    @return 锁屏或发呆达到阈值时为 True
    @author Kai
    @date 2026/09/29 15:12
    """
    if locked:
        return True
    return float(idle_seconds) >= IDLE_REST_SECONDS


def needs_window_title(exe: str) -> bool:
    """
    是否需要读窗口标题才能归类。

    @param exe 进程文件名
    @return 浏览器要识别站点，资源管理器要区分桌面
    @author Kai
    @date 2026/09/29 15:12
    """
    lower = (exe or "").casefold()
    return lower in BROWSER_NAMES or lower == "explorer.exe"


def default_category_for(app_key: str) -> str:
    """
    按内置名单取默认归类。

    @param app_key 使用记录键
    @return work / slack / unknown / rest
    @author Kai
    @date 2026/09/29 15:12
    """
    if app_key == REST_APP_KEY:
        return CAT_REST
    if app_key.startswith("site:"):
        return _SITE_CATEGORY.get(app_key, CAT_UNKNOWN)
    if app_key.startswith("exe:"):
        exe = app_key[4:]
        preset = _PROCESS_DEFAULTS.get(exe)
        if preset is not None:
            return preset[1]
    return CAT_UNKNOWN


# 浏览器自己的页面，没有可归类的网站
_INTERNAL_ADDRESS_PREFIXES = (
    "about:",
    "blob:",
    "brave:",
    "chrome-devtools:",
    "chrome-extension:",
    "chrome-untrusted:",
    "chrome:",
    "data:",
    "devtools:",
    "edge-extension:",
    "edge:",
    "file:",
    "javascript:",
    "view-source:",
)


def host_from_address(raw: str) -> str:
    """
    从地址栏文本取出域名。路径、参数和标题一律丢掉。

    @param raw 地址栏原文，用完即弃
    @return 小写域名；搜索词或浏览器内部页返回空串
    @author Kai
    @date 2026/09/29 16:25
    """
    text = (raw or "").strip()
    if not text or any(char.isspace() for char in text):
        return ""
    lowered = text.casefold()
    if lowered.startswith(_INTERNAL_ADDRESS_PREFIXES):
        return ""
    if "://" not in text:
        head = text.split("/")[0].split(":")[0]
        if "." not in head and head.casefold() != "localhost":
            return ""
        text = "https://" + text
    host = (urlparse(text).hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    # 没有点的名字是浏览器内部页（如 devtools），不是网站
    if "." not in host and host != "localhost":
        return ""
    return host


def classify_foreground(
    exe: str,
    title: str,
    url: str = "",
) -> ActivityIdentity | None:
    """
    把前台进程归成一条使用身份。

    @param exe 进程文件名，如 Cursor.exe
    @param title 窗口标题；只用于站点或桌面判断，不会写进返回值
    @param url 浏览器地址栏；只取域名，路径和参数不写进返回值
    @return 身份；系统壳窗口返回 None
    @author Kai
    @date 2026/09/29 16:20
    """
    lower = (exe or "").strip().casefold()
    if not lower:
        return None
    if lower in _LOCK_EXES:
        return ActivityIdentity(REST_APP_KEY, REST_DISPLAY_NAME, CAT_REST)
    if lower in _SKIP_EXES:
        return None
    if lower == "explorer.exe":
        return _classify_explorer(title)
    if lower in BROWSER_NAMES:
        return _classify_browser(lower, title, url)
    display, category = _PROCESS_DEFAULTS.get(
        lower, (_friendly_exe_name(exe), CAT_UNKNOWN)
    )
    return ActivityIdentity(f"exe:{lower}", display, category)


def format_usage_duration(seconds: int) -> str:
    """
    把秒数收成菜单和表格用的短时长。

    @param seconds 累计秒
    @return 如 1小时5分、不到1分
    @author Kai
    @date 2026/09/29 15:12
    """
    seconds = max(0, int(seconds))
    if seconds <= 0:
        return "0分"
    if seconds < 60:
        return "不到1分"
    hours, minutes = divmod(seconds // 60, 60)
    if hours:
        return f"{hours}小时{minutes}分"
    return f"{minutes}分"


def _classify_explorer(title: str) -> ActivityIdentity | None:
    """
    桌面和任务视图不记账，文件夹窗口记为资源管理器。

    @param title 窗口标题，用完即弃
    @return 资源管理器身份；桌面返回 None
    @author Kai
    @date 2026/09/29 15:12
    """
    folded = (title or "").strip().casefold()
    if folded in {"", "program manager", "任务视图"}:
        return None
    return ActivityIdentity("exe:explorer.exe", "文件资源管理器", CAT_UNKNOWN)


def _classify_browser(exe_lower: str, title: str, url: str) -> ActivityIdentity:
    """
    浏览器先按地址栏域名归类，读不到地址再用标签标题。

    @param exe_lower 小写进程名
    @param title 窗口标题，用完即弃
    @param url 地址栏原文，用完即弃
    @return 站点或浏览器身份
    @author Kai
    @date 2026/09/29 16:20
    """
    host = host_from_address(url)
    if host:
        matched = _match_host(host)
        if matched is not None:
            app_key, display, category = matched
            return ActivityIdentity(app_key, display, category)
        return ActivityIdentity(f"site:{host}", host, CAT_UNKNOWN)
    matched = _match_site(title)
    if matched is not None:
        app_key, display, category = matched
        return ActivityIdentity(app_key, display, category)
    return ActivityIdentity(
        f"exe:{exe_lower}",
        BROWSER_NAMES[exe_lower],
        CAT_UNKNOWN,
    )


def _match_host(host: str) -> tuple[str, str, str] | None:
    """
    用域名匹配内置站点，避免短关键字串到别的网站上。

    @param host 小写域名
    @return (app_key, 显示名, 默认归类)；没有命中则为 None
    @author Kai
    @date 2026/09/29 16:20
    """
    best: tuple[str, str, str] | None = None
    best_len = 0
    for keyword, app_key, display, category in _SITE_KEYWORDS:
        needle = keyword.casefold().lstrip(".")
        if not _host_has(host, needle):
            continue
        if len(needle) > best_len:
            best = (app_key, display, category)
            best_len = len(needle)
    return best


def _host_has(host: str, needle: str) -> bool:
    """
    判断域名是否就是这个站点，或是它的子域。

    @param host 小写域名
    @param needle 关键字或域名
    @return 命中为 True
    @author Kai
    @date 2026/09/29 16:20
    """
    if host == needle or host.endswith("." + needle):
        return True
    if "." in needle:
        return False
    return needle in host.split(".")


def _match_site(title: str) -> tuple[str, str, str] | None:
    """
    在标题中找最长的站点关键字。

    @param title 窗口标题
    @return (app_key, 显示名, 默认归类)；没有命中则为 None
    @author Kai
    @date 2026/09/29 15:12
    """
    folded = (title or "").casefold()
    if not folded:
        return None
    best: tuple[str, str, str] | None = None
    best_len = 0
    for keyword, app_key, display, category in _SITE_KEYWORDS:
        needle = keyword.casefold()
        if needle in folded and len(needle) > best_len:
            best = (app_key, display, category)
            best_len = len(needle)
    return best


def _friendly_exe_name(exe: str) -> str:
    """
    没有预设名字时，用文件名（去掉扩展名）当显示名。

    @param exe 进程文件名
    @return 显示名
    @author Kai
    @date 2026/09/29 15:12
    """
    stem = Path(exe).stem.strip()
    return stem or exe
