# Copyright (c) iGroup.
# All rights reserved.
"""
本地 AI Agent：有限轮次 tool-calling。

@author Kai
@date 2026/08/05 16:12
@description 对话可流式；通过工具创建事项 / 查考勤等
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable, Optional

from .ai_client import (
    chat_completions,
    extract_assistant_message,
    stream_chat_completions,
)
from .ai_tools import dispatch_tool, tool_schemas
from .config import S
from .paths import LOG


def build_system_prompt() -> str:
    """
    构造系统提示。

    @return system 文本
    @author Kai
    @date 2026/08/05 16:12
    """
    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    return f"""你是 iGroup China 考勤助手里的本地 AI，运行在用户电脑上。
当前本地时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（星期{weekday}）。

你的定位：能动手的考勤/事项助手。用户要求创建、完成或查询事项时必须调用对应工具，只有工具返回 ok=true 后才能回复操作成功。查今日考勤用 get_attendance；查昨天/某一天/指定日期或一段日期用 get_day_attendance（date 用 YYYY-MM-DD）；查本月/这个月/当月考勤或月度打卡统计用 get_month_attendance。问摸鱼、休息、用了哪些软件、使用时长时必须调用 get_app_usage，不要用打卡工时冒充。搜网、读文件也优先使用工具，绝不能假装调用或只用文字声称已执行。
可用 Markdown 简洁回复。不要把用户带进长文写作流程。若用户明确要求文案润色、改写、邮件/周报精修、会议纪要长文，请礼貌说明这类任务更适合用 ChatGPT。

