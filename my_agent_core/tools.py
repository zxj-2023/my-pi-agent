"""工具声明与分发 —— 上行翻译层。

- @tool 装饰器：从函数名、docstring、类型标注自动生成发给模型的 JSON schema
- schemas_for：把 Tool 列表包装成 OpenAI API 要求的 tools 参数格式
- call_tool：执行单个工具调用；任何错误都转成描述性字符串回给模型，永不抛出
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, create_model


@dataclass
class Tool:
    """一个可被模型调用的工具：函数本体 + 发给模型的 JSON schema + 参数模型。"""

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    model: type[BaseModel]   # pydantic 参数模型：schema 生成与运行期校验共用


def tool(func: Callable[..., Any]) -> Tool:
    """@tool 装饰器：从函数的名字、docstring、签名推导 Tool。

    schema 生成由 pydantic 驱动：参数类型支持 pydantic 全集
    （list/dict/Optional/嵌套等），允许默认值；无标注参数与
    *args/**kwargs 在装饰时抛 TypeError（明确失败）。
    """
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
        parameters = _clean_schema(model.model_json_schema())
    except Exception as exc:   # 无法建模的类型 → 装饰时明确失败
        raise TypeError(
            f"tool '{func.__name__}': cannot build parameter schema: {exc}"
        ) from exc

    return Tool(
        name=func.__name__,
        description=inspect.getdoc(func) or "",
        parameters=parameters,
        func=func,
        model=model,
    )


def _clean_schema(schema: Any) -> Any:
    """递归删除 pydantic 生成的各级 title 键（对模型是纯噪音）。"""
    if isinstance(schema, dict):
        cleaned = {k: _clean_schema(v) for k, v in schema.items() if k != "title"}
        # 删除 pydantic 的 additionalProperties（ConfigDict(extra="forbid") 产生）
        if cleaned.get("additionalProperties") is False:
            cleaned.pop("additionalProperties")
        return cleaned
    if isinstance(schema, list):
        return [_clean_schema(item) for item in schema]
    return schema


def schemas_for(tools: list[Tool]) -> list[dict[str, Any]]:
    """生成 OpenAI API 的 tools 参数"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def call_tool(tool_call: Any, tools_by_name: dict[str, Tool]) -> str:
    """执行单个 tool_call。任何错误都转成描述性字符串，永不抛出。"""
    name = tool_call.function.name
    target = tools_by_name.get(name)
    if target is None:
        available = ", ".join(sorted(tools_by_name))
        return f"Unknown tool '{name}'. Available: {available}"

    try:
        args = json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        return f"Invalid JSON arguments for tool '{name}': {exc}"

    try:
        result = target.func(**args)
    except Exception as exc:  # 工具错误 → 消息，喂回模型
        return f"Error executing tool '{name}': {exc}"

    return str(result)
