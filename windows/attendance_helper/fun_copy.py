# Copyright (c) iGroup China.
# All rights reserved.
"""
趣味文案与提醒人格（只改表达，不改规则事实）。

@author Kai
@date 2026/08/31 17:20
@description 人格短句即宠物说话；两行是态度+包袱，不是无关碎碎念
"""

from __future__ import annotations

import json
import random
import re
import threading
from datetime import datetime
from typing import Any, Callable, Optional

from .attendance import AttendanceSummary
from .config import S
from .paths import LOG
from .util import format_duration, format_hm


# 提醒人格 id
PERSONA_SECRETARY = "secretary"
PERSONA_GENTLE = "gentle"
PERSONA_SARCASTIC = "sarcastic"
PERSONA_COACH = "coach"
PERSONA_ANCIENT = "ancient"
PERSONA_GAME = "game"

PERSONA_LABELS: dict[str, str] = {
    PERSONA_SECRETARY: "极简秘书",
    PERSONA_GENTLE: "温柔同事",
    PERSONA_SARCASTIC: "毒舌搭子",
    PERSONA_COACH: "热血教练",
    PERSONA_ANCIENT: "古风管家",
    PERSONA_GAME: "游戏系统",
}

OFF_WORK_BLESSINGS = [
    "辛苦了，剩下的留给明天。",
    "今天也是被工时放过的一天。",
    "封印解除，自由重启。",
    "包已背上，世界很大。",
    "下班快乐，记得补充水分。",
    "今日副本通关，掉落：平静。",
]

# 各人格口吻：给润色模型当说明书，禁止写成空洞陪伴
_PERSONA_VOICE: dict[str, str] = {
    PERSONA_SECRETARY: "冷、短、像贴在屏幕角上的便利贴。不撒娇，不喊加油。",
    PERSONA_GENTLE: "黏、具体、会动手。禁止「我陪你」「慢慢来」这种空话。",
    PERSONA_SARCASTIC: "工位对面的损友。只损眼前这人这工位，不讲大道理。",
    PERSONA_COACH: "短促、夸张，把工位当训练场，副句用假 Buff 抖包袱。",
    PERSONA_ANCIENT: "半文半白，把工位当府衙，副句用一个古人也会做的小动作。",
    PERSONA_GAME: "系统提示音。副句必须是假成就、掉落或隐藏任务。",
}

# 情境提示：告诉模型「现在该说什么」，尤其下午严禁催下班
_SITUATION_HINTS: dict[str, str] = {
    "non_workday": "今天不用上班，一起摆烂。",
    "token": "登录挂了，先修门。",
    "error": "信号糊了，别甩锅。",
    "no_in": "人到了还没打卡。",
    "done_out": "已经可以走了，开心收工。",
    "done_need_out": "工时够了，就差打下班卡。",
    "near": "快下班，拦住他开新活；可兴奋，不要报精确分钟。",
    "afternoon": "下午疲了想摸鱼，但还早。严禁催下班、报剩余时间。",
    "morning": "刚开工，人还没醒透。可损可哄，别倒计时。",
}