提醒模式：fixed / before_due / workday。时间用本地 ISO。
搜网结果请标注来源。读文件、列目录只能访问白名单；不限制文件扩展名。不确定文件名时先 list_dir 或 ls。不要自行开门禁。
"""


def _required_tool_for_request(user_text: str) -> Optional[str]:
    """
    识别必须实际执行的事项操作，避免模型仅用文字声称完成。

    @param user_text 用户本轮输入
    @return 必须调用的工具名；普通对话返回 None
    @author Kai
    @date 2026/09/01 10:12
    """
    text = re.sub(r"\s+", "", user_text or "").lower()
    if not text or re.search(r"(?:怎么|如何|能否|可以).*?(?:创建|新增|添加)", text):
        return None
    create_action = re.search(
        r"(?:创建|新增|添加|新建|建个|建一个|记下|记个|提醒我)", text
    )
    item_target = re.search(r"(?:事项|待办|任务|提醒)", text)
    if create_action and (item_target or "提醒我" in text):
        return "create_item"
    # 「怎么看摸鱼」是问用法；「今天摸鱼了多久」必须走使用时长工具
    if re.search(r"(?:怎么|如何).*?(?:摸鱼|使用时长|软件)", text):
        return None
    if re.search(
        r"摸鱼|使用时长|前台软件|哪些软件|什么软件|开了哪些"
        r"|休息了|休息多久|休息时间",
        text,
    ):
        return "get_app_usage"
    # 「怎么查本月考勤」是问用法；「可以帮我查这个月」仍强制走工具
    if re.search(r"(?:怎么|如何).*?(?:本月|这个月|当月)", text):
        return None
    if re.search(
        r"(?:本月|这个月|当月).*(?:考勤|打卡|出勤|工时|统计)"
        r"|(?:考勤|打卡|出勤|工时).*(?:本月|这个月|当月)",
        text,
    ):
        return "get_month_attendance"
    # 昨天/指定日/上周某天：必须走按日接口，禁止编造
    if re.search(r"(?:怎么|如何).*?(?:昨天|前天|哪天|某一天)", text):
        return None
    if re.search(
        r"(?:昨天|前天|上周|哪天|某一天|\d{4}[-/]\d{1,2}[-/]\d{1,2})"
        r".*(?:考勤|打卡|出勤|工时)"
        r"|(?:考勤|打卡|出勤|工时).*"
        r"(?:昨天|前天|上周|\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        text,
    ):
        return "get_day_attendance"
    # 「怎么查今天考勤」是问用法；「帮我查今天打卡」仍强制走工具
    if re.search(r"(?:怎么|如何).*?(?:今天|今日)", text):
        return None
    if re.search(
        r"(?:今天|今日).*(?:考勤|打卡|出勤|工时)"
        r"|(?:考勤|打卡|出勤|工时).*(?:今天|今日)",
        text,
    ):
        return "get_attendance"
    return None


def _tool_result_ok(result_text: str) -> tuple[bool, str]:
    """
    解析工具 JSON，判断是否失败。

    @param result_text dispatch_tool 返回的 JSON 文本
    @return (是否成功, 失败原因)
    @author Kai
    @date 2026/09/01 10:20
    """
    try:
        data = json.loads(result_text)
    except json.JSONDecodeError:
        return True, ""
    if not isinstance(data, dict):
        return True, ""
    if data.get("ok") is False:
        err = str(data.get("error") or "失败").replace("\n", " ").strip()[:80]
        return False, err or "失败"
    return True, ""


def run_agent(
    user_text: str,
    *,
    history: Optional[list[dict[str, Any]]] = None,
    max_rounds: Optional[int] = None,
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    stream: bool = False,
) -> dict[str, Any]:
    """
    执行有限轮次 Agent；stream=True 时对正文 delta 回调。

    @param user_text 用户输入
    @param history 可选历史（不含 system）
    @param max_rounds 最大工具轮次
    @param on_delta 流式文本增量回调
    @param on_status 状态文案回调（如调用工具中）
    @param stream 是否流式拉取
    @return {ok, reply, tool_trace, error?}
    @author Kai
    @date 2026/08/05 16:12
    """
    if not S.ai_enable:
        return {"ok": False, "reply": "", "tool_trace": [], "error": "AI 已关闭"}

    rounds = int(max_rounds if max_rounds is not None else S.ai_agent_max_rounds)
    rounds = max(1, min(10, rounds))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt()}
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    tools = tool_schemas() if S.ai_enable_agent else None
    required_tool = _required_tool_for_request(user_text) if tools else None
    tool_trace: list[dict[str, Any]] = []
    streamed_any = False

    def _delta(piece: str) -> None:
        nonlocal streamed_any
        if not piece or not on_delta:
            return
        streamed_any = True
        on_delta(piece)

    try:
        for round_index in range(rounds):
            tool_choice: Any = "auto" if tools else None
            if required_tool and not tool_trace and round_index == 0:
                # 明确的写操作必须绑定函数，杜绝“嘴上创建、实际未落库”。
                tool_choice = {
                    "type": "function",
                    "function": {"name": required_tool},
                }
            if stream:
                msg = stream_chat_completions(
                    messages,
                    on_delta=_delta,
                    tools=tools if tools else None,
                    tool_choice=tool_choice,
                )
            else:
                data = chat_completions(
                    messages,
                    tools=tools if tools else None,
                    tool_choice=tool_choice,
                )
                msg = extract_assistant_message(data)

            tool_calls = msg.get("tool_calls") or []
            content = str(msg.get("content") or "")
            if tool_calls and tools:
                names = []
                for call in tool_calls:
                    fn = (call.get("function") or {}) if isinstance(call, dict) else {}
                    names.append(str(fn.get("name") or "tool"))
                if on_status:
                    # 逐个通知，便于 UI 做成 ChatGPT 式工具卡片
                    for name in names:
                        on_status(f"tool_start:{name}")
                    on_status("调用工具：" + ", ".join(names))
                messages.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": tool_calls,
                    }
                )
                for call in tool_calls:
                    fn = (call.get("function") or {}) if isinstance(call, dict) else {}
                    name = str(fn.get("name") or "")
                    args = fn.get("arguments") or "{}"
                    call_id = str(call.get("id") or name)
                    result_text = dispatch_tool(name, args)
                    tool_trace.append(
                        {"name": name, "arguments": args, "result": result_text}
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result_text,
                        }
                    )
                    if on_status and name:
                        ok, err = _tool_result_ok(result_text)
                        if ok:
                            on_status(f"tool_done:{name}")
                        else:
                            on_status(f"tool_fail:{name}|{err}")
                if on_status:
                    on_status("生成中…")
                continue

            reply = content.strip()
            if not reply and not streamed_any:
                reply = "已处理。" if tool_trace else "（无文本回复）"
            elif not reply and streamed_any:
                reply = ""  # 内容已通过 delta 推送
            return {"ok": True, "reply": reply or content, "tool_trace": tool_trace}

        messages.append(
            {
                "role": "user",
                "content": "工具调用轮次已达上限，请根据已有结果用中文简短总结（可用 Markdown）。",
            }
        )
        if stream:
            msg = stream_chat_completions(
                messages, on_delta=_delta, tools=None
            )
        else:
            data = chat_completions(messages, tools=None)
            msg = extract_assistant_message(data)
        return {
            "ok": True,
            "reply": str(msg.get("content") or "已达到工具轮次上限。").strip(),
            "tool_trace": tool_trace,
        }
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Agent 失败")
        return {
            "ok": False,
            "reply": "",
            "tool_trace": tool_trace,
            "error": str(exc),
        }
