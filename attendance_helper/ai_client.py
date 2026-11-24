# Copyright (c) iGroup.
# All rights reserved.
"""
本地 Ollama / OpenAI 兼容 Chat Completions 客户端。

@author Kai
@date 2026/08/05 14:50
@description 支持非流式、SSE 流式与 tools；对 Ollama 思考模型关 reasoning
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterator, Optional

from .config import S, normalize_reasoning_effort
from .paths import LOG

# 先加载 paths 以持久化 CA 证书，再让 requests 缓存 bundle 路径
import requests

# 请求超时（秒）
AI_TIMEOUT_SECONDS = 90


def _headers(*, stream: bool = False) -> dict[str, str]:
    """
    构造 Authorization 与内容协商头。

    @param stream 是否 SSE 流式
    @return 请求头
    @author Kai
    @date 2026/08/05 15:35
    """
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "text/event-stream" if stream else "application/json",
        "Accept-Charset": "utf-8",
    }
    token = (S.ai_api_token or "").strip()
    if token:
        if not token.lower().startswith("bearer "):
            token = f"Bearer {token}"
        headers["Authorization"] = token
    return headers


def _force_utf8_response(resp: requests.Response) -> None:
    """
    强制按 UTF-8 解码响应（网关常缺 charset，默认 latin-1 会中文乱码）。

    @param resp requests 响应
    @author Kai
    @date 2026/08/05 15:35
    """
    resp.encoding = "utf-8"


def _build_payload(
    messages: list[dict[str, Any]],
    *,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Any = None,
    temperature: float = 0.2,
    stream: bool = False,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    reasoning_effort: Optional[str] = None,
) -> dict[str, Any]:
    """
    构造 chat/completions 请求体。

    @param messages 消息列表
    @param tools 可选 tools
    @param tool_choice 工具选择策略或指定函数对象
    @param temperature 温度
    @param stream 是否流式
    @param max_tokens 最大生成 token
    @param json_mode 是否请求 JSON object 模式
    @param reasoning_effort 思考程度；None 则用聊天框配置
    @return payload
    @author Kai
    @date 2026/09/01 10:30
    """
    if not S.ai_enable:
        raise RuntimeError("AI 已在设置中关闭")
    url = (S.ai_base_url or "").strip()
    if not url:
        raise RuntimeError("未配置 AI base_url")
    effort = normalize_reasoning_effort(
        reasoning_effort if reasoning_effort is not None else S.ai_reasoning_effort
    )
    payload: dict[str, Any] = {
        "model": S.ai_model,
        "messages": messages,
        "stream": bool(stream),
        # 同时兼容 Ollama 的 think 与 OpenAI 兼容接口的 reasoning_effort。
        "think": effort != "none",
        "reasoning_effort": effort,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
    if max_tokens is not None and max_tokens > 0:
        payload["max_tokens"] = int(max_tokens)
    if json_mode:
        # OpenAI 兼容；网关不支持时由调用方兜底重试
        payload["response_format"] = {"type": "json_object"}
    return payload


def chat_completions(
    messages: list[dict[str, Any]],
    *,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Any = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    reasoning_effort: Optional[str] = None,
) -> dict[str, Any]:
    """
    非流式调用 chat/completions。

    @param messages OpenAI 风格消息列表
    @param tools 可选 tools schema
    @param tool_choice auto / none / 指定函数对象
    @param temperature 采样温度
    @param max_tokens 可选生成上限
    @param json_mode 是否强制 JSON
    @param reasoning_effort 思考程度；None 则用聊天框配置
    @return 原始响应 JSON
    @author Kai
    @date 2026/09/01 10:30
    """
    payload = _build_payload(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
        stream=False,
        max_tokens=max_tokens,
        json_mode=json_mode,
        reasoning_effort=reasoning_effort,
    )
    LOG.info(
        "AI 请求 model=%s msgs=%s tools=%s stream=0 json=%s effort=%s",
        S.ai_model,
        len(messages),
        bool(tools),
        json_mode,
        payload.get("reasoning_effort"),
    )
    resp = requests.post(
        S.ai_base_url.strip(),
        headers=_headers(stream=False),
        json=payload,
        timeout=AI_TIMEOUT_SECONDS,
    )
    _force_utf8_response(resp)
    # 部分网关不认 response_format：去掉再试
    if resp.status_code >= 400 and json_mode:
        LOG.warning(
            "json_mode 请求失败 HTTP %s，回退普通请求",
            resp.status_code,
        )
        payload.pop("response_format", None)
        resp = requests.post(
            S.ai_base_url.strip(),
            headers=_headers(stream=False),
            json=payload,
            timeout=AI_TIMEOUT_SECONDS,
        )
        _force_utf8_response(resp)
    if resp.status_code >= 400:
        raise RuntimeError(f"AI HTTP {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("AI 响应不是 JSON 对象")
    return data


def _merge_tool_call_delta(
    acc: dict[int, dict[str, Any]],
    deltas: list[dict[str, Any]],
) -> None:
    """
    合并流式 tool_calls delta 到累加器。

    @param acc index → 部分 tool_call
    @param deltas 本片 delta.tool_calls
    @author Kai
    @date 2026/08/05 14:50
    """
    for d in deltas:
        if not isinstance(d, dict):
            continue
        idx = int(d.get("index", 0))
        slot = acc.setdefault(
            idx,
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        if d.get("id"):
            slot["id"] = str(d["id"])
        if d.get("type"):
            slot["type"] = str(d["type"])
        fn = d.get("function") or {}
        if isinstance(fn, dict):
            if fn.get("name"):
                slot["function"]["name"] = str(fn["name"])
            if fn.get("arguments"):
                slot["function"]["arguments"] += str(fn["arguments"])


def iter_chat_completions(
    messages: list[dict[str, Any]],
    *,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Any = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
) -> Iterator[dict[str, Any]]:
    """
    SSE 流式调用；yield 事件：
    - {"type":"delta","content":"..."}
    - {"type":"message","message":{...}} 结束时的完整 assistant message

    @param messages 消息列表
    @param tools 可选 tools
    @param tool_choice 工具策略或指定函数对象
    @param temperature 温度
    @param max_tokens 生成上限
    @param reasoning_effort 思考程度；None 则用聊天框配置
    @return 事件迭代器
    @author Kai
    @date 2026/09/01 10:30
    """
    payload = _build_payload(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
        stream=True,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    LOG.info(
        "AI 流式请求 model=%s msgs=%s tools=%s effort=%s",
        S.ai_model,
        len(messages),
        bool(tools),
        payload.get("reasoning_effort"),
    )
    resp = requests.post(
        S.ai_base_url.strip(),
        headers=_headers(stream=True),
        json=payload,
        timeout=AI_TIMEOUT_SECONDS,
        stream=True,
    )
    _force_utf8_response(resp)
    if resp.status_code >= 400:
        body = resp.text[:400] if resp.text else ""
        raise RuntimeError(f"AI HTTP {resp.status_code}: {body}")

    content_parts: list[str] = []
    tool_acc: dict[int, dict[str, Any]] = {}
    finish_reason: Optional[str] = None

    # 二进制按 UTF-8 解码，避免 decode_unicode 走 latin-1 导致中文乱码
    for raw_line in resp.iter_lines(decode_unicode=False):
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace").strip()
        else:
            line = str(raw_line).strip()
        if not line:
            continue
        if line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice0 = choices[0] or {}
        delta = choice0.get("delta") or {}
        fr = choice0.get("finish_reason")
        if fr:
            finish_reason = str(fr)
        piece = delta.get("content")
        if piece:
            text = str(piece)
            content_parts.append(text)
            yield {"type": "delta", "content": text}
        tcs = delta.get("tool_calls")
        if isinstance(tcs, list) and tcs:
            _merge_tool_call_delta(tool_acc, tcs)

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts),
    }
    if tool_acc:
        message["tool_calls"] = [tool_acc[i] for i in sorted(tool_acc.keys())]
    yield {
        "type": "message",
        "message": message,
        "finish_reason": finish_reason,
    }


def stream_chat_completions(
    messages: list[dict[str, Any]],
    *,
    on_delta: Optional[Callable[[str], None]] = None,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Any = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
) -> dict[str, Any]:
    """
    流式调用并可选回调文本增量，返回完整 assistant message。

    @param messages 消息列表
    @param on_delta 文本增量回调
    @param tools 可选 tools
    @param tool_choice 工具策略或指定函数对象
    @param temperature 温度
    @param max_tokens 生成上限
    @param reasoning_effort 思考程度；None 则用聊天框配置
    @return assistant message
    @author Kai
    @date 2026/09/01 10:30
    """
    final: dict[str, Any] = {"role": "assistant", "content": ""}
    for event in iter_chat_completions(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    ):
        if event.get("type") == "delta" and on_delta:
            on_delta(str(event.get("content") or ""))
        elif event.get("type") == "message":
            final = event.get("message") or final
    return final


def extract_assistant_message(data: dict[str, Any]) -> dict[str, Any]:
    """
    从响应取出 assistant message（兼容 content / reasoning 字段）。

    @param data chat/completions 响应
    @return message 字典
    @author Kai
    @date 2026/08/05 15:20
    """
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("AI 响应无 choices")
    msg = choices[0].get("message") or {}
    if not isinstance(msg, dict):
        raise RuntimeError("AI message 格式异常")
    content = msg.get("content")
    if content is None or str(content).strip() == "":
        for key in ("reasoning_content", "reasoning", "text", "output"):
            alt = msg.get(key)
            if alt and str(alt).strip():
                msg = dict(msg)
                msg["content"] = str(alt)
                break
    if (not msg.get("content")) and choices[0].get("text"):
        msg = dict(msg)
        msg["content"] = str(choices[0].get("text"))
    return msg


def _strip_think_blocks(text: str) -> str:
    """
    去掉模型思考标签与常见包裹。

    @param text 原文
    @return 清洗后文本
    @author Kai
    @date 2026/08/05 15:20
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
    # 未闭合思考块：若后面还有 { 则从 JSON 起保留
    m = re.search(r"<think>", raw, flags=re.I)
    if m:
        brace = raw.find("{", m.start())
        if brace >= 0:
            raw = raw[brace:]
        else:
            raw = re.sub(r"<think>[\s\S]*$", "", raw, flags=re.I)
    return raw.strip()


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """
    从模型文本中提取第一个 JSON 对象（兼容 markdown / 思考标签 / 尾逗号）。

    @param text 模型输出
    @return 字典或 None
    @author Kai
    @date 2026/08/05 15:20
    """
    if not text:
        return None
    raw = _strip_think_blocks(text)
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()

    def _try_load(candidate: str) -> Optional[dict[str, Any]]:
        c = (candidate or "").strip()
        if not c:
            return None
        c = re.sub(r",\s*}", "}", c)
        c = re.sub(r",\s*]", "]", c)
        try:
            obj = json.loads(c)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
        if "'" in c and '"' not in c:
            try:
                obj = json.loads(c.replace("'", '"'))
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    direct = _try_load(raw)
    if direct:
        return direct

    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return _try_load(raw[start : i + 1])
    return None


def test_connection() -> tuple[bool, str]:
    """
    发送一句测试消息验证连通性。

    @return (成功, 说明)
    @author Kai
    @date 2026/08/05 14:15
    """
    try:
        data = chat_completions(
            [{"role": "user", "content": "Say this is a test!"}],
            temperature=0.0,
            max_tokens=32,
            reasoning_effort="none",
        )
        msg = extract_assistant_message(data)
        content = str(msg.get("content") or "").strip()
        return True, content[:200] or "OK"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