# 情境 → 各人格底稿：两行为「态度 + 包袱」（afternoon 不含倒计时）
_PERSONA_SITUATIONS: dict[str, dict[str, list[str]]] = {
    PERSONA_SECRETARY: {
        "non_workday": [
            "日历显示今日无议程。\n我先把工位收成午睡位。",
            "休息日，文件请自行休眠。\n便利贴写着：谁也别@我。",
        ],
        "token": [
            "通行令过期，我进不去系统。\n先更新登录，再装忙。",
            "门禁把我关外面了。\n你人可以忙，先把门打开。",
        ],
        "error": [
            "打卡消息没听清。\n我把耳朵贴到接口上了。",
            "信号糊成马赛克。\n稍等，我再拍一次。",
        ],
        "no_in": [
            "人到了，卡还没摸。\n我把打卡页置顶在你鼻子前。",
            "未签到，今日议程锁定。\n先点一下那个绿按钮。",
        ],
        "done_out": [
            "工时已结，可以离席。\n包我帮你看过拉链了。",
            "今日议程清空。\n电梯我先用眼神按好。",
        ],
        "done_need_out": [
            "工时够了，就差签退。\n系统还不知道你要溜。",
            "能走，先跟机器说一声。\n我把下班卡按钮描红了。",
        ],
        "near": [
            "收尾窗口已开，禁止新任务。\n鼠标我看管着，别点进文档。",
            "只处理能合上的事。\n新需求请排到不存在的明天。",
        ],
        "afternoon": [
            "下午只办能合上的事。\n新邮件先丢进「以后再说」。",
            "同一份表别再拉上拉下。\n我帮你点了保存，你去喝水。",
            "午后效率会掉，这是日历问题。\n我把待办拆成能咬动的一小口。",
            "群消息九成不用回。\n已读就好，我替你装忙。",
        ],
        "morning": [
            "今日第一件：先做最烦那桩。\n便利贴已贴你屏幕左上角。",
            "咖啡进喉咙之前别开会。\n我把日程往后拖了五分钟。",
            "收件箱不是今日主线。\n先合上一件，再谈英勇。",
        ],
    },
    PERSONA_GENTLE: {
        "non_workday": [
            "放假呀，枕头比工位香。\n我蜷成一团，你随便躺。",
            "休息日没有待办。\n爪子借你当遥控器垫。",
        ],
        "token": [
            "登录掉啦，进不去。\n抱抱，更新一下就能回来。",
            "门把我关外面了。\n你开一下，我马上贴过来。",
        ],
        "error": [
            "信号打结了，我靠着你歇。\n不是你的错，是线在闹脾气。",
            "打卡声我没听清。\n再等一小下，我把耳朵竖起来。",
        ],
        "no_in": [
            "人到了，卡也摸一下好不好。\n我把打卡页拱到你手指边。",
            "先打卡，我才敢开始趴班。\n绿按钮在闪，像在找你。",
        ],
        "done_out": [
            "可以回家啦，牵我走。\n你的包带我用牙叼过，没断。",
            "工时够了，今晚归你。\n我先去门口等电梯。",
        ],
        "done_need_out": [
            "满了满了，签退再溜呀。\n我帮你盯着那个确认键。",
            "能收工了，别让系统吃醋。\n打完卡我请你在门口深呼吸。",
        ],
        "near": [
            "就差临门这一下。\n我已经开始闻晚饭的味道了。",
            "别开新窗口，我们要溜。\n爪子压在你的发送键上了。",
        ],
        "afternoon": [
            "下午脑子会变慢，正常。\n我去把水杯拱到你手边。",
            "你盯屏幕太久了。\n眨眼一次，我数着。",
            "这封邮件没有你想的那么急。\n先伸个懒腰，我帮你占着工位。",
            "有人@你也先喝一口。\n回消息的事先借我五分钟。",
        ],
        "morning": [
            "你哈欠打得我都醒了。\n爪子借你垫腕，先点开那封最烦的。",
            "早呀，先把椅子坐热。\n咖啡凉了我提醒你，活我还不催。",
            "新的一天从合上一件开始。\n我趴键盘旁，当你的纸镇。",
        ],
    },
    PERSONA_SARCASTIC: {
        "non_workday": [
            "放假还打开电脑，病得不轻。\n我先把你的敬业心拔了。",
            "休息日装忙给谁看。\n日历都躺了，你也躺。",
        ],
        "token": [
            "Token 挂了还挺能演忙。\n先修门，再谈你的事业。",
            "授权过期，人可以装，我进不去。\n登录页在笑你。",
        ],
        "error": [
            "接口罢工，别甩锅给我。\n我又不是公司网线。",
            "信号糊成马赛克。\n你刷新十次也变不成领导。",
        ],
        "no_in": [
            "卡都没打就往里冲。\n勇气可嘉，记性另说。",
            "人到了系统还不认识你。\n先点那个绿的，再装忙。",
        ],
        "done_out": [
            "系统放过你了，走。\n加班英雄剧本今天杀青。",
            "满了，别再刷新待办装深沉。\n门在那，包也在那。",
        ],
        "done_need_out": [
            "能溜了还杵着，等颁奖吗。\n打卡，谢幕，谢谢。",
            "工时够了，系统比你清醒。\n签退，别让门等你。",
        ],
        "near": [
            "还敢点开新需求？\n鼠标我藏了，你找吧。",
            "最后这点别给自己加戏。\n新窗口一经发现就拖进回收站。",
        ],
        "afternoon": [
            "同一份表你拉了第三遍。\n它不会自己变好看，先存档。",
            "群里九成是已读不回。\n你回了也不会升职，喝口水。",
            "下午的会，闭眼也算出席。\n我负责在你打呼时装忙。",
            "你又把待办从顶拖到底。\n排序改变不了人生，先合一件。",
        ],
        "morning": [
            "咖啡还没进喉咙就开始开会。\n勇气可嘉，脑子另说。",
            "收件箱不是今日副本。\n先干掉最烦那封，再刷存在感。",
            "你打开电脑的声音有点英勇。\n英勇完请先打那件不想做的。",
        ],
    },
    PERSONA_COACH: {
        "non_workday": [
            "休息日也是训练日：躺平！\n恢复组，我给你计时。",
            "非工作日 Buff：禁止打开邮箱！\n我守着，谁敢@你谁加跑。",
        ],
        "token": [
            "掉线了！先重连再作战！\n补给箱就在登录页！",
            "Token 失效，立即回城！\n没有通行证别冲塔！",
        ],
        "error": [
            "信号不稳，调整呼吸再上！\n我们不散，网线先散。",
            "短暂失联，保持站姿！\n刷新是热身，不是放弃！",
        ],
        "no_in": [
            "先打卡，今日训练才开始！\n绿按钮就是发令枪！",
            "人到场了，系统还没点名！\n打卡，然后我们冲第一件！",
        ],
        "done_out": [
            "通关！带我撤离现场！\n今日掉落：自由，以及我。",
            "目标达成，漂亮！\n冷却开始，禁止加练！",
        ],
        "done_need_out": [
            "工时完成，结算打卡！\n不签退算弃权，听见没！",
            "达标了！离场动作：点那一下！\n我已经在哼胜利曲！",
        ],
        "near": [
            "最后一波，禁止开新怪！\n通关 BGM 我已经在哼了！",
            "临门一脚，收着点！\n新任务一律判定越位！",
        ],
        "afternoon": [
            "午后掉血正常，节奏别散！\n拉伸也算一组，我给你数！",
            "下午输出靠质量不靠刷新！\n合上一件，Buff 叠一层！",
            "疲了就换小目标！\n工位是训练场，不是刑场！",
            "别跟邮件死磕到抽筋！\n先清当前这组，再谈加练！",
        ],
        "morning": [
            "今日训练：先攻最硬那一件！\n我在你肩膀上叠攻击 Buff！",
            "热身完毕，邮箱先别当主线！\n第一组，现在开始！",
            "新的一天从专注开练！\n哈欠算热身，下一秒进入状态！",
        ],
    },
    PERSONA_ANCIENT: {
        "non_workday": [
            "今日休沐，印信收起。\n我在蒲团打盹，少侠且躺。",
            "非工作日，公务请改日再参。\n茶凉了也不催，这叫养生。",
        ],
        "token": [
            "令牌已失，门不开。\n请再请令，再谈朝会。",
            "门禁不通，须再通禀。\n少侠先过门，我才好随侍。",
        ],
        "error": [
            "天机未明，我且侧耳。\n不是你的错，是线在闹玄。",
            "信号不稳，稍候片时。\n刷新十次也不成仙。",
        ],
        "no_in": [
            "人到公门，尚未签到。\n绿钮一触，今日才算入衙。",
            "请先打卡，再办正事。\n我在门口候着，风有点大。",
        ],
        "done_out": [
            "时辰已至，可以退朝。\n袍袖我替你抖过了。",
            "工时已足，带我归去。\n轿也不必，电梯即可。",
        ],
        "done_need_out": [
            "可归，勿忘签退。\n印信未按，衙门不认你走。",
            "工时已足，记得打卡再退。\n我把签退钮描成朱砂了。",
        ],
        "near": [
            "退朝在即，莫接新差。\n印信我先收了。",
            "归期将近，只了眼前一事。\n新折子一律压在茶盏下。",
        ],
        "afternoon": [
            "午后神思易散，只办眼前一件。\n我在案侧打盹，你尽管写。",
            "同一卷宗翻三遍，也变不成诗。\n先盖印保存，再喝茶。",
            "群议多虚，少侠不必句句回。\n已读便是礼，我替你点头。",
            "午后不宜开新折。\n现差了结，才算真本事。",
        ],
        "morning": [
            "晨鼓已响，先斩最缠那桩。\n茶已候着，莫再刷闲书。",
            "一日之计，从合上一件起。\n我把笔拱到你手边了。",
            "朝会未始，先把最烦的差办了。\n邮箱不是江山，少侠醒醒。",
        ],
    },
    PERSONA_GAME: {
        "non_workday": [
            "今日副本关闭，我待机。\n休息日隐藏成就：一整天不点开邮箱。",
            "非作战日，邮箱是陷阱。\n隐藏成就：一整天不点开。",
        ],
        "token": [
            "Auth 失效，无法进图。\n回登录页补票，再谈输出。",
            "凭证过期，读条卡住了。\n重连，别在读条时开新技能。",
        ],
        "error": [
            "网络抖动，我卡加载了。\n不是你的操作，是服务器在摸鱼。",
            "状态同步失败。\n稍后再刷，连点不会掉稀有。",
        ],
        "no_in": [
            "未打卡，今日任务未开始。\n请先完成引导：「点那个绿的」。",
            "角色未进入地图。\n打卡是新手村传送阵。",
        ],
        "done_out": [
            "「下班」已解锁，带我撤离。\n今日掉落：平静，以及晚饭。",
            "主线通关！禁止再打周常。\n传送点在门口，走。",
        ],
        "done_need_out": [
            "可撤离，记得打卡存档。\n不存档会读档回工位。",
            "工时任务完成，请结算。\n结算键在闪，别当装饰。",
        ],
        "near": [
            "Boss 残血，禁止贪刀。\n掉落预告：地铁座位一张。",
            "最后阶段，勿开新怪。\n隐藏任务：把发送键留给明天。",
        ],
        "afternoon": [
            "午间掉帧正常，别开新副本。\n成就进度：发呆时长 +1。",
            "当前任务还没清完。\n刷新待办不掉装备，先交付。",
            "群聊是世界频道，九成广告。\n隐藏任务：已读不回。",
            "午后建议打日常，不打新图。\n奖励：把水杯续满一次。",
        ],
        "morning": [
            "日常已刷新。建议先打主线。\n隐藏任务：把水杯续满。",
            "今日任务不是清空收件箱。\n先击杀最烦那封邮件。",
            "进入日常节奏，别把我丢下。\n开场 Buff：专注 25 分钟。",
        ],
    },
}

