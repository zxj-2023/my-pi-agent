"""统一数据模型：保证内部数据流通，屏蔽 provider 差异。"""

import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class TurnOutcome(str, Enum):
    """Provider 中立的单轮终止原因（对标 pig-llm）。"""

    COMPLETED = "completed"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    ABORTED = "aborted"
    PROVIDER_ERROR = "provider_error"
    UNKNOWN = "unknown"


_COMPLETED_REASONS = {
    "stop",
    "end_turn",
    "complete",
    "completed",
    "stop_sequence",
    "natural",
    "success",
    "done",
}
_TOOL_REASONS = {"tool_calls", "tool_use", "function_call", "function_calls"}
_LENGTH_REASONS = {
    "length",
    "max_tokens",
    "max_output_tokens",
    "model_length",
    "token_limit",
}
_FILTER_REASONS = {"content_filter", "safety", "blocked", "recitation", "prohibited"}
_ABORT_REASONS = {"aborted", "cancelled", "canceled", "interrupt", "interrupted"}
_ERROR_REASONS = {"error", "failed", "failure", "provider_error"}


def normalize_finish_reason(
    reason: str | None, has_tool_calls: bool = False
) -> TurnOutcome:
    """归一化各厂商私有 finish_reason 为中立枚举。"""
    if reason is None:
        return TurnOutcome.TOOL_CALLS if has_tool_calls else TurnOutcome.COMPLETED
    norm = reason.strip().lower().rsplit(".", maxsplit=1)[-1]
    if norm in _COMPLETED_REASONS:
        return TurnOutcome.TOOL_CALLS if has_tool_calls else TurnOutcome.COMPLETED
    if norm in _TOOL_REASONS:
        return TurnOutcome.TOOL_CALLS
    if norm in _LENGTH_REASONS:
        return TurnOutcome.LENGTH
    if norm in _FILTER_REASONS:
        return TurnOutcome.CONTENT_FILTER
    if norm in _ABORT_REASONS:
        return TurnOutcome.ABORTED
    if norm in _ERROR_REASONS:
        return TurnOutcome.PROVIDER_ERROR
    return TurnOutcome.TOOL_CALLS if has_tool_calls else TurnOutcome.UNKNOWN


class Message(BaseModel):
    """统一消息：role + content + 附加元数据（tool_calls / tool_call_id 等）。"""

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] | None = None


class ToolCallFunction(BaseModel):
    """tool_call 的 function 子对象（保留以兼容历史导入）。"""

    name: str
    arguments: str


class ToolCall(BaseModel):
    """统一结构化工具调用对象（对标 Tau / Pi）。

    参数在模型层完成反序列化，核心层直接消费字典，彻底告别四重 JSON 编解码。
    """

    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_wire_dict(cls, data: Any) -> Any:
        if isinstance(data, dict) and "function" in data and "name" not in data:
            fn = data.get("function")
            if isinstance(fn, dict):
                name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
            else:
                name = getattr(fn, "name", "")
                raw_args = getattr(fn, "arguments", "{}")
            error = None
            if isinstance(raw_args, str):
                try:
                    if raw_args.strip():
                        parsed = json.loads(raw_args)
                        if isinstance(parsed, dict):
                            args = parsed
                        else:
                            error = f"Tool arguments must be a dict, got {type(parsed).__name__}"
                            args = {}
                    else:
                        args = {}
                except Exception as exc:
                    args = {}
                    error = f"Malformed JSON arguments: {exc}"
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            return {
                "id": data.get("id", ""),
                "name": name,
                "args": args,
                "error": error,
            }
        return data

    def to_wire_dict(self) -> dict[str, Any]:
        """兼容 OpenAI wire 形状 dict（用于对外导出或与旧协议对接）。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.args, ensure_ascii=False),
            },
        }


class Response(BaseModel):
    """统一响应：文本 + 工具调用 + usage + reasoning。"""

    content: str
    model: str
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None

    @property
    def outcome(self) -> TurnOutcome:
        """中立化的终止状态。"""
        return normalize_finish_reason(self.finish_reason, bool(self.tool_calls))

    def to_message(
        self,
        role: Literal["system", "developer", "user", "assistant", "tool"] = "assistant",
        stop_reason: str | None = None,
    ) -> Message:
        """将模型层完整响应直接转换为标准 Message 实体，彻底消除调度层手动累加拼装。"""
        meta: dict[str, Any] = {}
        if self.tool_calls:
            meta["tool_calls"] = [
                tc.model_dump() if hasattr(tc, "model_dump") else tc
                for tc in self.tool_calls
            ]
        if self.usage:
            meta["usage"] = self.usage
        if self.reasoning_content:
            meta["reasoning_content"] = self.reasoning_content
        effective_stop = stop_reason or self.outcome.value
        if effective_stop:
            meta["stop_reason"] = effective_stop
        return Message(role=role, content=self.content, metadata=meta if meta else None)


class StreamChunk(BaseModel):
    """流式增量块：文本增量 + 末块携带完整 tool_calls 与终态已拼装好的 Response。"""

    content: str
    finish_reason: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: dict[str, int] | None = None
    metadata: dict[str, Any] | None = None
    response: Response | None = None

    @property
    def outcome(self) -> TurnOutcome | None:
        if self.finish_reason is None and not self.tool_calls:
            return None
        return normalize_finish_reason(self.finish_reason, bool(self.tool_calls))
