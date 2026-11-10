# pyright: reportIncompatibleVariableOverride=false
"""Codemode tool facade, output formatting, and session store integration.

Provides CodemodeTool for executing multi-tool JavaScript scripts within
an isolated Node.js sandbox, with format alignment to Pi's codemode specification.
"""

from __future__ import annotations

import json
import tempfile
from typing import TYPE_CHECKING, Any

from my_agent_core.codemode.bridge import CodemodeBridge, ScriptResult
from my_agent_core.codemode.declarations import generate_codemode_description
from my_agent_core.session.entries import CodemodeStoreEntry, CustomEntry
from my_agent_core.tools.core import Tool, ToolResult

if TYPE_CHECKING:
    from my_agent_core.registry import ToolRegistry
    from my_agent_core.session.session import Session


class CodemodeSourceError(ValueError):
    """Codemode 源代码格式或首行配置语法错误。"""


class CodemodeResult(ToolResult):
    """Codemode 工具执行结果包装，支持字符串与容器兼容操作。"""

    def __init__(
        self,
        ok: bool,
        content: str | None = None,
        data: Any = None,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
        terminate: bool = False,
    ) -> None:
        if content is not None:
            if ok:
                data = content if data is None else data
            else:
                error = content if error is None else error
        super().__init__(
            ok=ok,
            data=data,
            error=error,
            meta=meta or {},
            terminate=terminate,
        )

    @property
    def content(self) -> str:
        return str(self.data if self.ok else (self.error or ""))

    def __str__(self) -> str:
        return self.content

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.content == other
        return super().__eq__(other)

    def __contains__(self, item: Any) -> bool:
        return str(item) in self.content


def parse_options(
    code: str,
    default_max_output_tokens: int = 10000,
    default_timeout_ms: int | None = None,
) -> tuple[int, int | None]:
    """解析脚本首行的可选 // @options: 配置。

    规则：
    - 若出现 // @options:，必须严格位于第 1 行；位于第 2 行及以后立即抛出 CodemodeSourceError。
    - 仅允许 'max_output_tokens'（非负整数）与 'timeout_ms'（正整数）。
    """
    lines = code.splitlines()
    if not lines:
        return default_max_output_tokens, default_timeout_ms

    # 检查第 2 行及后续行是否包含 // @options:
    for line in lines[1:]:
        if "// @options:" in line:
            raise CodemodeSourceError("The // @options: line must be the first line of the input")

    line1 = lines[0].strip()
    if "// @options:" in line1 and not line1.startswith("// @options:"):
        raise CodemodeSourceError("The // @options: line must be the first line of the input")

    if not line1.startswith("// @options:"):
        return default_max_output_tokens, default_timeout_ms

    raw_json = line1[len("// @options:") :].strip()
    if not raw_json:
        raise CodemodeSourceError("The // @options: content must be a JSON object")

    try:
        options = json.loads(raw_json)
    except Exception as exc:
        raise CodemodeSourceError(f"Invalid JSON in // @options:: {exc}") from exc

    if not isinstance(options, dict):
        raise CodemodeSourceError("The // @options: content must be a JSON object")

    for key in options:
        if key not in ("max_output_tokens", "timeout_ms"):
            raise CodemodeSourceError(f"Unknown option '{key}' in // @options:")

    max_tokens = default_max_output_tokens
    if "max_output_tokens" in options:
        val = options["max_output_tokens"]
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise CodemodeSourceError("Option 'max_output_tokens' must be a non-negative integer")
        max_tokens = val

    timeout = default_timeout_ms
    if "timeout_ms" in options:
        val = options["timeout_ms"]
        if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
            raise CodemodeSourceError("Option 'timeout_ms' must be a positive integer")
        timeout = val

    return max_tokens, timeout


def format_script_output(result: ScriptResult) -> str:
    """按 Pi 原厂规范对脚本执行结果进行统一排版格式化。

    成功格式：
    Script completed (0.2s)
    ==> text 1/2 <==
    {text_1}

    ==> text 2/2 <==
    {text_2}

    <console_output>
    {lines}
    </console_output>

    失败格式：
    Script failed (0.0s)
    <console_output>
    {lines}
    </console_output>
    Script error:
    {result.error}
    """
    if result.ok:
        parts: list[str] = [f"Script completed ({result.wall_time:.1f}s)"]
        if len(result.text_items) > 1:
            sections: list[str] = []
            for i, item in enumerate(result.text_items, start=1):
                sections.append(f"==> text {i}/{len(result.text_items)} <==\n{item}")
            parts.append("\n\n".join(sections))
        elif len(result.text_items) == 1:
            parts.append(result.text_items[0])

        if result.console_lines:
            console_body = "\n".join(result.console_lines)
            parts.append(f"<console_output>\n{console_body}\n</console_output>")
        elif not result.text_items:
            parts.append("(no output)")

        # 头部与第一个内容块之间换行，后续内容块之间空行分隔
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return f"{parts[0]}\n{parts[1]}"
        # len >= 3: 包含 text 与 console
        return f"{parts[0]}\n{parts[1]}\n\n" + "\n\n".join(parts[2:])

    # 失败分支
    err_parts: list[str] = [f"Script failed ({result.wall_time:.1f}s)"]
    if result.console_lines:
        console_body = "\n".join(result.console_lines)
        err_parts.append(f"<console_output>\n{console_body}\n</console_output>")
    err_parts.append(f"Script error:\n{result.error or 'Unknown error'}")

    return "\n".join(err_parts)