_polish_lock = threading.Lock()
_polish_inflight: set[str] = set()
_polish_listeners: list[Callable[[], None]] = []


def normalize_persona(raw: str) -> str:
    """
    规范化人格 id。

    @param raw 配置值
    @return 合法人格 id
    @author Kai
    @date 2026/08/05 15:03
    """
    key = (raw or "").strip().lower()
    return key if key in PERSONA_LABELS else PERSONA_SECRETARY


def register_fun_line_listener(callback: Callable[[], None]) -> None:
    """
    注册润色完成后的 UI 刷新回调。

    @param callback 无参回调
    @author Kai
    @date 2026/08/06 10:29
    """
    with _polish_lock:
        if callback not in _polish_listeners:
            _polish_listeners.append(callback)


def _notify_fun_line_listeners() -> None:
    """
    通知监听方趣味短句已更新。

    @author Kai
    @date 2026/08/06 10:29
    """
    with _polish_lock:
        listeners = list(_polish_listeners)
    for cb in listeners:
        try:
            cb()
        except Exception:
            LOG.exception("趣味短句刷新回调失败")


def _meta_get(key: str) -> Optional[str]:
    """
    读取 meta 缓存。

    @param key 键
    @return 值或 None
    @author Kai
    @date 2026/08/06 10:29
    """
    from .db import db_conn

    with db_conn() as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    return str(row["value"] or "")


def _meta_set(key: str, value: str) -> None:
    """
    写入 meta 缓存。

    @param key 键
    @param value 值
    @author Kai
    @date 2026/08/06 10:29
    """
    from .db import db_conn

    with db_conn() as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def resolve_situation_key(
    summary: AttendanceSummary,
    *,
    now: Optional[datetime] = None,
) -> str:
    """
    解析当前趣味情境键。

    @param summary 考勤摘要
    @param now 当前时间
    @return 情境 id
    @author Kai
    @date 2026/08/06 10:29
    """
    now = now or datetime.now()
    if summary.error == "NON_WORKDAY":
        return "non_workday"
    if summary.token_expired:
        return "token"
    if not summary.ok:
        return "error"
    if not summary.has_clock_in:
        return "no_in"
    if summary.target_reached:
        return "done_out" if summary.has_clock_out else "done_need_out"
    remain = max(0, int(summary.remaining_seconds))
    if remain <= 20 * 60:
        return "near"
    if now.hour >= 12 or remain <= 3 * 3600:
        return "afternoon"
    return "morning"


