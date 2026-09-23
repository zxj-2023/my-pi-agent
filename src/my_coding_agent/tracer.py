"""tracer: 面向事件驱动的可观察性与调试诊断跟踪器。

记录毫秒级不可变生命周期事件，计算调用耗时，脱敏敏感参数，并持久化到 debug.log。
"""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, TextIO

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
from my_coding_agent.serialization import serialize_event, serialize_message

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PATTERN = re.compile(r"(?:api_?key|token|secret|password|auth)", re.IGNORECASE)


def redact_sensitive_data(data: Any) -> Any:
    """递归对字典或列表中的敏感字段（如 api_key, token 等）执行脱敏替换。"""
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for k, v in data.items():
            if SENSITIVE_KEY_PATTERN.search(str(k)):
                cleaned[k] = "***REDACTED***"
            else:
                cleaned[k] = redact_sensitive_data(v)
        return cleaned
    elif isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]
    return data


class DebugEventTracer:
    """监听不可变事实事件流，输出结构化毫秒级调试日志与机器可读事件流 (双轨制)。"""

    def __init__(
        self,
        log_path: Path | str | None = None,
        events_path: Path | str | None = None,
        console_output: bool = False,
    ) -> None:
        self.console_output = console_output
        self.log_path: Path | None = None
        self.events_path: Path | None = None
        self._file: TextIO | None = None
        self._events_file: TextIO | None = None
        self._tool_starts: dict[str, float] = {}
        self._turn_start_ts: float = 0.0
        self._llm_start_ts: float = 0.0

        if log_path is not None or events_path is not None:
            self.rebind(log_path=log_path, events_path=events_path)

    def rebind(
        self,
        log_path: Path | str | None = None,
        events_path: Path | str | None = None,
    ) -> None:
        """安全刷新并关闭旧文件句柄，重新绑定至新会话的日志路径。"""
        self.close()
        self._tool_starts.clear()
        self._turn_start_ts = 0.0
        self._llm_start_ts = 0.0

        if log_path is not None:
            p = Path(log_path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            self.log_path = p
            try:
                self._file = open(p, "a", encoding="utf-8")  # noqa: SIM115
            except OSError:
                self._file = None
        else:
            self.log_path = None

        if events_path is not None:
            ep = Path(events_path).resolve()
            ep.parent.mkdir(parents=True, exist_ok=True)
            self.events_path = ep
            try:
                self._events_file = open(ep, "a", encoding="utf-8")  # noqa: SIM115
            except OSError:
                self._events_file = None
        else:
            self.events_path = None

    def _format_ts(self, ts: float) -> str:
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _write_line(self, line: str) -> None:
        if self._file and not self._file.closed:
            try:
                self._file.write(line + "\n")
                self._file.flush()
            except Exception:
                pass
        if self.console_output:
            print(line, file=sys.stderr)

    def _write_event(self, event: Event) -> None:
        """向 events.jsonl 写入一条序列化的机器可读事件。"""
        if self._events_file and not self._events_file.closed:
            try:
                payload = serialize_event(event)
                safe_payload = redact_sensitive_data(payload)
                self._events_file.write(json.dumps(safe_payload, ensure_ascii=False) + "\n")
                self._events_file.flush()
            except Exception:
                pass

    def __call__(self, event: Event) -> None:
        """事件旁路广播回调。"""
        # 忽略高频打字机 Token 碎片与工具输出增量，避免磁盘风暴
        if isinstance(event, (MessageUpdate, ToolExecutionUpdate)):
            return

        ts_str = self._format_ts(event.timestamp)
        self._write_event(event)

        if isinstance(event, AgentStart):
            prompt_preview = (event.user_input or "").strip().splitlines()[0][:80] if event.user_input else ""
            self._write_line(f"[{ts_str}] [AGENT_START] prompt={json.dumps(prompt_preview, ensure_ascii=False)}")

        elif isinstance(event, TurnStart):
            self._turn_start_ts = event.timestamp
            self._llm_start_ts = event.timestamp
            self._write_line(f"[{ts_str}] [TURN_START] iteration={event.iteration}")

        elif isinstance(event, MessageStart):
            role = getattr(event.message, "role", "unknown")
            if role == "assistant":
                self._llm_start_ts = event.timestamp

        elif isinstance(event, MessageEnd):
            role = getattr(event.message, "role", "unknown")
            if role == "assistant":
                try:
                    duration_ms = int((event.timestamp - (self._llm_start_ts or event.timestamp)) * 1000)
                except (ValueError, TypeError):
                    duration_ms = 0
                meta = getattr(event.message, "metadata", None) or {}
                usage = meta.get("usage") or {}
                in_tok = usage.get("prompt_tokens") or usage.get("input") or 0
                out_tok = usage.get("completion_tokens") or usage.get("output") or 0
                self._write_line(
                    f"[{ts_str}] [LLM_RESPONSE] duration={duration_ms}ms in_tokens={in_tok} out_tokens={out_tok}"
                )

        elif isinstance(event, ToolExecutionStart):
            self._tool_starts[event.tool_call_id] = event.timestamp
            safe_args = redact_sensitive_data(event.args or {})
            args_str = json.dumps(safe_args, ensure_ascii=False)
            if len(args_str) > 200:
                args_str = args_str[:200] + "..."
            self._write_line(
                f"[{ts_str}] [TOOL_CALL_START] tool={event.tool_name} id={event.tool_call_id} args={args_str}"
            )

        elif isinstance(event, ToolExecutionEnd):
            start = self._tool_starts.pop(event.tool_call_id, event.timestamp)
            try:
                cost_ms = int((event.timestamp - start) * 1000)
            except (ValueError, TypeError):
                cost_ms = 0
            status = "ERROR" if event.is_error else "OK"
            res_preview = str(event.result or "").strip().splitlines()[0][:80] if event.result else ""
            self._write_line(
                f"[{ts_str}] [TOOL_CALL_END] tool={event.tool_name} id={event.tool_call_id} status={status} duration={cost_ms}ms result={json.dumps(res_preview, ensure_ascii=False)}"
            )

        elif isinstance(event, ContextCompacted):
            self._write_line(
                f"[{ts_str}] [COMPACT] before={event.tokens_before} after={event.tokens_after} summarized={event.summarized_count}"
            )

        elif isinstance(event, ToolsChanged):
            self._write_line(f"[{ts_str}] [TOOLS_CHANGED] action={event.action} name={event.name}")

        elif isinstance(event, TurnEnd):
            try:
                turn_cost_ms = int((event.timestamp - (self._turn_start_ts or event.timestamp)) * 1000)
            except (ValueError, TypeError):
                turn_cost_ms = 0
            self._write_line(f"[{ts_str}] [TURN_END] duration={turn_cost_ms}ms")

        elif isinstance(event, AgentEnd):
            self._write_line(f"[{ts_str}] [AGENT_END] stop_reason={event.stop_reason} iterations={event.iterations}\n")

    def flush(self) -> None:
        if self._file and not self._file.closed:
            with contextlib.suppress(Exception):
                self._file.flush()
        if self._events_file and not self._events_file.closed:
            with contextlib.suppress(Exception):
                self._events_file.flush()

    def close(self) -> None:
        if self._file and not self._file.closed:
            with contextlib.suppress(Exception):
                self._file.flush()
                self._file.close()
            self._file = None
        if self._events_file and not self._events_file.closed:
            with contextlib.suppress(Exception):
                self._events_file.flush()
                self._events_file.close()
            self._events_file = None


def export_debug_dump(agent: Any, output_path: Path | str) -> dict[str, Any]:
    """导出当前 Agent 瞬时运行态快照（对标 Pi /debug 命令）。"""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    inner = getattr(agent, "agent", agent)
    model = getattr(inner, "model", "default")
    system_prompt = getattr(inner, "system_prompt", "")
    messages = [serialize_message(m) for m in getattr(inner, "messages", []) if getattr(m, "role", "") != "system"]

    registered_tools = []
    reg = getattr(inner, "registry", None)
    if reg is not None:
        if isinstance(reg, dict):
            registered_tools = list(reg.keys())
        elif hasattr(reg, "tools"):
            registered_tools = list(getattr(reg, "tools", {}).keys())
        elif hasattr(reg, "list"):
            registered_tools = [t.name if hasattr(t, "name") else str(t) for t in reg.list()]

    data: dict[str, Any] = {
        "timestamp": datetime.datetime.now().isoformat(),
        "model": model,
        "workspace": str(getattr(agent, "workspace", ".")),
        "system_prompt": system_prompt,
        "registered_tools": registered_tools,
        "messages": messages,
    }

    tmp_file = out_file.with_name(f"{out_file.name}.tmp")
    tmp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(out_file)

    return data
