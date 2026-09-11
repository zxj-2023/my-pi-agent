"""统一数据模型：保证内部数据流通，屏蔽 provider 差异。"""

from typing import Any, Literal

from pydantic import BaseModel


class Message(BaseModel):
    """统一消息：role + content + 附加元数据（tool_calls / tool_call_id 等）。"""

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] | None = None


class ToolCallFunction(BaseModel):
    """tool_call 的 function 子对象（arguments 是 JSON 字符串，wire 形状）。"""

    name: str
    arguments: str


class ToolCall(BaseModel):
    """统一 OpenAI 形状 tool_call：三处构造共用一处模型（防形状漂移）。

    出方向：openai/deepseek 的流式聚合与提取、anthropic 的 block 翻译都经此构造，
    model_dump() 产出 {'id', 'type': 'function', 'function': {name, arguments}}。
    """

    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class Response(BaseModel):
    """统一响应：文本 + 工具调用 + usage + reasoning。"""

    content: str
    model: str
    tool_calls: list[dict[str, Any]] | None = None
    reasoning_content: str | None = None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None

    def to_message(
        self,
        role: Literal["system", "developer", "user", "assistant", "tool"] = "assistant",
        stop_reason: str | None = None,
    ) -> Message:
        """将模型层完整响应直接转换为标准 Message 实体，彻底消除调度层手动累加拼装。"""
        meta: dict[str, Any] = {}
        if self.tool_calls:
            meta["tool_calls"] = self.tool_calls
        if self.usage:
            meta["usage"] = self.usage
        if self.reasoning_content:
            meta["reasoning_content"] = self.reasoning_content
        effective_stop = stop_reason or self.finish_reason
        if effective_stop:
            meta["stop_reason"] = effective_stop
        return Message(role=role, content=self.content, metadata=meta if meta else None)


class StreamChunk(BaseModel):
    """流式增量块：文本增量 + 末块携带完整 tool_calls 与终态已拼装好的 Response。"""

    content: str
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    metadata: dict[str, Any] | None = None  # 承载流式 reasoning 等附加信息
    response: Response | None = (
        None  # 流式终态携带的已由模型层拼装完毕的完整 Response 实体
    )