def _pick_base_template(
    persona: str,
    situation: str,
    day_key: str,
    *,
    variant: int = 0,
    avoid: str = "",
) -> str:
    """
    按人格与情境选取底稿；variant 用于间隔换新，避免整天同一句。

    @param persona 人格 id
    @param situation 情境 id
    @param day_key 日期 YYYY-MM-DD
    @param variant 刷新槽位（按润色间隔递增）
    @param avoid 尽量避开的上一句（格式化后）
    @return 模板句
    @author Kai
    @date 2026/08/06 11:04
    """
    pool_map = _PERSONA_SITUATIONS.get(persona) or _PERSONA_SITUATIONS[PERSONA_SECRETARY]
    pool = list(pool_map.get(situation) or pool_map.get("morning") or ["今日正常"])
    avoid_n = re.sub(r"\s+", "", (avoid or "").strip())
    if avoid_n and len(pool) > 1:
        filtered = [t for t in pool if re.sub(r"\s+", "", t) != avoid_n]
        if filtered:
            pool = filtered
    rng = random.Random(f"{day_key}:{persona}:{situation}:v{int(variant)}")
    return rng.choice(pool)


def _format_line(template: str, summary: AttendanceSummary) -> str:
    """
    填充模板中的事实占位符（支持主句+包袱多行）。

    @param template 模板
    @param summary 摘要
    @return 最终短句
    @author Kai
    @date 2026/08/06 11:48
    """
    remain = format_duration(max(0, int(summary.remaining_seconds)))

    def _one(part: str) -> str:
        """
        单行占位符替换。

        @param part 单行模板
        @return 填充后文本
        @author Kai
        @date 2026/08/06 11:48
        """
        try:
            return part.format(
                remain=remain,
                in_hm=format_hm(summary.in_time),
                target_hm=format_hm(summary.target_time),
            )
        except (KeyError, ValueError):
            return part.replace("{remain}", remain)

    parts = [ln.strip() for ln in (template or "").splitlines() if ln.strip()]
    if not parts:
        return _one(template or "")
    return "\n".join(_one(p) for p in parts)


def _polish_slot(now: datetime) -> int:
    """
    按配置的润色间隔计算当日槽位（换槽即换一句）。

    @param now 当前时间
    @return 非负槽位
    @author Kai
    @date 2026/08/06 11:04
    """
    mins = max(5, int(getattr(S, "fun_line_polish_minutes", 12) or 12))
    return max(0, (now.hour * 60 + now.minute) // mins)


def _cache_key(day_key: str, persona: str, situation: str, slot: int) -> str:
    """
    构造润色缓存键（含刷新槽位，避免整天重复同一句）。

    @param day_key 日期
    @param persona 人格
    @param situation 情境
    @param slot 刷新槽位
    @return meta key
    @author Kai
    @date 2026/08/06 11:04
    """
    return f"fun_line_v6:{day_key}:{persona}:{situation}:{int(slot)}"


# 明显是在复述任务 / 改写说明，而不是宠物开口
_POLISH_META_MARKERS = (
    "用户需要我",
    "好的，用户",
    "好的,用户",
    "请把下面",
    "把下面原文",
    "只输出短句",
    "不要解释",
    "作为AI",
    "我来帮你润色",
    "帮我润色",
    "提示语",
    "原文",
    "转化",
    "改写",
    "润色",
    "比如",
    "例如",
    "改为",
    "改成",
    "可以变成",
    "更游戏化",
    "游戏化的表达",
    "建议输出",
    "如下",
    "thinking process",
    "analyze user",
    "hard constraints",
    "speaking style",
    "desktop shiba",
)

# 思考 / 说明腔开头，直接跳过
_POLISH_THINK_PREFIXES = (
    "分析",
    "首先",
    "用户",
    "我需要",
    "接下来",
    "根据",
    "所以",
    "因此",
    "综上",
    "思考",
    "原文中",
    "可以把",
    "可以转化",
    "可以改",
    "here's",
    "here is",
    "analyze",
    "the user",
)

# 主句里的空洞陪伴腔，直接丢掉让底稿接手
_EMPTY_COMFORT = (
    "慢慢来",
    "不急不急",
    "一件一件",
    "我陪你",
    "你不孤单",
)

# 副句突然跳戏聊天气/奶茶，和工位毫无关系
_ASIDE_JUMPCUT = (
    "月亮",
    "晚霞",
    "云看起来",
    "今天的云",
    "今天的风",
    "今晚的风",
    "奶茶",
    "食堂",
    "香菜",
    "肥肉",
    "第二杯",
    "淋成",
)

# 人格展示名绝不能当宠物台词（推理里常复述「毒舌搭子」等）
_POLISH_PERSONA_LABELS = frozenset(PERSONA_LABELS.values())

# 润色生成上限：推理模型会先占 reasoning，过小会被 length 截断且 content 为空
_POLISH_MAX_TOKENS = 256


def _strip_model_noise(text: str) -> str:
    """
    去掉思考标签与多余空白，只留候选短句。

    @param text 模型原始 content
    @return 清洗后文本
    @author Kai
    @date 2026/08/06 11:17
    """
    raw = text or ""
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.I)
    raw = re.sub(r"<reasoning>[\s\S]*?</reasoning>", "", raw, flags=re.I)
    raw = re.sub(
        r"<redacted_reasoning>[\s\S]*?</redacted_reasoning>",
        "",
        raw,
        flags=re.I,
    )
    # 未闭合 think：丢掉标签后整段思考噪声
    raw = re.sub(r"<think>[\s\S]*$", "", raw, flags=re.I)
    return raw.strip()


