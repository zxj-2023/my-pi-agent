"""RPC 通信与事件序列化协议层。

提供对标 Pi 规范的 UUIDv7 唯一标识符生成、Message 实体序列化以及 AgentEvent JSON 序列化功能。
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    ContextCompacted,
    Event,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolsChanged,
    TurnEnd,
    TurnStart,
)
from my_agent_llm import Message


def uuid7_str() -> str:
    """生成符合 RFC 9562 规范的 UUIDv7 字符串（基于毫秒时间戳保序）。"""
    try:
        timestamp_ms = int(time.time() * 1000)
    except Exception:
        timestamp_ms = 0
    rand = int.from_bytes(os.urandom(10), "big")
    uuid_int = (
        ((timestamp_ms & 0xFFFFFFFFFFFF) << 80)
        | (0x7 << 76)
        | (((rand >> 62) & 0x0FFF) << 64)
        | (0x2 << 62)
        | (rand & 0x3FFFFFFFFFFFFFFF)
    )
    return str(uuid.UUID(int=uuid_int))


def serialize_message(m: Message) -> dict[str, Any]:
    """将内部 Message 实体转为标准 JSON 字典，保留 role、content 与关键 metadata (tool_calls / tool_call_id 等)。"""
    md: dict[str, Any] = {}
    if m.metadata:
        for k, v in m.metadata.items():
            if k == "tool_calls" and isinstance(v, list):
                serialized_tcs = []
                for tc in v:
                    if hasattr(tc, "model_dump"):
                        serialized_tcs.append(tc.model_dump())
                    elif isinstance(tc, dict):
                        serialized_tcs.append(tc)
                    else:
                        serialized_tcs.append(str(tc))
                md[k] = serialized_tcs
            elif hasattr(v, "model_dump"):
                md[k] = v.model_dump()
            elif isinstance(v, (str, int, float, bool, list, dict)) or v is None:
                md[k] = v
            else:
                md[k] = str(v)
    return {
        "role": m.role,
        "content": m.content,
        "metadata": md,
    }


def serialize_event(event: Event, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """将 Python 内部不可变事实事件序列化为对标 Pi AgentEvent 规范的 JSON 字典。"""
    if isinstance(event, AgentStart):
        return {
            "type": "agent_start",
            "system_prompt": event.system_prompt,
            "user_input": event.user_input,
        }
    elif isinstance(event, AgentEnd):
        res: dict[str, Any] = {
            "type": "agent_end",
            "iterations": event.iterations,
            "stop_reason": event.stop_reason,
            "final_text": event.final_text or "",
        }
        if stats:
            res.update(stats)
        return res
    elif isinstance(event, TurnStart):
        return {
            "type": "turn_start",
            "iteration": event.iteration,
        }
    elif isinstance(event, TurnEnd):
        res = {
            "type": "turn_end",
        }
        if stats:
            res.update(stats)
        return res
    elif isinstance(event, MessageStart):
        msg = event.message
        return {
            "type": "message_start",
            "message": {
                "role": msg.role,
                "content": msg.content or "",
            },
        }
    elif isinstance(event, MessageUpdate):
        msg = event.message
        chunk: Any = event.chunk
        delta_text = ""
        delta_thinking = ""
        if chunk is not None:
            delta_text = getattr(chunk, "content", None) or getattr(chunk, "text", "") or ""
            reasoning = getattr(chunk, "reasoning_content", None)
            if not reasoning and getattr(chunk, "metadata", None) and isinstance(chunk.metadata, dict):
                reasoning = chunk.metadata.get("reasoning_content")
            delta_thinking = str(reasoning) if reasoning else ""

        return {
            "type": "message_update",
            "message": {
                "role": msg.role,
                "content": msg.content or "",
            },
            "delta": delta_text,
            "reasoning_delta": delta_thinking,
        }
    elif isinstance(event, MessageEnd):
        msg = event.message
        meta = getattr(msg, "metadata", None) or {}
        usage = meta.get("usage")
        out: dict[str, Any] = {
            "type": "message_end",
            "message": {
                "role": msg.role,
                "content": msg.content or "",
                "metadata": meta,
            },
        }
        if usage:
            out["usage"] = usage
        if stats:
            out.update(stats)
        return out
    elif isinstance(event, ToolExecutionStart):
        return {
            "type": "tool_execution_start",
            "toolCallId": event.tool_call_id,
            "toolName": event.tool_name,
            "args": event.args,
        }
    elif isinstance(event, ToolExecutionUpdate):
        return {
            "type": "tool_execution_update",
            "toolCallId": event.tool_call_id,
            "toolName": event.tool_name,
            "partialResult": event.partial_result,
        }
    elif isinstance(event, ToolExecutionEnd):
        return {
            "type": "tool_execution_end",
            "toolCallId": event.tool_call_id,
            "toolName": event.tool_name,
            "result": event.result,
            "isError": event.is_error,
        }
    elif isinstance(event, ContextCompacted):
        return {
            "type": "context_compacted",
            "tokensBefore": event.tokens_before,
            "tokensAfter": event.tokens_after,
            "summarizedCount": event.summarized_count,
        }
    elif isinstance(event, ToolsChanged):
        return {
            "type": "tools_changed",
            "action": event.action,
            "name": event.name,
        }

    return {"type": type(event).__name__.lower()}
