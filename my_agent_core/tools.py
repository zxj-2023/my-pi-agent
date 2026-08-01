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

# Python 类型标注 → JSON Schema 类型映射表（装饰器的核心机密）
TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
}


@dataclass
class Tool:
    """一个可被模型调用的工具：函数本体 + 发给模型的 JSON schema。"""

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]


def tool(func: Callable[..., Any]) -> Tool:
    """@tool 装饰器：从函数的名字、docstring、签名推导 Tool。

    - 参数必须带 TYPE_MAP 内的类型标注，否则装饰时抛 TypeError
    - 不支持默认值参数（保持 schema 最简，明确失败）
    - 零参数合法：properties == {}，required == []
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    hints = get_type_hints(func)
    for param_name, param in inspect.signature(func).parameters.items():
        if param.default is not inspect.Parameter.empty:
            raise TypeError(
                f"tool '{func.__name__}': parameter '{param_name}' has a default "
                "value, which is not supported (keep the schema minimal)"
            )
        json_type = TYPE_MAP.get(hints.get(param_name))
        if json_type is None:
            supported = ", ".join(t.__name__ for t in TYPE_MAP)
            raise TypeError(
                f"tool '{func.__name__}': parameter '{param_name}' has annotation "
                f"{hints.get(param_name)!r}; supported types: {supported}"
            )
        properties[param_name] = {"type": json_type}
        required.append(param_name)

    return Tool(
        name=func.__name__,
        description=inspect.getdoc(func) or "",
        parameters={"type": "object", "properties": properties, "required": required},
        func=func,
    )


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