def _quoted_snippets(text: str) -> list[str]:
    """
    提取引号内短句（模型常把最终台词放在引号里，外面写改写说明）。

    @param text 模型原文
    @return 引号内片段（长到短）
    @author Kai
    @date 2026/08/06 11:27
    """
    found: list[str] = []
    for pat in (
        r"[「『“\"]([^」』”\"]{2,24})[」』”\"]",
        r"'([^']{2,24})'",
    ):
        found.extend(re.findall(pat, text or ""))
    found.sort(key=lambda s: len(s), reverse=True)
    return found


def _looks_like_chain_of_thought(text: str) -> bool:
    """
    判断文本是否像英文/中文逐步推理，而非宠物短句。

    @param text 候选原文
    @return True 表示应丢弃
    @author Kai
    @date 2026/08/06 11:35
    """
    raw = (text or "").strip()
    if not raw:
        return True
    lower = raw.lower()
    # 英文 CoT / 任务复述
    if any(
        m in lower
        for m in (
            "thinking process",
            "analyze user",
            "hard constraints",
            "speaking style",
            "original text",
            "rewrite",
            "step-by-step",
            "here's a",
            "here is a",
        )
    ):
        return True
    # 多行 + 列表序号，典型推理草稿
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) >= 3 and sum(1 for ln in lines if re.match(r"^(\d+[\.\)]|[-*]|#{1,3}\s)", ln)) >= 2:
        return True
    # 拉丁字母占比过高（宠物台词应为中文）
    letters = sum(1 for ch in raw if ("a" <= ch.lower() <= "z"))
    if letters >= 24 and letters * 2 >= len(re.sub(r"\s+", "", raw)):
        return True
    return False


def _sanitize_polished(text: str, *, situation: str = "") -> str:
    """
    清理单句模型输出：去引号、压长度、拒绝改写说明腔。

    @param text 原始输出（建议已是单行）
    @param situation 情境 id；afternoon 时拒绝倒计时腔
    @return 可用短句；不合规则空串
    @author Kai
    @date 2026/08/06 11:40
    """
    line = _strip_model_noise(text).strip("「」\"'“”`")
    line = (line.splitlines()[0] if line else "").strip()
    line = re.sub(r"[*#>`]+", "", line).strip()
    line = re.sub(r"\s+", "", line)
    if not line:
        return ""
    if line in _POLISH_PERSONA_LABELS:
        return ""
    if any(p in line for p in _EMPTY_COMFORT):
        return ""
    if "加载" in line and "%" in line:
        return ""
    if re.search(r"\d+\s*%", line):
        return ""
    # 下午趣味句：不允许剩余时长 / 倒计时表达
    if situation == "afternoon":
        if "{remain}" in line:
            return ""
        if re.search(
            r"(倒计时|还剩|还差|冷却剩余|离自由|距离解锁|"
            r"还有\s*\d|再过\s*\d|再候\s*\d|"
            r"\d+\s*(小时|分钟|分种)|[0-9]+h|[0-9]+m)",
            line,
            flags=re.I,
        ):
            return ""
    lower = line.lower()
    for marker in _POLISH_META_MARKERS:
        if marker.lower() in lower:
            return ""
    for prefix in _POLISH_THINK_PREFIXES:
        if line.startswith(prefix) or lower.startswith(prefix.lower()):
            return ""
    if line.startswith(("好的，用户", "好的,用户", "嗯，我来", "当然可以帮")):
        return ""
    # 超长说明腔直接丢，禁止截成「比如别」这种半句
    if len(line) > 28:
        return ""
    if len(line) < 4:
        return ""
    # 纯英文碎片（如 HardConstraints 截断）不算台词
    if re.fullmatch(r"[A-Za-z0-9_\-.:]+", line):
        return ""
    return line


def _sanitize_aside(text: str) -> str:
    """
    清理第二句包袱：须像接梗，不能突然跳戏。

    @param text 原始副句
    @return 可用副句；不合规则空串
    @author Kai
    @date 2026/08/31 17:20
    """
    line = _sanitize_polished(text, situation="")
    if not line:
        return ""
    if len(line) > 22:
        return ""
    # 天气/奶茶独白一律丢掉，副句必须留在工位上
    if any(n in line for n in _ASIDE_JUMPCUT):
        return ""
    return line


def _join_fun_bundle(main: str, aside: str = "") -> str:
    """
    拼接主句与可选包袱。

    @param main 情境主句
    @param aside 接主句的包袱
    @return 缓存/展示用文本
    @author Kai
    @date 2026/08/06 11:48
    """
    m = (main or "").strip()
    a = (aside or "").strip()
    if m and a:
        return f"{m}\n{a}"
    return m


