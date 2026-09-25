"""工具声明与分发 —— 核心模型与装饰器（Pydantic 驱动）。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, get_type_hints, overload

from pydantic import BaseModel, ConfigDict, ValidationError, create_model


@dataclass
class ToolResult:
    """工具执行结果：成功/失败 + 数据或错误消息 + 结构化元数据。"""

    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    terminate: bool = False

    def serialize(self) -> str:
        """转成写入 messages 的字符串。失败时返回错误文本。"""
        if self.ok:
            return str(self.data)
        return self.error or "Unknown error"


_FRAMEWORK_RESERVED_PARAMS: frozenset[str] = frozenset({"on_update", "signal", "tool_call_id"})


class Tool:
    """一个可被模型调用的工具：函数本体 + 参数模型/原始Schema + 协议转换 + 超时与并发配置。"""

    func: Callable[..., Any]
    name: str
    description: str
    prompt_snippet: str
    prompt_guidelines: list[str]
    raw_schema: dict[str, Any] | None
    timeout: float | None
    is_parallel_safe: bool
    is_async: bool
    params_model: type[BaseModel] | None

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        prompt_snippet: str | None = None,
        prompt_guidelines: Sequence[str] | None = None,
        params_model: type[BaseModel] | None = None,
        raw_schema: dict[str, Any] | None = None,
        timeout: float | None = None,
        is_parallel_safe: bool = False,
    ):
        self.func = func
        self.name = name or func.__name__
        self.description = description or (inspect.getdoc(func) or "")
        self.prompt_snippet = prompt_snippet if prompt_snippet is not None else self._extract_summary(self.description)
        self.prompt_guidelines = list(prompt_guidelines) if prompt_guidelines else []
        self.raw_schema = raw_schema
        self.timeout = timeout
        self.is_parallel_safe = is_parallel_safe
        self.is_async = inspect.iscoroutinefunction(func)
        sig = inspect.signature(func)
        self._accepts_on_update = "on_update" in sig.parameters
        self._accepts_signal = "signal" in sig.parameters
        self._accepts_tool_call_id = "tool_call_id" in sig.parameters
        self.params_model = params_model or (None if raw_schema else self._create_params_model(func))

    @staticmethod
    def _extract_summary(desc: str) -> str:
        """从 description 中安全提取第一句作为 prompt_snippet 极简概要。"""
        if not desc:
            return ""
        line = desc.strip().split("\n")[0].strip()
        if not line:
            return ""
        for sep in (". ", "。", "."):
            if sep in line:
                line = line.split(sep)[0].strip()
                break
        return line

    def _create_params_model(self, func: Callable[..., Any]) -> type[BaseModel]:
        """从函数签名动态建模（pydantic create_model）。"""
        hints = get_type_hints(func)
        fields: dict[str, Any] = {}
        for param_name, param in inspect.signature(func).parameters.items():
            if param_name in _FRAMEWORK_RESERVED_PARAMS:
                continue
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise TypeError(
                    f"tool '{func.__name__}': parameter '{param_name}' is "
                    "*args/**kwargs, which is not supported（不支持）"
                )
            if param_name not in hints:
                raise TypeError(
                    f"tool '{func.__name__}': parameter '{param_name}' has no type annotation（没有类型标注）"
                )
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (hints[param_name], default)

        try:
            model = create_model(
                f"{func.__name__}_Args",
                __config__=ConfigDict(extra="forbid"),  # 多余参数 → 校验错误
                **fields,
            )
            return model
        except Exception as exc:  # 无法建模的类型 → 装饰时明确失败
            raise TypeError(f"tool '{func.__name__}': cannot build parameter schema: {exc}") from exc

    def to_openai_schema(self) -> dict[str, Any]:
        """生成 OpenAI tools 参数。"""
        if self.raw_schema is not None:
            params = self.raw_schema
        elif self.params_model is not None:
            params = self.params_model.model_json_schema()
        else:
            params = {}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }

    async def execute(
        self,
        args: dict[str, Any],
        signal: Any | None = None,
        on_update: Callable[[Any], None] | None = None,
        tool_call_id: str | None = None,
    ) -> ToolResult:
        """校验 + 执行，永不抛（错误全部转 ToolResult）。自动适配 sync/async 函数。"""
        accepting_updates = True

        def guarded_on_update(partial: Any) -> None:
            if accepting_updates and on_update is not None:
                on_update(partial)

        extra_kwargs: dict[str, Any] = {}
        if self._accepts_on_update:
            extra_kwargs["on_update"] = guarded_on_update
        if self._accepts_signal:
            extra_kwargs["signal"] = signal
        if self._accepts_tool_call_id and tool_call_id is not None:
            extra_kwargs["tool_call_id"] = tool_call_id

        if self.params_model is not None:
            try:
                validated = self.params_model.model_validate(args)
            except ValidationError as exc:
                return ToolResult(ok=False, error=str(exc))
            kwargs = {**validated.model_dump(), **extra_kwargs}

            def func_call() -> Any:
                return self.func(**kwargs)

            async def async_func_call() -> Any:
                return await self.func(**kwargs)
        else:

            def func_call() -> Any:
                if extra_kwargs:
                    return self.func(args, **extra_kwargs)
                return self.func(args)

            async def async_func_call() -> Any:
                if extra_kwargs:
                    return await self.func(args, **extra_kwargs)
                return await self.func(args)

        try:
            if self.is_async:
                result = await async_func_call()
            else:
                result = await asyncio.to_thread(func_call)
        except Exception as exc:  # 工具错误 → 消息，喂回模型
            return ToolResult(ok=False, error=f"Error executing tool '{self.name}': {exc}")
        finally:
            accepting_updates = False

        if isinstance(result, ToolResult):
            return result
        return ToolResult(ok=True, data=result)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """直接调用工具函数本体。"""
        return self.func(*args, **kwargs)


@overload
def tool(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    prompt_snippet: str | None = None,
    prompt_guidelines: Sequence[str] | None = None,
    params_model: type[BaseModel] | None = None,
    raw_schema: dict[str, Any] | None = None,
    timeout: float | None = None,
    is_parallel_safe: bool = False,
) -> Tool: ...


@overload
def tool(
    func: None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    prompt_snippet: str | None = None,
    prompt_guidelines: Sequence[str] | None = None,
    params_model: type[BaseModel] | None = None,
    raw_schema: dict[str, Any] | None = None,
    timeout: float | None = None,
    is_parallel_safe: bool = False,
) -> Callable[[Callable[..., Any]], Tool]: ...


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    prompt_snippet: str | None = None,
    prompt_guidelines: Sequence[str] | None = None,
    params_model: type[BaseModel] | None = None,
    raw_schema: dict[str, Any] | None = None,
    timeout: float | None = None,
    is_parallel_safe: bool = False,
) -> Tool | Callable[[Callable[..., Any]], Tool]:
    """@tool 装饰器：支持 @tool 与 @tool(name=..., description=..., params_model=...)。

    schema 生成由 pydantic 驱动：参数类型支持 pydantic 全集（list/dict/Optional/嵌套等），
    允许默认值；无标注参数与 *args/**kwargs 在装饰时抛 TypeError（明确失败）。
    """

    def decorator(f: Callable[..., Any]) -> Tool:
        return Tool(
            func=f,
            name=name,
            description=description,
            prompt_snippet=prompt_snippet,
            prompt_guidelines=prompt_guidelines,
            params_model=params_model,
            raw_schema=raw_schema,
            timeout=timeout,
            is_parallel_safe=is_parallel_safe,
        )

    if func is None:
        return decorator
    return decorator(func)