def truncate_codemode_output(
    content: str,
    max_output_tokens: int = 10000,
) -> str:
    """根据 max_output_tokens 限制输出字符数（默认 ~40,000 字符），保留头部与尾部并落盘。"""
    max_chars = max_output_tokens * 4
    if len(content) <= max_chars:
        return content

    temp_path_str = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="codemode_output_",
            suffix=".log",
            delete=False,
        ) as tmp:
            tmp.write(content)
            temp_path_str = tmp.name
    except Exception:
        pass

    omitted_chars = len(content) - max_chars
    notice = f"\n\n[... {omitted_chars} characters omitted due to output length exceeding max_output_tokens ({max_output_tokens})"
    if temp_path_str:
        notice += f"; full output saved to {temp_path_str}"
    notice += " ...]\n\n"

    avail = max_chars - len(notice)
    if avail <= 0:
        return content[:max_chars]

    head_len = avail // 2
    tail_len = avail - head_len

    return content[:head_len] + notice + content[-tail_len:]


def get_session_store_snapshot(session: Any | None) -> dict[str, Any]:
    """沿当前会话分支自根至叶折叠提取最新 store 状态快照。"""
    if session is None:
        return {}

    tree = getattr(session, "tree", None)
    if tree is None:
        return {}

    path_entries = tree.get_current_path() if hasattr(tree, "get_current_path") else []
    store: dict[str, Any] = {}
    for entry in path_entries:
        if isinstance(entry, CodemodeStoreEntry):
            store.update(entry.data)
        elif isinstance(entry, CustomEntry) and entry.custom_type == "codemode-store":
            store.update(entry.data)
        elif getattr(entry, "type", None) in ("codemode-store", "codemode_store", "codemodeStore"):
            data = getattr(entry, "data", {})
            if isinstance(data, dict):
                store.update(data)
    return store


class CodemodeTool(Tool):
    """Codemode 工具门面：承接大模型编写的 JavaScript 源码并在 Node.js 沙箱中调度执行。"""

    def __init__(
        self,
        registry: ToolRegistry,
        session: Session | None = None,
        bridge: CodemodeBridge | None = None,
        default_max_output_tokens: int = 10000,
        default_timeout_ms: int | None = None,
    ) -> None:
        self.registry = registry
        self.session = session
        self.bridge = bridge or CodemodeBridge()
        self.default_max_output_tokens = default_max_output_tokens
        self.default_timeout_ms = default_timeout_ms
        self._description = ""

        super().__init__(
            func=self._run,
            name="codemode",
            description="",
            is_parallel_safe=False,
        )

    @property
    def description(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        if self.registry is not None and hasattr(self.registry, "_tools"):
            tools_list = [t for t in self.registry._tools.values() if t.name != self.name]
            return generate_codemode_description(tools_list)
        return self._description

    @description.setter
    def description(self, val: str) -> None:
        self._description = val

    async def _run(self, code: str, signal: Any | None = None) -> ToolResult:
        """解析参数、拉取会话状态、执行沙箱脚本并格式化输出（严格 Never-Throw）。"""
        try:
            max_output_tokens, timeout_ms = parse_options(
                code,
                default_max_output_tokens=self.default_max_output_tokens,
                default_timeout_ms=self.default_timeout_ms,
            )
        except CodemodeSourceError as exc:
            formatted = format_script_output(ScriptResult(ok=False, wall_time=0.0, error=f"CodemodeSourceError: {exc}"))
            return CodemodeResult(ok=False, content=formatted)
        except Exception as exc:
            formatted = format_script_output(
                ScriptResult(ok=False, wall_time=0.0, error=f"Error parsing options: {exc}")
            )
            return CodemodeResult(ok=False, content=formatted)

        current_store = get_session_store_snapshot(self.session)

        async def _tool_executor(name: str, args: dict[str, Any]) -> Any:
            return await self.registry.execute_tool(name=name, args=args, signal=signal)

        try:
            result = await self.bridge.execute_script(
                code=code,
                store=current_store,
                tool_executor=_tool_executor,
                timeout_ms=timeout_ms,
                max_output_tokens=max_output_tokens,
                signal=signal,
            )
        except Exception as exc:
            formatted = format_script_output(
                ScriptResult(ok=False, wall_time=0.0, error=f"Sandbox execution failed: {exc}")
            )
            return CodemodeResult(ok=False, content=formatted)

        # 会话状态持久化：仅当执行成功且产生了写入时才保存
        if self.session is not None and result.ok and result.store_writes:
            try:
                if hasattr(self.session, "add_custom_entry"):
                    self.session.add_custom_entry("codemode-store", result.store_writes)
                elif hasattr(self.session, "append_entry"):
                    entry = CodemodeStoreEntry(
                        parent_id=getattr(self.session.tree, "current_id", None),
                        data=result.store_writes,
                    )
                    self.session.append_entry(entry)
            except Exception:
                pass  # Never-Throw 保证

        raw_output = format_script_output(result)
        truncated_output = truncate_codemode_output(raw_output, max_output_tokens=max_output_tokens)

        return CodemodeResult(
            ok=result.ok,
            content=truncated_output,
            meta={
                "wall_time": result.wall_time,
                "store_writes": result.store_writes,
            },
        )


def make_codemode_tool(
    registry: ToolRegistry,
    session: Session | None = None,
    bridge: CodemodeBridge | None = None,
    **kwargs: Any,
) -> Tool:
    """创建并装配 CodemodeTool 工具门面。"""
    return CodemodeTool(
        registry=registry,
        session=session,
        bridge=bridge,
        **kwargs,
    )


__all__ = [
    "CodemodeResult",
    "CodemodeSourceError",
    "CodemodeTool",
    "format_script_output",
    "get_session_store_snapshot",
    "make_codemode_tool",
    "parse_options",
    "truncate_codemode_output",
]