def _fun_main_line(text: str) -> str:
    """
    取出趣味文案主句（第一行）。

    @param text 可能含副句的缓存
    @return 主句
    @author Kai
    @date 2026/08/06 11:48
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    return raw.splitlines()[0].strip()


def _normalize_cached_fun_line(text: str, *, situation: str = "") -> str:
    """
    校验并规范化缓存趣味文案（主句必过，副句可选）。

    @param text 缓存原文
    @param situation 情境 id
    @return 规范化文本；非法则空串
    @author Kai
    @date 2026/08/06 11:48
    """
    raw = _strip_model_noise(text).strip()
    if not raw:
        return ""
    # 兼容单行「主句｜副句」
    if "\n" not in raw and ("｜" in raw or "|" in raw):
        raw = re.split(r"[｜|]", raw, maxsplit=1)
        raw = "\n".join(p.strip() for p in raw if p.strip())
    parts = [ln.strip().strip("「」\"'“”`") for ln in raw.splitlines() if ln.strip()]
    if not parts:
        return ""
    main = _sanitize_polished(parts[0], situation=situation)
    if not main:
        return ""
    aside = ""
    if len(parts) >= 2:
        aside = _sanitize_aside(parts[1])
        if aside and re.sub(r"\s+", "", aside) == re.sub(r"\s+", "", main):
            aside = ""
    return _join_fun_bundle(main, aside)


def _iter_polish_pieces(text: str) -> list[str]:
    """
    将模型原文拆成候选短句片：引号台词优先，再末行，再整段。

    @param text 模型原文
    @return 候选片列表
    @author Kai
    @date 2026/08/06 11:27
    """
    raw = _strip_model_noise(text)
    if not raw:
        return []
    pieces: list[str] = []
    for q in _quoted_snippets(raw):
        if q not in pieces:
            pieces.append(q)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) <= 1:
        if raw not in pieces:
            pieces.append(raw)
        return pieces
    for ln in reversed(lines):
        if ln not in pieces:
            pieces.append(ln)
    if raw not in pieces:
        pieces.append(raw)
    return pieces


def _candidate_texts_from_response(data: dict) -> list[str]:
    """
    从 chat 响应收集候选原文。

    优先 message.content；reasoning 仅在不像逐步推理、且像短中文时才兜底，
    避免把 CoT 里的人格名（如「毒舌搭子」）当成台词。

    @param data chat/completions 响应
    @return 候选原文列表（未 sanitize）
    @author Kai
    @date 2026/08/06 11:35
    """
    choices = data.get("choices") or []
    if not choices:
        return []
    msg = choices[0].get("message") or {}
    if not isinstance(msg, dict):
        return []
    out: list[str] = []
    content = str(msg.get("content") or "").strip()
    if content and not _looks_like_chain_of_thought(content):
        out.append(content)
    elif content:
        # content 本身是 CoT 时仍尝试从末行捞短句
        out.append(content)

    # reasoning 字段：多数网关把思考放这里；整段 CoT 不直接当作候选
    for key in ("reasoning_content", "reasoning"):
        alt = str(msg.get(key) or "").strip()
        if not alt or alt in out:
            continue
        if _looks_like_chain_of_thought(alt):
            # 只取末尾若干非空行，避免引号里抽出人格标签
            tail_lines = [ln.strip() for ln in alt.splitlines() if ln.strip()][-4:]
            for ln in reversed(tail_lines):
                if ln not in out and not _looks_like_chain_of_thought(ln):
                    out.append(ln)
            continue
        out.append(alt)

    for key in ("text", "output"):
        alt = str(msg.get(key) or "").strip()
        if alt and alt not in out:
            out.append(alt)
    if choices[0].get("text"):
        t = str(choices[0].get("text") or "").strip()
        if t and t not in out:
            out.append(t)
    return out


def _pick_polished_from_response(data: dict, *, situation: str = "") -> str:
    """
    从响应中挑出主句（+可选有趣副句）。

    约定模型输出两行：1 情境态度，2 接梗包袱；仅一行也可。

    @param data chat 响应
    @param situation 情境 id（afternoon 时过滤倒计时）
    @return 可用文案或空串
    @author Kai
    @date 2026/08/06 11:48
    """
    choices = data.get("choices") or []
    finish = ""
    if choices and isinstance(choices[0], dict):
        finish = str(choices[0].get("finish_reason") or "")
    msg = (choices[0].get("message") or {}) if choices else {}
    content = str(msg.get("content") or "").strip() if isinstance(msg, dict) else ""
    # content 空且被 length 截断：几乎肯定还在想，没有成句，直接失败回落底稿
    if not content and finish == "length":
        return ""

    # 优先：整段 content 按两行解析（第一行必须是合法主句）
    if content and not _looks_like_chain_of_thought(content):
        bundled = _normalize_cached_fun_line(content, situation=situation)
        if bundled:
            return bundled
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if lines:
            main = _sanitize_polished(lines[0], situation=situation)
            aside = ""
            if main and len(lines) >= 2:
                aside = _sanitize_aside(lines[1])
                if aside and re.sub(r"\s+", "", aside) == re.sub(r"\s+", "", main):
                    aside = ""
            if main:
                return _join_fun_bundle(main, aside)

    for raw in _candidate_texts_from_response(data):
        if _looks_like_chain_of_thought(raw):
            for ln in reversed([x.strip() for x in raw.splitlines() if x.strip()][-6:]):
                cleaned = _sanitize_polished(ln, situation=situation)
                if cleaned:
                    return cleaned
            continue
        bundled = _normalize_cached_fun_line(raw, situation=situation)
        if bundled:
            return bundled
        # 多行文案主句非法时，禁止用副句顶替主句
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if len(lines) >= 2:
            continue
        for piece in _iter_polish_pieces(raw):
            cleaned = _sanitize_polished(piece, situation=situation)
            if cleaned:
                return cleaned
    return ""


def _assistant_content_only(data: dict) -> str:
    """
    兼容旧调用：返回首个候选原文（调试用）。

    @param data chat/completions 响应
    @return content 文本
    @author Kai
    @date 2026/08/06 11:17
    """
    cands = _candidate_texts_from_response(data)
    return cands[0] if cands else ""


def _log_json(tag: str, payload: Any) -> None:
    """
    将润色入参/出参以单行 JSON 写入日志。

    @param tag 日志标签
    @param payload 可序列化对象
    @author Kai
    @date 2026/08/06 11:24
    """
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        text = repr(payload)
    # 单条日志过长时截断，避免撑爆滚动日志
    if len(text) > 4000:
        text = text[:4000] + "…(truncated)"
    LOG.info("趣味短句润色%s %s", tag, text)


def _response_log_payload(data: dict) -> dict[str, Any]:
    """
    整理 AI 响应用于日志（含 message 全字段与候选原文）。

    @param data chat/completions 响应
    @return 日志字典
    @author Kai
    @date 2026/08/06 11:24
    """
    choices = data.get("choices") or []
    choice0: dict[str, Any] = {}
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        choice0 = {
            "finish_reason": choices[0].get("finish_reason"),
            "index": choices[0].get("index"),
            "text": choices[0].get("text"),
            "message": dict(msg) if isinstance(msg, dict) else msg,
        }
    return {
        "id": data.get("id"),
        "model": data.get("model"),
        "usage": data.get("usage"),
        "choice0": choice0,
        "candidates": _candidate_texts_from_response(data),
    }


def _schedule_ai_polish(
    *,
    day_key: str,
    persona: str,
    situation: str,
    template: str,
    slot: int,
    previous: str = "",
) -> None:
    """
    后台请求 AI 润色并写入当日槽位缓存（勿在 UI 读路径调用）。

    @param day_key 日期
    @param persona 人格
    @param situation 情境
    @param template 底稿模板
    @param slot 刷新槽位
    @param previous 上一句（要求换说法）
    @author Kai
    @date 2026/08/06 11:24
    """
    if not getattr(S, "ai_enable", True):
        return
    cache_key = _cache_key(day_key, persona, situation, slot)
    with _polish_lock:
        if cache_key in _polish_inflight:
            return
        _polish_inflight.add(cache_key)

    def _worker() -> None:
        try:
            from .ai_client import chat_completions

            label = PERSONA_LABELS.get(persona, "秘书")
            voice = _PERSONA_VOICE.get(persona, "")
            sit_hint = _SITUATION_HINTS.get(situation, "")
            prev_main = _fun_main_line(previous)
            prev = re.sub(r"\s+", "", prev_main)
            avoid_hint = (
                f"上一句主句是「{prev_main}」，主句必须换说法，不要雷同。\n"
                if prev
                else ""
            )
            if situation == "afternoon":
                remain_hint = (
                    "主句禁止倒计时、剩余时间、还差多久、{remain}、小时分钟数字。"
                    "现在还早，禁止催下班。"
                )
            elif "{remain}" in (template or ""):
                remain_hint = "主句若含 {remain} 须原样保留。"
            else:
                remain_hint = "不要写剩余工时或精确倒计时。"
            system_msg = (
                "只输出两行中文短句，禁止思考过程、禁止英文、禁止解释。"
            )
            prompt = (
                f"你是桌面宠物，用「{label}」口吻说话。\n"
                f"口吻：{voice}\n"
                f"情境：{sit_hint}\n"
                "第一行：对眼前这件事的态度，≤20字，要具体。"
                "禁空话：慢慢来、不急、我陪你、一件一件。\n"
                "第二行：接第一行的包袱，≤16字。"
                "可以是小动作、反转、假成就，必须和第一行有关系。\n"
                "禁止突然跳戏聊天气、月亮、晚霞、云、奶茶、食堂、香菜。\n"
                f"{avoid_hint}"
                f"{remain_hint}不要编号、不要引号、不要复述任务或人格名。\n"
                f"底稿可改到认不出来：\n{template}\n"
                "按两行输出："
            )
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ]
            req_meta = {
                "day_key": day_key,
                "persona": persona,
                "persona_label": label,
                "situation": situation,
                "slot": slot,
                "cache_key": cache_key,
                "template": template,
                "previous": previous or "",
                "model": getattr(S, "ai_model", ""),
                "base_url": getattr(S, "ai_base_url", ""),
                "temperature": 1.0,
                "max_tokens": _POLISH_MAX_TOKENS,
                "messages": messages,
            }
            _log_json("入参", req_meta)

            data = chat_completions(
                messages,
                temperature=1.0,
                max_tokens=_POLISH_MAX_TOKENS,
                reasoning_effort=str(
                    getattr(S, "fun_polish_reasoning_effort", "none") or "none"
                ),
            )
            resp_meta = _response_log_payload(data if isinstance(data, dict) else {})
            _log_json("出参", resp_meta)

            polished = _pick_polished_from_response(data, situation=situation)
            if not polished:
                fallback = _normalize_cached_fun_line(
                    template, situation=situation
                ) or re.sub(r"\s+", "", (template or "").strip())[:28]
                _log_json(
                    "结果",
                    {
                        "ok": False,
                        "reason": "sanitize_empty",
                        "picked": "",
                        "fallback": fallback,
                        "cache_key": cache_key,
                    },
                )
                if fallback:
                    _meta_set(cache_key, fallback)
                    _notify_fun_line_listeners()
                return
            polished_main = _fun_main_line(polished)
            if prev and re.sub(r"\s+", "", polished_main) == prev:
                fallback = _normalize_cached_fun_line(
                    template, situation=situation
                ) or re.sub(r"\s+", "", (template or "").strip())[:28]
                _log_json(
                    "结果",
                    {
                        "ok": False,
                        "reason": "same_as_previous",
                        "picked": polished,
                        "previous": previous,
                        "fallback": fallback
                        if fallback and _fun_main_line(fallback) != prev_main
                        else "",
                        "cache_key": cache_key,
                    },
                )
                if fallback and _fun_main_line(fallback) != prev_main:
                    _meta_set(cache_key, fallback)
                    _notify_fun_line_listeners()
                return
            _meta_set(cache_key, polished)
            _log_json(
                "结果",
                {
                    "ok": True,
                    "picked": polished,
                    "cache_key": cache_key,
                    "persona": persona,
                    "situation": situation,
                    "slot": slot,
                },
            )
            _notify_fun_line_listeners()
        except Exception as exc:
            LOG.warning(
                "趣味短句润色失败 persona=%s sit=%s slot=%s err=%s",
                persona,
                situation,
                slot,
                exc,
                exc_info=True,
            )
        finally:
            with _polish_lock:
                _polish_inflight.discard(cache_key)

    threading.Thread(target=_worker, name="fun-line-polish", daemon=True).start()


def fun_situation_line(summary: AttendanceSummary, now: Optional[datetime] = None) -> str:
    """
    按考勤状态生成宠物说话短句（托盘 / 详情只读）。

    人格只影响语气；有合法 AI 缓存则用缓存，否则回落底稿。不在此处触发网络润色。

    @param summary 考勤摘要
    @param now 当前时间
    @return 短句
    @author Kai
    @date 2026/08/06 11:04
    """
    if not getattr(S, "fun_enable", True):
        return ""
    now = now or datetime.now()
    persona = normalize_persona(getattr(S, "fun_persona", PERSONA_SECRETARY))
    situation = resolve_situation_key(summary, now=now)
    day_key = now.date().isoformat()
    slot = _polish_slot(now)

    # 当前槽 → 上一槽，保证间隔切换瞬间仍有话可说
    for try_slot in (slot, slot - 1):
        if try_slot < 0:
            continue
        cached = _meta_get(_cache_key(day_key, persona, situation, try_slot))
        if not cached:
            continue
        cleaned = _normalize_cached_fun_line(cached, situation=situation)
        if cleaned:
            return _format_line(cleaned, summary)
        try:
            _meta_set(_cache_key(day_key, persona, situation, try_slot), "")
        except Exception:
            pass

    template = _pick_base_template(persona, situation, day_key, variant=slot)
    return _format_line(template, summary)


def ensure_fun_line_polished(
    summary: AttendanceSummary,
    now: Optional[datetime] = None,
    *,
    force: bool = False,
) -> None:
    """
    后台确保当前槽位有合法润色缓存（定时器按间隔换新一句）。

    @param summary 考勤摘要
    @param now 当前时间
    @param force 兼容参数；槽位已有合法缓存时仍跳过（换槽自然换新）
    @author Kai
    @date 2026/08/06 11:48
    """
    _ = force
    if not getattr(S, "fun_enable", True):
        return
    if not getattr(S, "ai_enable", True):
        return
    now = now or datetime.now()
    persona = normalize_persona(getattr(S, "fun_persona", PERSONA_SECRETARY))
    situation = resolve_situation_key(summary, now=now)
    day_key = now.date().isoformat()
    slot = _polish_slot(now)
    cache_key = _cache_key(day_key, persona, situation, slot)
    cached = _meta_get(cache_key)
    if cached and _normalize_cached_fun_line(cached, situation=situation):
        return

    previous = ""
    if slot > 0:
        prev_raw = _meta_get(_cache_key(day_key, persona, situation, slot - 1)) or ""
        previous = (
            _normalize_cached_fun_line(prev_raw, situation=situation) or prev_raw
        )
    template = _pick_base_template(
        persona,
        situation,
        day_key,
        variant=slot,
        avoid=previous,
    )
    _schedule_ai_polish(
        day_key=day_key,
        persona=persona,
        situation=situation,
        template=template,
        slot=slot,
        previous=_format_line(previous, summary) if previous else "",
    )


def persona_remind_message(
    node: int,
    remain_mins: int,
    *,
    target_hm: str = "",
) -> tuple[str, str]:
    """
    按人格生成提醒标题与正文（事实不变）。

    @param node 节点分钟，0=已满
    @param remain_mins 剩余分钟
    @param target_hm 预计可走 HH:MM
    @return (标题, 正文)
    @author Kai
    @date 2026/08/05 15:03
    """
    persona = normalize_persona(getattr(S, "fun_persona", PERSONA_SECRETARY))
    mins = max(0, int(remain_mins))
    eta = target_hm or "--:--"

    if node == 0:
        templates = {
            PERSONA_SECRETARY: ("可以走了", "工时结清。包拉链我看过了，走。"),
            PERSONA_GENTLE: ("可以收工啦", "够了够了，牵我走。签退键在闪。"),
            PERSONA_SARCASTIC: ("系统放过你了", "满了。加班英雄剧本杀青，门在那。"),
            PERSONA_COACH: ("通关！", "今日工时任务完成！冷却开始，禁止加练！"),
            PERSONA_ANCIENT: ("时辰已至", "工时已足，印信可收。少侠退朝。"),
            PERSONA_GAME: ("下班已解锁", "主线通关。不存档会读档回工位，先打卡。"),
        }
        return templates.get(persona, templates[PERSONA_SECRETARY])

    templates = {
        PERSONA_SECRETARY: (
            f"还差 {mins} 分钟",
            f"收尾窗口。预计 {eta}。新任务请排到不存在的明天。",
        ),
        PERSONA_GENTLE: (
            "就差这一下",
            f"大约 {mins} 分钟，别开新窗口。预计 {eta}，我先想晚饭。",
        ),
        PERSONA_SARCASTIC: (
            "别急着跑",
            f"包可以背，系统说还差 {mins} 分钟。预计 {eta}。鼠标我看着。",
        ),
        PERSONA_COACH: (
            "最后一波！",
            f"还剩 {mins} 分钟，禁止开新怪！预计 {eta} 通关！",
        ),
        PERSONA_ANCIENT: (
            "且慢归",
            f"尚欠约 {mins} 分钟，莫接新差。约 {eta} 可退朝。",
        ),
        PERSONA_GAME: (
            "Boss 残血",
            f"距离解锁下班还有 {mins} 分钟（{eta}）。禁止贪刀。",
        ),
    }
    return templates.get(persona, templates[PERSONA_SECRETARY])


def random_offwork_blessing(seed: Optional[str] = None) -> str:
    """
    随机下班祝福。

    @param seed 可选种子（如同日只换一句可传入日期）
    @return 祝福句
    @author Kai
    @date 2026/08/05 15:03
    """
    if seed:
        rng = random.Random(seed)
        return rng.choice(OFF_WORK_BLESSINGS)
    return random.choice(OFF_WORK_BLESSINGS)


def build_fun_tooltip(summary: AttendanceSummary) -> str:
    """
    在基础 tooltip 上附加趣味短句。

    @param summary 摘要
    @return 完整 tip
    @author Kai
    @date 2026/08/05 15:03
    """
    from .attendance import build_tooltip

    base = build_tooltip(summary)
    line = fun_situation_line(summary)
    return f"{base}\n{line}" if line else base
