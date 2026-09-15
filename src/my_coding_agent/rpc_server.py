from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, TextIO

from dotenv import find_dotenv, load_dotenv

if sys.platform == "win32":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure_fn = getattr(stream, "reconfigure", None)
        if callable(reconfigure_fn):
            reconfigure_fn(encoding="utf-8", errors="replace")

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
from my_agent_core.session import Session, SessionInfoEntry
from my_agent_core.session.entries import (
    BranchSummaryEntry,
    CompactionEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    ThinkingLevelChangeEntry,
)
from my_agent_core.session.tree import lowest_common_ancestor
from my_agent_core.tool_history import repair_tool_history
from my_agent_llm import LLM, Config, Message
from my_agent_llm.auth.manager import AuthManager
from my_agent_llm.auth.schema import ApiKeyCredential, OAuthCredential
from my_coding_agent.agent import CodingAgent
from my_coding_agent.macro import MacroEngine
from my_coding_agent.paths import AgentPaths
from my_coding_agent.permissions import PermissionGate
from my_coding_agent.prompt import build_default_coding_prompt
from my_coding_agent.settings import Settings, load_settings, save_settings
from my_agent_core.skills import SkillManager


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


def serialize_event(event: Event) -> dict[str, Any]:
    """将 Python 内部不可变事实事件序列化为对标 Pi AgentEvent 规范的 JSON 字典。"""
    if isinstance(event, AgentStart):
        return {
            "type": "agent_start",
            "system_prompt": event.system_prompt,
            "user_input": event.user_input,
        }
    elif isinstance(event, AgentEnd):
        return {
            "type": "agent_end",
            "iterations": event.iterations,
            "stop_reason": event.stop_reason,
            "final_text": event.final_text or "",
        }
    elif isinstance(event, TurnStart):
        return {
            "type": "turn_start",
            "iteration": event.iteration,
        }
    elif isinstance(event, TurnEnd):
        return {
            "type": "turn_end",
        }
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
        return {
            "type": "message_end",
            "message": {
                "role": msg.role,
                "content": msg.content or "",
            },
        }
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


KNOWN_MODEL_CATALOG: list[dict[str, Any]] = [
    # DeepSeek
    {"id": "deepseek-chat", "provider": "deepseek", "name": "DeepSeek-V3", "contextWindow": 64000},
    {"id": "deepseek-reasoner", "provider": "deepseek", "name": "DeepSeek-R1", "contextWindow": 64000},
    # OpenAI
    {"id": "gpt-4o", "provider": "openai", "name": "GPT-4o", "contextWindow": 128000},
    {"id": "gpt-4o-mini", "provider": "openai", "name": "GPT-4o mini", "contextWindow": 128000},
    {"id": "o1", "provider": "openai", "name": "o1", "contextWindow": 200000},
    {"id": "o3-mini", "provider": "openai", "name": "o3-mini", "contextWindow": 200000},
    # Anthropic
    {"id": "claude-3-5-sonnet-20241022", "provider": "anthropic", "name": "Claude 3.5 Sonnet", "contextWindow": 200000},
    {"id": "claude-3-5-haiku-20241022", "provider": "anthropic", "name": "Claude 3.5 Haiku", "contextWindow": 200000},
    {"id": "claude-3-opus-20240229", "provider": "anthropic", "name": "Claude 3 Opus", "contextWindow": 200000},
    # Antigravity (Google)
    {"id": "gemini-3.8-flash", "provider": "antigravity", "name": "Gemini 3.8 Flash", "contextWindow": 1000000},
    {"id": "gemini-2.5-pro", "provider": "antigravity", "name": "Gemini 2.5 Pro", "contextWindow": 1000000},
    {"id": "gemini-2.5-flash", "provider": "antigravity", "name": "Gemini 2.5 Flash", "contextWindow": 1000000},
]


