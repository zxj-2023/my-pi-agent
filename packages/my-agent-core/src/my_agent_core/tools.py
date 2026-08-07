"""工具声明与分发 —— 上行翻译层（类模式）。

- Tool 类：从函数名、docstring、类型标注自动生成发给模型的 JSON schema
  （pydantic 驱动），并提供校验执行与直接调用
- tool() 装饰器：支持 @tool 与 @tool(name=..., description=..., params_model=...)
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, ValidationError, create_model


@dataclass
class ToolResult:
    """工具执行结果：成功/失败 + 数据或错误消息。"""

    ok: bool
    data: Any = None
    error: str | None = None

    def serialize(self) -> str:
        """转成写入 messages 的字符串。失败时返回错误文本。"""
        if self.ok:
            return str(self.data)
        return self.error or "Unknown error"


class ToolBlocked(Exception):
    """before_tool 拦截工具调用时抛出；reason 会变成错误结果喂回模型。"""


class Tool:
    """一个可被模型调用的工具：函数本体 + 参数模型 + 协议转换。"""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        params_model: type[BaseModel] | None = None,
    ):
        self.func = func
        self.name = name or func.__name__
        self.description = description or (inspect.getdoc(func) or "")
        self.params_model = params_model or self._create_params_model(func)

    def _create_params_model(self, func: Callable[..., Any]) -> type[BaseModel]:
        """从函数签名动态建模（pydantic create_model）。"""
        hints = get_type_hints(func)
        fields: dict[str, Any] = {}
        for param_name, param in inspect.signature(func).parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                raise TypeError(
                    f"tool '{func.__name__}': parameter '{param_name}' is "
                    "*args/**kwargs, which is not supported（不支持）"
                )
            if param_name not in hints:
                raise TypeError(
                    f"tool '{func.__name__}': parameter '{param_name}' "
                    "has no type annotation（没有类型标注）"
                )
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (hints[param_name], default)

        try:
            model = create_model(
                f"{func.__name__}_Args",
                __config__=ConfigDict(extra="forbid"),   # 多余参数 → 校验错误
                **fields,
            )
            return model
        except Exception as exc:   # 无法建模的类型 → 装饰时明确失败
            raise TypeError(
                f"tool '{func.__name__}': cannot build parameter schema: {exc}"
            ) from exc

    def to_openai_schema(self) -> dict[str, Any]:
        """生成 OpenAI tools 参数（pydantic 原始 schema）。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params_model.model_json_schema(),
            },
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """校验 + 执行，永不抛（错误全部转 ToolResult）。"""
        try:
            validated = self.params_model.model_validate(args)
        except ValidationError as exc:
            return ToolResult(ok=False, error=str(exc))
        try:
            result = self.func(**validated.model_dump())
        except Exception as exc:  # 工具错误 → 消息，喂回模型
            return ToolResult(ok=False, error=f"Error executing tool '{self.name}': {exc}")
        return ToolResult(ok=True, data=result)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """直接调用工具函数本体。"""
        return self.func(*args, **kwargs)


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    params_model: type[BaseModel] | None = None,
):
    """@tool 装饰器：支持 @tool 与 @tool(name=..., description=..., params_model=...)。

    schema 生成由 pydantic 驱动：参数类型支持 pydantic 全集（list/dict/Optional/嵌套等），
    允许默认值；无标注参数与 *args/**kwargs 在装饰时抛 TypeError（明确失败）。
    """

    def decorator(f: Callable[..., Any]) -> Tool:
        return Tool(func=f, name=name, description=description, params_model=params_model)

    if func is None:
        return decorator
    return decorator(func)