class RpcServer:
    """标准 stdio JSON-RPC 2.0 服务端，将 Python 无头 CodingAgent 连接至 Node 前端。"""

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        agent: CodingAgent | None = None,
        llm: Any | None = None,
        paths: AgentPaths | None = None,
    ):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.agent = agent
        self.llm = llm
        self.paths = paths
        self.macro_engine: MacroEngine = MacroEngine(
            workspace=agent.workspace if agent else None,
            paths=paths,
        )
        self.auth_mgr: AuthManager | None = AuthManager(auth_path=paths.auth_path) if paths else None
        self.settings: Settings | None = None
        self.is_shutting_down = False
        self._write_lock = threading.Lock()
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def emit_json(self, payload: dict[str, Any]) -> None:
        """向 stdout 写入单行 JSON 并强制 flush。"""
        line = json.dumps(payload, ensure_ascii=False)
        with self._write_lock:
            try:
                self.stdout.write(line + "\n")
                self.stdout.flush()
            except UnicodeEncodeError:
                # 编码兜底：若当前宿主 stdout 不支持特定 Unicode 字符，使用 ASCII 转义输出
                ascii_line = json.dumps(payload, ensure_ascii=True)
                self.stdout.write(ascii_line + "\n")
                self.stdout.flush()

    def send_notification(self, method: str, params: dict[str, Any]) -> None:
        """向客户端发送单向通知 (如 event)。"""
        self.emit_json(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def send_response(
        self,
        req_id: int | str,
        result: Any = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造并发送 RPC 响应，同时返回字典便于单元测试断言。"""
        resp: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
        }
        if error is not None:
            resp["error"] = error
        else:
            resp["result"] = result or {}

        self.emit_json(resp)
        return resp

    def _resolve_initial_llm(
        self,
        workspace_path: Path,
        explicit_model: str | None,
        settings: Settings,
        auth_mgr: AuthManager,
    ) -> LLM | None:
        """根据启动参数、工作区配置与凭证中心探测构造底层 LLM 客户端。"""
        model_name = explicit_model or settings.default_model
        provider = None
        if model_name and "/" in model_name:
            provider, model_name = model_name.split("/", 1)
        elif model_name and model_name.startswith("gemini-"):
            provider = "antigravity"
        elif model_name and ("deepseek" in model_name):
            provider = (
                "deepseek"
                if (os.environ.get("DEEPSEEK_API_KEY") or auth_mgr.get_credential("deepseek"))
                else ("openai" if explicit_model else None)
            )
        elif model_name and ("gpt-" in model_name or "o1" in model_name or "o3" in model_name):
            provider = "openai"
        elif model_name and ("claude-" in model_name):
            provider = "anthropic"

        api_key = None
        base_url = None
        if not provider:
            if os.environ.get("OPENAI_API_KEY") or auth_mgr.get_credential("openai"):
                provider = "openai"
                model_name = explicit_model or os.environ.get("OPENAI_MODEL") or "gpt-4o"
            elif os.environ.get("DEEPSEEK_API_KEY") or auth_mgr.get_credential("deepseek"):
                provider = "deepseek"
                model_name = explicit_model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
            elif os.environ.get("ANTHROPIC_API_KEY") or auth_mgr.get_credential("anthropic"):
                provider = "anthropic"
                model_name = explicit_model or os.environ.get("ANTHROPIC_MODEL") or "claude-3-5-sonnet-20241022"
            else:
                from my_agent_llm.auth.antigravity import AntigravityAuthResolver

                resolver = AntigravityAuthResolver(workspace=workspace_path)
                if resolver.resolve_credentials() is not None or auth_mgr.get_credential("antigravity") is not None:
                    provider = "antigravity"
                    model_name = explicit_model or "gemini-3.8-flash"
                else:
                    provider = settings.default_provider or "openai"
                    model_name = explicit_model or "gpt-4o"

        if provider:
            # 1. 优先从全局凭据中心 (~/.my-pi-agent/auth.json) 加载
            cred = auth_mgr.get_credential(provider)
            if cred is not None:
                if isinstance(cred, ApiKeyCredential):
                    api_key = cred.resolve_key()
                    if not base_url and cred.base_url:
                        base_url = cred.base_url
                elif isinstance(cred, OAuthCredential):
                    api_key = cred.access

            # 2. 次选本地环境变量与 .env 兜底
            if not api_key:
                api_key = os.environ.get(f"{provider.upper()}_API_KEY")
                base_url = os.environ.get(f"{provider.upper()}_BASE_URL")
                if provider == "openai":
                    api_key = api_key or os.environ.get("OPENAI_API_KEY")
                    base_url = base_url or os.environ.get("OPENAI_BASE_URL")
                elif provider == "antigravity":
                    api_key = (
                        api_key or os.environ.get("ANTIGRAVITY_ACCESS_TOKEN") or os.environ.get("GOOGLE_ACCESS_TOKEN")
                    )

            if not api_key and provider != "antigravity":
                api_key = os.environ.get("OPENAI_API_KEY")
                if not base_url and provider == "openai":
                    base_url = os.environ.get("OPENAI_BASE_URL")

        try:
            return LLM(config=Config(provider=provider, model=model_name, api_key=api_key, base_url=base_url))
        except Exception:
            return None

    async def _handle_initialize(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        workspace_path = Path(params.get("workspace", ".")).resolve()
        paths = self.paths or AgentPaths()
        paths.ensure_directories()
        self.paths = paths
        settings = load_settings(paths, cwd=workspace_path)
        self.settings = settings
        auth_mgr = self.auth_mgr or AuthManager(auth_path=paths.auth_path)
        self.auth_mgr = auth_mgr

        explicit_model = params.get("model")
        mode = params.get("mode", settings.default_permission_mode)

        if (workspace_path / ".env").exists():
            load_dotenv(workspace_path / ".env", override=False)

        llm = self.llm
        if llm is None:
            llm = self._resolve_initial_llm(workspace_path, explicit_model, settings, auth_mgr)

        session_file = paths.default_session_path(workspace_path)
        session_file.parent.mkdir(parents=True, exist_ok=True)

        target_session: Session | None = None
        should_continue = bool(params.get("continue_session", False) or params.get("continue", False))
        resume_param = params.get("resume")
        if resume_param and isinstance(resume_param, str) and resume_param != "true":
            s_dir = paths.project_session_dir(workspace_path)
            for cand in [s_dir / f"{resume_param}.jsonl", s_dir / resume_param, Path(resume_param)]:
                if cand.exists():
                    try:
                        target_session = Session.load(cand)
                        break
                    except Exception:
                        continue
        elif should_continue:
            s_dir = paths.project_session_dir(workspace_path)
            jsonl_files = sorted(s_dir.glob("*.jsonl"), key=lambda p: os.path.getmtime(p), reverse=True)
            if jsonl_files:
                try:
                    target_session = Session.load(jsonl_files[0])
                except Exception:
                    target_session = None

        if target_session is None:
            if session_file.exists() and not bool(params.get("new_session", False)):
                try:
                    target_session = Session.load(session_file)
                except Exception:
                    target_session = Session(path=session_file, cwd=str(workspace_path))
            else:
                target_session = Session(path=session_file, cwd=str(workspace_path))

        if bool(params.get("no_session", False)):
            target_session.save = lambda: None  # type: ignore[method-assign]

        gate = PermissionGate(mode=mode) if mode else None
        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=llm,
            session=target_session,
            permission_gate=gate,
        )

        if initial_name := params.get("name"):
            name_str = str(initial_name).strip()
            if name_str:
                self.agent.session.metadata["name"] = name_str
                self.agent.session.metadata["title"] = name_str
                info_entry = SessionInfoEntry(
                    name=name_str,
                    title=name_str,
                    cwd=str(workspace_path),
                    parent_id=self.agent.session.tree.current_id,
                )
                self.agent.session.store.append_entry(info_entry)

        if initial_thinking := params.get("thinking"):
            thinking_str = str(initial_thinking).strip().lower()
            valid_levels = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
            if thinking_str in valid_levels:
                setattr(self.agent, "thinking_level", thinking_str)
                t_entry = ThinkingLevelChangeEntry(
                    thinking_level=thinking_str,
                    parent_id=self.agent.session.tree.current_id,
                )
                self.agent.session.append_entry(t_entry)

        self.macro_engine = MacroEngine(workspace=workspace_path, paths=paths)

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        actual_model = getattr(getattr(self.agent.agent.llm, "config", None), "model", "default")
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "workspace": str(workspace_path),
                "model": actual_model,
                "session_id": target_session.id,
                "session_file": str(target_session.path) if target_session.path else "",
                "session_name": target_session.metadata.get("name")
                or target_session.metadata.get("title")
                or target_session.id,
                "messages": messages_repr,
            },
        )

    async def _handle_prompt(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        if getattr(self.agent.agent, "llm", None) is None:
            return self.send_response(
                req_id,
                error={
                    "code": -32002,
                    "message": "未检测到有效模型凭据。请在当前项目 .env 文件中配置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY，或输入 /login 绑定 Key。",
                },
            )

        text = params.get("text", "")
        async for event in self.agent.run_stream(text):
            serialized = serialize_event(event)
            self.send_notification("event", serialized)

        return self.send_response(req_id, result={"status": "completed"})

    def _handle_login(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        provider = params.get("provider", "").lower().strip()
        key = params.get("key", "").strip()
        if not provider or not key:
            return self.send_response(
                req_id,
                result={
                    "status": "info",
                    "message": "请使用: /login <provider> <key>，例如: /login deepseek sk-xxxx 或 /login openai sk-xxxx",
                },
            )

        key_name = "ANTIGRAVITY_ACCESS_TOKEN" if provider == "antigravity" else f"{provider.upper()}_API_KEY"
        os.environ[key_name] = key

        paths = self.paths or AgentPaths()
        paths.ensure_directories()
        self.paths = paths
        auth_mgr = self.auth_mgr or AuthManager(auth_path=paths.auth_path)
        self.auth_mgr = auth_mgr
        auth_mgr.set_api_key(provider=provider, key=key)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "message": f"已成功绑定 {provider} 凭据至全局凭据中心 (~/.my-pi-agent/auth.json)！",
            },
        )

    def _handle_steer(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        msg = params.get("message", "")
        self.agent.steer(msg)
        return self.send_response(req_id, result={"status": "ok"})

    def _handle_followup(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        msg = params.get("message", "")
        self.agent.follow_up(msg)
        return self.send_response(req_id, result={"status": "ok"})

    def _handle_abort(self, req_id: Any) -> dict[str, Any]:
        if self.agent:
            self.agent.abort()
        return self.send_response(req_id, result={"status": "ok"})

    def _handle_session_name(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        name = params.get("name", "").strip()
        if not name:
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing 'name' parameter"},
            )

        entry = SessionInfoEntry(
            name=name,
            title=name,
            cwd=str(self.agent.workspace),
            parent_id=self.agent.session.tree.current_id,
        )
        self.agent.session.store.append_entry(entry)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "name": name,
            },
        )

    def _handle_session_list(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        paths = self.paths or AgentPaths()
        workspace_path = Path(self.agent.workspace if self.agent else params.get("workspace", ".")).resolve()
        all_projects = bool(params.get("all_projects", False))

        target_dirs: list[Path] = []
        if all_projects:
            if paths.sessions_dir.exists():
                target_dirs = [d for d in paths.sessions_dir.iterdir() if d.is_dir()]
        else:
            proj_dir = paths.project_session_dir(workspace_path)
            if proj_dir.exists():
                target_dirs = [proj_dir]

        sessions_meta: list[dict[str, Any]] = []
        for s_dir in target_dirs:
            for f in s_dir.glob("*.jsonl"):
                try:
                    with open(f, encoding="utf-8") as fh:
                        line1 = fh.readline()
                        if not line1:
                            continue
                        header = json.loads(line1)
                        sid = header.get("id") or f.stem
                        cwd_val = header.get("cwd", "")
                        created_val = header.get("createdAt") or header.get("created_at") or os.path.getctime(f)
                        s_name = (
                            header.get("name")
                            or header.get("title")
                            or header.get("metadata", {}).get("name")
                            or header.get("metadata", {}).get("title")
                        )
                        msg_count = 0
                        for line in fh:
                            line_str = line.strip()
                            if not line_str:
                                continue
                            try:
                                entry_data = json.loads(line_str)
                                etype = entry_data.get("type")
                                if etype == "message":
                                    msg_count += 1
                                elif etype in ("session_info", "sessionInfo"):
                                    latest_name = entry_data.get("name") or entry_data.get("title")
                                    if latest_name:
                                        s_name = latest_name
                            except Exception:
                                continue

                        modified_val = os.path.getmtime(f)
                        sessions_meta.append(
                            {
                                "id": sid,
                                "name": s_name or sid,
                                "path": str(f.resolve()),
                                "cwd": cwd_val,
                                "modified": modified_val,
                                "created_at": created_val,
                                "message_count": msg_count,
                            }
                        )
                except Exception:
                    continue

        sessions_meta.sort(key=lambda s: s.get("modified", 0), reverse=True)
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "sessions": sessions_meta,
            },
        )

    def _handle_session_resume(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.get("session_id") or params.get("id") or params.get("path") or params.get("session_file")
        if not session_id:
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing session_id parameter"},
            )

        paths = self.paths or AgentPaths()
        workspace_path = Path(self.agent.workspace if self.agent else params.get("workspace", ".")).resolve()
        session_dir = paths.project_session_dir(workspace_path)

        target_file: Path | None = None
        cand = Path(session_id)
        if cand.is_file():
            cand_resolved = cand.resolve()
            if cand_resolved.is_relative_to(paths.sessions_dir) or cand_resolved.is_relative_to(workspace_path):
                target_file = cand_resolved
        elif "/" not in session_id and "\\" not in session_id and (session_dir / f"{session_id}.jsonl").is_file():
            target_file = session_dir / f"{session_id}.jsonl"
        elif "/" not in session_id and "\\" not in session_id and (session_dir / session_id).is_file():
            target_file = session_dir / session_id
        else:
            matches: list[Path] = []
            if session_dir.exists():
                for f in session_dir.glob("*.jsonl"):
                    try:
                        with open(f, encoding="utf-8") as fh:
                            first_line = fh.readline()
                            if first_line:
                                header = json.loads(first_line)
                                fid = header.get("id", "")
                                if (
                                    fid == session_id
                                    or fid.startswith(session_id)
                                    or f.stem == session_id
                                    or f.stem.startswith(session_id)
                                ):
                                    matches.append(f)
                    except Exception:
                        continue

            if not matches and paths.sessions_dir.exists():
                for s_dir in paths.sessions_dir.iterdir():
                    if not s_dir.is_dir() or s_dir == session_dir:
                        continue
                    for f in s_dir.glob("*.jsonl"):
                        try:
                            with open(f, encoding="utf-8") as fh:
                                first_line = fh.readline()
                                if first_line:
                                    header = json.loads(first_line)
                                    fid = header.get("id", "")
                                    if (
                                        fid == session_id
                                        or fid.startswith(session_id)
                                        or f.stem == session_id
                                        or f.stem.startswith(session_id)
                                    ):
                                        matches.append(f)
                        except Exception:
                            continue

            if len(matches) == 1:
                target_file = matches[0]
            elif len(matches) > 1:
                return self.send_response(
                    req_id,
                    error={
                        "code": -32003,
                        "message": f"Ambiguous session_id '{session_id}': {[m.name for m in matches]}",
                    },
                )

        if target_file is None or not target_file.is_file():
            return self.send_response(
                req_id,
                error={"code": -32004, "message": f"Session file not found for '{session_id}'"},
            )

        new_session = Session.load(target_file)
        mode = getattr(self.settings, "default_permission_mode", None)
        gate = self.agent.permission_gate if self.agent else (PermissionGate(mode=mode) if mode else None)
        llm = self.agent.agent.llm if self.agent else self.llm
        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=llm,
            session=new_session,
            permission_gate=gate,
        )

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "session_id": new_session.id,
                "session_name": new_session.metadata.get("name") or new_session.metadata.get("title") or new_session.id,
                "session_file": str(target_file),
                "cwd": new_session.cwd,
                "messages": messages_repr,
            },
        )

    def _handle_session_history(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "session_id": self.agent.session.id,
                "session_name": self.agent.session.metadata.get("name") or self.agent.session.id,
                "messages": messages_repr,
            },
        )

    async def _handle_session_compact(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        self.agent.abort()
        instructions = params.get("instructions")
        await self.agent.compact(instructions=instructions)

        info = self.agent.agent.context_manager.pending_compaction
        tokens_before = info.tokens_before if info else 0
        tokens_after = info.tokens_after if info else 0
        summary = info.summary if info else ""

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "tokens_before": tokens_before,
                "tokens_after": tokens_after,
                "summary": summary,
            },
        )

    def _handle_session_new(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        self.agent.abort()
        workspace_path = Path(self.agent.workspace).resolve()
        paths = self.paths or AgentPaths()
        session_dir = paths.project_session_dir(workspace_path)
        session_id = uuid7_str()
        session_file = session_dir / f"{session_id}.jsonl"

        new_session = Session(path=session_file, cwd=str(workspace_path))
        new_session.id = session_id
        mode = getattr(self.settings, "default_permission_mode", None)
        gate = self.agent.permission_gate or (PermissionGate(mode=mode) if mode else None)

        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=self.agent.agent.llm,
            session=new_session,
            permission_gate=gate,
        )

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "session_id": session_id,
                "session_file": str(session_file),
                "messages": [],
            },
        )

    def _handle_session_tree(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        session = self.agent.session
        entries = list(session.tree.entries.values())
        active_leaf_id = session.tree.current_id
        root_id = session.tree.root_id

        active_path_ids: set[str] = set()
        if active_leaf_id and active_leaf_id in session.tree.entries:
            active_path_ids = {e.id for e in session.tree.get_current_path()}

        parent_ids = {e.parent_id for e in entries if e.parent_id is not None}

        nodes: list[dict[str, Any]] = []
        for entry in entries:
            eid = entry.id
            pid = entry.parent_id
            etype = getattr(entry, "type", "message")
            role = getattr(entry, "role", etype)

            preview = ""
            if isinstance(entry, MessageEntry):
                msg = entry.message
                content = msg.content or ""
                if msg.metadata and msg.metadata.get("tool_calls"):
                    tc_names = [
                        tc.get("function", {}).get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                        for tc in msg.metadata.get("tool_calls", [])
                    ]
                    prefix = f"[Tool Call: {', '.join(filter(None, tc_names))}]"
                    preview = f"{prefix} {content}".strip() if content else prefix
                else:
                    preview = content
            elif isinstance(entry, CompactionEntry):
                preview = entry.summary
            elif isinstance(entry, BranchSummaryEntry):
                preview = entry.summary
            elif isinstance(entry, SessionInfoEntry):
                preview = entry.name or entry.title or ""
            elif isinstance(entry, ModelChangeEntry):
                preview = f"Model: {entry.model}"
            elif isinstance(entry, ThinkingLevelChangeEntry):
                preview = f"Thinking: {entry.thinking_level}"
            elif isinstance(entry, LabelEntry):
                preview = f"Label: {entry.label}"
            elif isinstance(entry, LeafEntry):
                preview = f"Leaf: {entry.leaf_id}"
            else:
                preview = str(getattr(entry, "content", "") or getattr(entry, "summary", "") or "")

            if len(preview) > 200:
                preview = preview[:200] + "..."

            nodes.append(
                {
                    "id": eid,
                    "parent_id": pid,
                    "role": role,
                    "type": etype,
                    "preview": preview,
                    "is_leaf": eid not in parent_ids,
                    "is_active": eid in active_path_ids,
                    "timestamp": getattr(entry, "timestamp", 0.0),
                }
            )

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "nodes": nodes,
                "active_leaf_id": active_leaf_id,
                "root_id": root_id,
            },
        )

    async def _handle_session_branch(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        target_id = params.get("target_id") or params.get("entry_id") or params.get("id")
        if not target_id:
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing 'target_id' parameter"},
            )

        session = self.agent.session
        if target_id not in session.tree.entries:
            return self.send_response(
                req_id,
                error={"code": -32004, "message": f"Entry '{target_id}' not found in session"},
            )

        target_entry = session.tree.entries[target_id]
        is_user = getattr(target_entry, "role", None) == "user" or (
            isinstance(target_entry, MessageEntry) and target_entry.message.role == "user"
        )

        self.agent.abort()
        old_leaf_id = session.tree.current_id
        summarize = bool(params.get("summarize", False))
        branch_summary_text = ""

        if is_user:
            new_leaf_id = target_entry.parent_id
            editor_text = (
                getattr(target_entry, "content", "")
                or (target_entry.message.content if isinstance(target_entry, MessageEntry) else "")
                or ""
            )
        else:
            new_leaf_id = target_id
            editor_text = ""

        if new_leaf_id is not None and session.compaction_floor is not None:
            if not session._after_floor(new_leaf_id):
                return self.send_response(
                    req_id,
                    error={
                        "code": -32005,
                        "message": f"Cannot branch past compaction floor {session.compaction_floor}: entry {new_leaf_id} is prior to compacted history",
                    },
                )
        elif new_leaf_id is None and session.compaction_floor is not None:
            return self.send_response(
                req_id,
                error={
                    "code": -32005,
                    "message": f"Cannot branch past compaction floor {session.compaction_floor}: root is prior to compacted history",
                },
            )

        if summarize and old_leaf_id and old_leaf_id != new_leaf_id:
            old_path = session.tree.get_path_to_entry(old_leaf_id)
            new_path_ids = (
                {e.id for e in session.tree.get_path_to_entry(new_leaf_id)}
                if new_leaf_id and new_leaf_id in session.tree.entries
                else set()
            )
            abandoned_entries = [e for e in old_path if e.id not in new_path_ids]

            if abandoned_entries:
                lca = lowest_common_ancestor(session.tree.entries, old_leaf_id, new_leaf_id) if new_leaf_id else None
                summary_prompt = (
                    "Please concisely summarize the key decisions, code changes, and exploration from this abandoned conversation branch in 1-2 sentences:\n"
                    + "\n".join(
                        f"{getattr(e, 'role', 'entry')}: {getattr(e, 'content', '')}"
                        for e in abandoned_entries
                        if hasattr(e, "content") or hasattr(e, "message")
                    )
                )
                try:
                    llm = self.agent.agent.llm
                    resp = await llm.achat([Message(role="user", content=summary_prompt)])
                    branch_summary_text = getattr(resp, "content", "") or "Branch summary"
                except Exception:
                    branch_summary_text = "Branch exploration summary"

                summary_entry = BranchSummaryEntry(
                    parent_id=new_leaf_id,
                    summary=branch_summary_text,
                    details={
                        "abandoned_from": old_leaf_id,
                        "abandoned_count": len(abandoned_entries),
                        "lca": lca,
                    },
                )
                session.tree.entries[summary_entry.id] = summary_entry
                session.tree.current_id = summary_entry.id
                session.save()
                new_leaf_id = summary_entry.id

        if not (summarize and branch_summary_text):
            if new_leaf_id is None:
                session.tree.current_id = None
                session.save()
            else:
                session.tree.current_id = new_leaf_id
                session.save()

        system = [m for m in self.agent.agent.messages if m.role == "system"]
        restored = system + session.get_full_history_messages()
        self.agent.agent.messages = list(repair_tool_history(restored).messages)

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        res_payload: dict[str, Any] = {
            "status": "ok",
            "leaf_id": new_leaf_id,
            "editor_text": editor_text,
            "session_id": session.id,
            "messages": messages_repr,
        }
        if branch_summary_text:
            res_payload["branch_summary"] = branch_summary_text

        return self.send_response(req_id, result=res_payload)

    def _handle_session_fork(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        entry_id = params.get("entry_id") or params.get("id") or params.get("target_id")
        if not entry_id:
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing 'entry_id' parameter"},
            )

        session = self.agent.session
        if entry_id not in session.tree.entries:
            return self.send_response(
                req_id,
                error={"code": -32004, "message": f"Entry '{entry_id}' not found in session"},
            )

        target_entry = session.tree.entries[entry_id]
        prompt_text = (
            getattr(target_entry, "content", "")
            or (target_entry.message.content if isinstance(target_entry, MessageEntry) else "")
            or ""
        )

        cutoff_id = target_entry.parent_id
        path_entries = (
            session.tree.get_path_to_entry(cutoff_id) if cutoff_id and cutoff_id in session.tree.entries else []
        )

        self.agent.abort()
        workspace_path = Path(self.agent.workspace).resolve()
        paths = self.paths or AgentPaths()
        session_dir = paths.project_session_dir(workspace_path)
        new_session_id = uuid7_str()
        new_session_file = session_dir / f"{new_session_id}.jsonl"

        new_session = Session(path=new_session_file, cwd=str(workspace_path))
        new_session.id = new_session_id
        new_session.metadata["parent_session_id"] = session.id
        new_session.metadata["forked_from_entry_id"] = entry_id

        for entry in path_entries:
            if isinstance(entry, MessageEntry):
                new_session.add_message(entry.role, entry.content, **(entry.metadata or {}))
            elif isinstance(entry, CompactionEntry):
                new_compaction = CompactionEntry(
                    parent_id=new_session.tree.current_id,
                    summary=entry.summary,
                    replaces_entry_ids=list(entry.replaces_entry_ids),
                    metadata=dict(entry.metadata),
                )
                new_session.append_entry(new_compaction)
            elif isinstance(entry, BranchSummaryEntry):
                new_bs = BranchSummaryEntry(
                    parent_id=new_session.tree.current_id,
                    summary=entry.summary,
                    details=dict(entry.details),
                )
                new_session.append_entry(new_bs)
            else:
                copied = entry.model_copy(update={"parent_id": new_session.tree.current_id})
                new_session.append_entry(copied)

        new_session.save()

        mode = getattr(self.settings, "default_permission_mode", None)
        gate = self.agent.permission_gate or (PermissionGate(mode=mode) if mode else None)
        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=self.agent.agent.llm,
            session=new_session,
            permission_gate=gate,
        )

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "new_session_id": new_session_id,
                "session_file": str(new_session_file),
                "prompt_text": prompt_text,
                "messages": messages_repr,
            },
        )

    def _handle_session_clone(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        session = self.agent.session
        active_leaf_id = session.tree.current_id
        path_entries = session.tree.get_current_path() if active_leaf_id else []

        self.agent.abort()
        workspace_path = Path(self.agent.workspace).resolve()
        paths = self.paths or AgentPaths()
        session_dir = paths.project_session_dir(workspace_path)
        new_session_id = uuid7_str()
        new_session_file = session_dir / f"{new_session_id}.jsonl"

        new_session = Session(path=new_session_file, cwd=str(workspace_path))
        new_session.id = new_session_id
        new_session.metadata["parent_session_id"] = session.id
        if active_leaf_id:
            new_session.metadata["cloned_from_leaf_id"] = active_leaf_id

        for entry in path_entries:
            if isinstance(entry, MessageEntry):
                new_session.add_message(entry.role, entry.content, **(entry.metadata or {}))
            elif isinstance(entry, CompactionEntry):
                new_compaction = CompactionEntry(
                    parent_id=new_session.tree.current_id,
                    summary=entry.summary,
                    replaces_entry_ids=list(entry.replaces_entry_ids),
                    metadata=dict(entry.metadata),
                )
                new_session.append_entry(new_compaction)
            elif isinstance(entry, BranchSummaryEntry):
                new_bs = BranchSummaryEntry(
                    parent_id=new_session.tree.current_id,
                    summary=entry.summary,
                    details=dict(entry.details),
                )
                new_session.append_entry(new_bs)
            else:
                copied = entry.model_copy(update={"parent_id": new_session.tree.current_id})
                new_session.append_entry(copied)

        new_session.save()

        mode = getattr(self.settings, "default_permission_mode", None)
        gate = self.agent.permission_gate or (PermissionGate(mode=mode) if mode else None)
        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=self.agent.agent.llm,
            session=new_session,
            permission_gate=gate,
        )

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "new_session_id": new_session_id,
                "session_file": str(new_session_file),
                "messages": messages_repr,
            },
        )

    async def _handle_shell_exec(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        command = params.get("command", "").strip()
        if not command:
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing 'command' parameter"},
            )
        exclude_from_context = bool(params.get("exclude_from_context", False))
        try:
            timeout = float(params.get("timeout", 60.0))
        except (ValueError, TypeError):
            timeout = 60.0

        cwd = Path(self.agent.workspace)
        res = await asyncio.to_thread(
            self.macro_engine.execute_shell,
            command=command,
            cwd=cwd,
            exclude_from_context=exclude_from_context,
            timeout=timeout,
        )

        if not exclude_from_context:
            output_str = res.get("output", "")
            if output_str:
                formatted = f"Ran `{command}`\n```text\n{output_str}\n```"
            else:
                formatted = f"Ran `{command}`\n```text\n```"

            self.agent.session.add_message(
                role="user",
                content=formatted,
                metadata={
                    "type": "bashExecution",
                    "customType": "bashExecution",
                    "command": command,
                    "exit_code": res.get("exit_code"),
                    "exclude_from_context": False,
                },
            )

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "output": res.get("output", ""),
                "exit_code": res.get("exit_code", 0),
            },
        )

    def _handle_macro_expand(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if self.agent:
            self.macro_engine.workspace = Path(self.agent.workspace)
        text = str(params.get("text", ""))
        skills_dir_param = params.get("skills_dir")
        prompts_dir_param = params.get("prompts_dir")

        skills_dir = Path(skills_dir_param) if skills_dir_param else None
        prompts_dir = Path(prompts_dir_param) if prompts_dir_param else None

        expanded_text, is_expanded = self.macro_engine.expand_macro(
            text,
            skills_dir=skills_dir,
            prompts_dir=prompts_dir,
        )

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "text": expanded_text,
                "expanded": is_expanded,
                "expanded_text": expanded_text,
            },
        )

    def _handle_model_switch(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        raw_model = params.get("model", "")
        if not raw_model or not isinstance(raw_model, str) or not raw_model.strip():
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing 'model' parameter"},
            )
        raw_model = raw_model.strip()

        provider = params.get("provider")
        if isinstance(provider, str):
            provider = provider.strip() or None

        if "/" in raw_model:
            prov_part, model_name = raw_model.split("/", 1)
            provider = provider or prov_part.strip()
            model_name = model_name.strip()
        else:
            model_name = raw_model
            if not provider:
                if model_name.startswith("gemini-"):
                    provider = "antigravity"
                elif "deepseek" in model_name:
                    provider = "deepseek"
                elif "gpt-" in model_name or "o1" in model_name or "o3" in model_name:
                    provider = "openai"
                elif "claude-" in model_name:
                    provider = "anthropic"
                else:
                    current_llm = getattr(self.agent.agent, "llm", None)
                    current_config = getattr(current_llm, "config", None)
                    if current_config and hasattr(current_config, "provider"):
                        provider = current_config.provider
                    elif self.settings and self.settings.default_provider:
                        provider = self.settings.default_provider
                    else:
                        provider = "openai"

        # 更新 Agent 当前模型标识
        self.agent.agent.model = model_name

        llm_inst = getattr(self.agent.agent, "llm", None)
        if hasattr(llm_inst, "config"):
            paths = self.paths or AgentPaths()
            auth_mgr = self.auth_mgr or AuthManager(auth_path=paths.auth_path)
            api_key = None
            base_url = None
            if provider:
                # 1. 优先从全局凭据中心读取
                cred = auth_mgr.get_credential(provider)
                if cred is not None:
                    if isinstance(cred, ApiKeyCredential):
                        api_key = cred.resolve_key()
                        if cred.base_url:
                            base_url = cred.base_url
                    elif isinstance(cred, OAuthCredential):
                        api_key = cred.access

                # 2. 次选环境变量兜底
                if not api_key:
                    api_key = os.environ.get(f"{provider.upper()}_API_KEY")
                    base_url = os.environ.get(f"{provider.upper()}_BASE_URL")
            try:
                new_config = Config(
                    provider=provider or "openai",
                    model=model_name,
                    api_key=api_key or "placeholder",
                    base_url=base_url,
                )
                self.agent.agent.llm = LLM(config=new_config)
            except Exception:
                pass
        elif llm_inst is not None and hasattr(llm_inst, "model"):
            setattr(llm_inst, "model", model_name)

        # 向 Session 追加 ModelChangeEntry
        entry = ModelChangeEntry(
            model=model_name,
            provider=provider,
            parent_id=self.agent.session.tree.current_id,
        )
        self.agent.session.append_entry(entry)

        # 若 persist=True，更新并持久化 settings.json
        persist = bool(params.get("persist", False))
        if persist:
            paths = self.paths or AgentPaths()
            if self.settings is None:
                self.settings = load_settings(paths)
            self.settings.default_model = model_name
            if provider:
                self.settings.default_provider = provider
            save_settings(self.settings, paths.settings_path)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "model": model_name,
                "provider": provider,
            },
        )

    def _handle_thinking_set(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        level = params.get("level", "")
        if not level or not isinstance(level, str):
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing 'level' parameter"},
            )
        level = level.strip().lower()

        valid_levels = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
        if level not in valid_levels:
            return self.send_response(
                req_id,
                error={
                    "code": -32602,
                    "message": f"Invalid thinking level '{level}'. Must be one of: {', '.join(sorted(valid_levels))}",
                },
            )

        entry = ThinkingLevelChangeEntry(
            thinking_level=level,
            parent_id=self.agent.session.tree.current_id,
        )
        self.agent.session.append_entry(entry)

        setattr(self.agent, "thinking_level", level)

        persist = bool(params.get("persist", False))
        if persist:
            paths = self.paths or AgentPaths()
            if self.settings is None:
                self.settings = load_settings(paths)
            self.settings.default_thinking_level = level  # type: ignore[assignment]
            save_settings(self.settings, paths.settings_path)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "level": level,
            },
        )

    def _get_configured_providers(self) -> set[str]:
        configured: set[str] = set()
        paths = self.paths or AgentPaths()
        auth_mgr = self.auth_mgr or AuthManager(auth_path=paths.auth_path)

        for p in ["deepseek", "openai", "anthropic", "antigravity"]:
            if auth_mgr.get_credential(p) is not None:
                configured.add(p)
                continue
            key_name = "ANTIGRAVITY_ACCESS_TOKEN" if p == "antigravity" else f"{p.upper()}_API_KEY"
            if os.environ.get(key_name):
                configured.add(p)
                continue
            if p == "openai" and os.environ.get("OPENAI_API_KEY"):
                configured.add("openai")
            if p == "antigravity":
                try:
                    from my_agent_llm.auth.antigravity import AntigravityAuthResolver

                    ws = Path(self.agent.workspace if self.agent else ".").resolve()
                    resolver = AntigravityAuthResolver(workspace=ws)
                    if resolver.resolve_credentials() is not None:
                        configured.add("antigravity")
                except Exception:
                    pass

        return configured

    def _handle_models_list(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        scope = params.get("scope", "configured")
        configured_providers = self._get_configured_providers()

        models = []
        for item in KNOWN_MODEL_CATALOG:
            prov = item["provider"]
            is_configured = prov in configured_providers
            if scope == "all" or is_configured:
                models.append(
                    {
                        **item,
                        "is_configured": is_configured,
                    }
                )

        curr = "default"
        if self.agent:
            curr = getattr(self.agent, "model", None) or getattr(getattr(self.agent, "agent", None), "model", "default")
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "scope": scope,
                "configured_providers": sorted(list(configured_providers)),
                "models": models,
                "current_model": curr,
            },
        )

    def _handle_auth_logout(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        provider = params.get("provider", "")
        if not provider or not isinstance(provider, str) or not provider.strip():
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing 'provider' parameter"},
            )
        prov = provider.strip().lower()

        paths = self.paths or AgentPaths()
        auth_mgr = self.auth_mgr or AuthManager(auth_path=paths.auth_path)
        self.auth_mgr = auth_mgr

        profile = params.get("profile")
        if isinstance(profile, str):
            profile = profile.strip() or None

        removed = auth_mgr.remove_credential(prov, profile=profile)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "provider": prov,
                "removed": removed,
            },
        )

    def _handle_resource_reload(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        paths = self.paths or AgentPaths()
        workspace_path = Path(self.agent.workspace if self.agent else ".").resolve()

        # 1. 重载 settings
        self.settings = load_settings(paths, cwd=workspace_path)

        # 2. 重载项目指导文件与系统提示词
        new_prompt = build_default_coding_prompt(workspace_path)
        if self.agent:
            self.agent.agent._system_prompt = new_prompt

            mem_store = getattr(self.agent.agent, "memory_store", None)
            mem_prompt = (
                mem_store.format_all_for_system_prompt()
                if mem_store is not None and hasattr(mem_store, "format_all_for_system_prompt")
                else None
            )
            skill_prompt = (
                self.agent.agent.skill_manager.format_prompt() if hasattr(self.agent.agent, "skill_manager") else ""
            )
            subagent_prompt = (
                self.agent.agent.subagent_manager.format_prompt()
                if hasattr(self.agent.agent, "subagent_manager")
                else ""
            )
            parts = [p for p in (new_prompt, skill_prompt, subagent_prompt, mem_prompt) if p]
            new_sys_content = "\n\n".join(parts)

            if self.agent.agent.messages and self.agent.agent.messages[0].role == "system":
                self.agent.agent.messages[0] = Message(role="system", content=new_sys_content)
            elif parts:
                self.agent.agent.messages.insert(0, Message(role="system", content=new_sys_content))

        # 3. 重载 skills
        skill_dirs = [
            paths.skills_dir,
            paths.project_skills_dir(workspace_path),
            paths.project_agents_skills_dir(workspace_path),
        ]
        skill_mgr = SkillManager(dirs=skill_dirs)
        if self.agent and hasattr(self.agent.agent, "skill_manager"):
            self.agent.agent.skill_manager = skill_mgr
        skill_count = len(skill_mgr.skills)

        # 4. 统计 templates
        template_count = 0
        for p_dir in (
            paths.prompts_dir,
            paths.project_agent_dir(workspace_path) / "prompts",
            workspace_path / ".agents" / "prompts",
        ):
            if p_dir.exists():
                template_count += len(list(p_dir.glob("*.md")))

        summary = f"Reloaded settings, project context, {skill_count} skills, and {template_count} prompt templates."
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "summary": summary,
                "skills_count": skill_count,
                "templates_count": template_count,
            },
        )

    def _handle_settings_get(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        paths = self.paths or AgentPaths()
        ws = Path(self.agent.workspace if self.agent else ".").resolve()
        if self.settings is None:
            self.settings = load_settings(paths, cwd=ws)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "settings": self.settings.model_dump(),
                "paths": {
                    "global_settings": str(paths.settings_path),
                    "project_settings": str(paths.project_settings_path(ws)),
                },
            },
        )

    def _handle_settings_set(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        paths = self.paths or AgentPaths()
        ws = Path(self.agent.workspace if self.agent else ".").resolve()
        if self.settings is None:
            self.settings = load_settings(paths, cwd=ws)

        scope = params.get("scope", "global")
        target_path = paths.project_settings_path(ws) if scope == "project" else paths.settings_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        updated_fields: dict[str, Any] = {}
        for key in [
            "default_model",
            "default_provider",
            "default_thinking_level",
            "default_permission_mode",
            "theme",
            "auto_compact",
        ]:
            if key in params:
                val = params[key]
                setattr(self.settings, key, val)
                updated_fields[key] = val

        save_settings(self.settings, target_path)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "updated": updated_fields,
                "settings": self.settings.model_dump(),
            },
        )

    def _handle_trust_set(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        paths = self.paths or AgentPaths()
        paths.home.mkdir(parents=True, exist_ok=True)
        trust_file = paths.home / "trust.json"

        workspace_path = Path(self.agent.workspace if self.agent else ".").resolve()
        target_dir = Path(params.get("path", workspace_path)).resolve()

        if bool(params.get("parent", False)):
            target_dir = target_dir.parent

        trusted = bool(params.get("trusted", True))

        trust_data: dict[str, bool] = {}
        if trust_file.exists():
            try:
                content = trust_file.read_text(encoding="utf-8")
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    trust_data = parsed
            except Exception:
                trust_data = {}

        trust_data[str(target_dir)] = trusted

        tmp_file = trust_file.with_name(f"{trust_file.name}.tmp")
        tmp_file.write_text(json.dumps(trust_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_file.replace(trust_file)

        decision = "trusted" if trusted else "untrusted"
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "path": str(target_dir),
                "trusted": trusted,
                "decision": decision,
            },
        )

    async def _handle_shutdown(self, req_id: Any) -> dict[str, Any]:
        self.is_shutting_down = True
        if self.agent and hasattr(self.agent, "close_mcp"):
            res = self.agent.close_mcp()
            if inspect.isawaitable(res):
                await res
        return self.send_response(req_id, result={"status": "ok"})

    async def handle_request(self, req: dict[str, Any]) -> dict[str, Any]:
        """分发并处理单个 RPC 请求。"""
        req_id = req.get("id", 0)
        method = req.get("method", "")
        params = req.get("params", {})

        try:
            if method == "initialize":
                return await self._handle_initialize(req_id, params)
            elif method == "prompt":
                return await self._handle_prompt(req_id, params)
            elif method == "login":
                return self._handle_login(req_id, params)
            elif method == "steer":
                return self._handle_steer(req_id, params)
            elif method == "followup":
                return self._handle_followup(req_id, params)
            elif method == "abort":
                return self._handle_abort(req_id)
            elif method == "session_name":
                return self._handle_session_name(req_id, params)
            elif method == "session_list":
                return self._handle_session_list(req_id, params)
            elif method == "session_resume":
                return self._handle_session_resume(req_id, params)
            elif method == "session_history":
                return self._handle_session_history(req_id, params)
            elif method == "session_compact":
                return await self._handle_session_compact(req_id, params)
            elif method == "session_new":
                return self._handle_session_new(req_id, params)
            elif method == "session_tree":
                return self._handle_session_tree(req_id, params)
            elif method == "session_branch":
                return await self._handle_session_branch(req_id, params)
            elif method == "session_fork":
                return self._handle_session_fork(req_id, params)
            elif method == "session_clone":
                return self._handle_session_clone(req_id, params)
            elif method == "shell_exec":
                return await self._handle_shell_exec(req_id, params)
            elif method == "macro_expand":
                return self._handle_macro_expand(req_id, params)
            elif method == "models_list":
                return self._handle_models_list(req_id, params)
            elif method == "model_switch":
                return self._handle_model_switch(req_id, params)
            elif method == "thinking_set":
                return self._handle_thinking_set(req_id, params)
            elif method == "auth_logout":
                return self._handle_auth_logout(req_id, params)
            elif method == "resource_reload":
                return self._handle_resource_reload(req_id, params)
            elif method == "settings_get":
                return self._handle_settings_get(req_id, params)
            elif method == "settings_set":
                return self._handle_settings_set(req_id, params)
            elif method == "trust_set":
                return self._handle_trust_set(req_id, params)
            elif method == "shutdown":
                return await self._handle_shutdown(req_id)
            else:
                return self.send_response(
                    req_id,
                    error={"code": -32601, "message": f"Method '{method}' not found"},
                )
        except Exception as e:
            return self.send_response(
                req_id,
                error={"code": -32000, "message": str(e)},
            )

    async def run_forever(self) -> None:
        """主服务循环，以异步方式按行消费 stdin 并处理请求。"""
        while not self.is_shutting_down:
            try:
                line = await asyncio.to_thread(self.stdin.readline)
            except Exception:
                break

            if not line:
                # 管道关闭 (EOF)
                break

            line_str = line.strip()
            if not line_str:
                continue

            try:
                req = json.loads(line_str)
            except json.JSONDecodeError:
                self.send_response(
                    0,
                    error={"code": -32700, "message": "Parse error (invalid JSON)"},
                )
                continue

            # 并发派发请求，保证在 prompt 执行期间仍可实时处理 abort / steer / followup
            task = asyncio.create_task(self.handle_request(req))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        if self._background_tasks:
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)


async def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(description="my-coding-agent stdio JSON-RPC server")
    parser.add_argument("-w", "--workspace", default=".", help="工作区路径")
    parser.add_argument("-m", "--model", default=None, help="LLM 模型标识符")
    parser.add_argument("-c", "--continue", dest="continue_session", action="store_true", help="续接最近一次会话")
    parser.add_argument("-r", "--resume", nargs="?", const=True, default=None, help="恢复指定会话或打开选择器")
    parser.add_argument("-n", "--name", default=None, help="为当前会话命名")
    parser.add_argument("--thinking", default=None, help="思考深度等级")
    parser.add_argument("--no-session", action="store_true", help="内存无痕模式")
    parser.add_argument("--new-session", action="store_true", help="强制开启新会话")
    args = parser.parse_args()

    server = RpcServer()
    # 如果指定了启动工作区或模型，先行执行预初始化
    if (
        args.workspace != "."
        or args.model is not None
        or args.continue_session
        or args.resume is not None
        or args.name is not None
        or args.thinking is not None
        or args.no_session
    ):
        await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "workspace": args.workspace,
                    "model": args.model,
                    "continue_session": args.continue_session,
                    "resume": args.resume,
                    "name": args.name,
                    "thinking": args.thinking,
                    "no_session": args.no_session,
                },
            }
        )

    await server.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
