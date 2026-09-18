from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from my_agent_core.events import MessageEnd
from my_agent_core.session import Session, SessionInfoEntry
from my_agent_core.session.entries import (
    ModelChangeEntry,
    ThinkingLevelChangeEntry,
)
from my_agent_core.skills import SkillManager
from my_agent_llm import LLM, Message
from my_agent_llm.auth.manager import AuthManager
from my_coding_agent.agent import CodingAgent
from my_coding_agent.macro import MacroEngine
from my_coding_agent.model_catalog import (
    build_models_catalog,
    resolve_initial_llm,
    resolve_model_context_window,
    switch_llm_model,
)
from my_coding_agent.paths import AgentPaths
from my_coding_agent.permissions import PermissionGate
from my_coding_agent.prompt import build_default_coding_prompt
from my_coding_agent.resource_scanner import get_all_skill_dirs, scan_loaded_resources
from my_coding_agent.serialization import (
    serialize_event,
    serialize_message,
    uuid7_str,
)
from my_coding_agent.session_ops import (
    branch_session_tree,
    build_tree_nodes,
    clone_session_tree,
    compute_session_stats,
    compute_session_usage,
    fork_session_tree,
    list_project_sessions,
    resolve_session_file,
)
from my_coding_agent.settings import Settings, load_settings, save_settings
from my_coding_agent.tracer import DebugEventTracer, export_debug_dump

__all__ = [
    "RpcServer",
    "serialize_event",
    "serialize_message",
    "uuid7_str",
    "resolve_model_context_window",
    "compute_session_usage",
    "compute_session_stats",
    "list_project_sessions",
    "resolve_session_file",
    "build_tree_nodes",
    "fork_session_tree",
    "clone_session_tree",
    "branch_session_tree",
    "switch_llm_model",
]

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure_fn = getattr(stream, "reconfigure", None)
        if callable(reconfigure_fn):
            reconfigure_fn(encoding="utf-8", errors="replace")


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
        self.session_usage: dict[str, Any] = {
            "input": 0,
            "output": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": 0,
            "cost": 0.0,
            "latestCacheHitRate": 0.0,
        }
        self.debug_mode: bool = False
        self.tracer: DebugEventTracer | None = None

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

    def _get_current_model_name(self) -> str:
        if not self.agent:
            return "default"
        cur = getattr(self.agent.agent, "model", None)
        if cur:
            return str(cur)
        llm = getattr(self.agent.agent, "llm", None)
        if llm is not None:
            cfg = getattr(llm, "config", None)
            if cfg is not None and getattr(cfg, "model", None):
                return str(getattr(cfg, "model"))
            mod = getattr(llm, "model", None)
            if mod:
                return str(mod)
        return "default"

    def _compute_session_usage(self, session: Session, model_name: str) -> dict[str, Any]:
        """对标 Pi 规范，从会话历史中提取所有 Assistant 消息的 usage 累加统计。"""
        return compute_session_usage(session, model_name)

    def _resolve_initial_llm(
        self,
        workspace_path: Path,
        explicit_model: str | None,
        settings: Settings,
        auth_mgr: AuthManager,
    ) -> LLM | None:
        """根据启动参数、工作区配置与凭证中心探测构造底层 LLM 客户端。"""
        return resolve_initial_llm(workspace_path, explicit_model, settings, auth_mgr)

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

        llm = self.llm
        if llm is None:
            llm = self._resolve_initial_llm(workspace_path, explicit_model, settings, auth_mgr)

        target_session: Session | None = None
        should_continue = bool(params.get("continue_session", False) or params.get("continue", False))
        resume_param = params.get("resume")
        s_dir = paths.project_session_dir(workspace_path)

        if resume_param and isinstance(resume_param, str) and resume_param != "true":
            for cand in [s_dir / f"{resume_param}.jsonl", s_dir / resume_param, Path(resume_param)]:
                if cand.exists():
                    try:
                        target_session = Session.load(cand)
                        break
                    except Exception:
                        continue
        elif should_continue:
            jsonl_files = sorted(s_dir.glob("*.jsonl"), key=lambda p: os.path.getmtime(p), reverse=True)
            if jsonl_files:
                try:
                    target_session = Session.load(jsonl_files[0])
                except Exception:
                    target_session = None

        if target_session is None:
            # 严格对标 Pi 原厂规范：默认启动始终创建全新的独立会话（UUIDv7），
            # 只有用户显式传入 -c / --continue 或 -r / --resume 时才续接历史会话。
            session_id = uuid7_str()
            session_file = s_dir / f"{session_id}.jsonl"
            target_session = Session(path=session_file, cwd=str(workspace_path))
            target_session.id = session_id

        if bool(params.get("no_session", False)):
            target_session.save = lambda: None  # type: ignore[method-assign]

        gate = PermissionGate(mode=mode) if mode else None
        skill_dirs = get_all_skill_dirs(workspace_path, paths)
        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=llm,
            session=target_session,
            permission_gate=gate,
            skill_dirs=skill_dirs,
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

        debug_param = bool(params.get("debug", False) or os.environ.get("MY_AGENT_DEBUG"))
        self.debug_mode = debug_param
        if self.debug_mode:
            log_file = paths.logs_dir / "debug.log"
            self.tracer = DebugEventTracer(log_path=log_file)
            self.agent.subscribe(self.tracer)

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        actual_model = getattr(getattr(self.agent.agent.llm, "config", None), "model", "default")
        actual_provider = getattr(getattr(self.agent.agent.llm, "config", None), "provider", "default")
        ctx_win = resolve_model_context_window(actual_model)
        self.session_usage = self._compute_session_usage(target_session, actual_model)
        resources = scan_loaded_resources(workspace_path, paths)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "workspace": str(workspace_path),
                "model": actual_model,
                "provider": actual_provider,
                "context_window": ctx_win,
                "contextWindow": ctx_win,
                "usage": self.session_usage,
                "thinking_level": getattr(self.agent, "thinking_level", "off"),
                "session_id": target_session.id,
                "session_file": str(target_session.path) if target_session.path else "",
                "session_name": target_session.metadata.get("name")
                or target_session.metadata.get("title")
                or target_session.id,
                "resources": resources,
                "debug": self.debug_mode,
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
                    "message": "未检测到有效模型凭据。请使用 /login <provider> <key> 绑定凭证，或在系统环境变量中配置对应 API Key。",
                },
            )

        text = params.get("text", "")
        async for event in self.agent.run_stream(text):
            if isinstance(event, MessageEnd) and event.message and event.message.role == "assistant":
                meta = event.message.metadata or {}
                usage = meta.get("usage")
                if usage and isinstance(usage, dict):
                    prompt_tok = usage.get("prompt_tokens") or usage.get("input") or 0
                    comp_tok = usage.get("completion_tokens") or usage.get("output") or 0
                    cache_read = (
                        usage.get("cache_read_tokens") or usage.get("cache_read") or usage.get("cacheRead") or 0
                    )
                    cache_write = (
                        usage.get("cache_write_tokens") or usage.get("cache_write") or usage.get("cacheWrite") or 0
                    )
                    total_tok = usage.get("total_tokens") or usage.get("total") or (prompt_tok + comp_tok)

                    self.session_usage["input"] += prompt_tok
                    self.session_usage["output"] += comp_tok
                    self.session_usage["cacheRead"] += cache_read
                    self.session_usage["cacheWrite"] += cache_write
                    self.session_usage["total"] += total_tok
                    self.session_usage["contextTokens"] = prompt_tok + comp_tok + cache_read + cache_write

                    total_prompt = prompt_tok + cache_read + cache_write
                    if total_prompt > 0 and cache_read > 0:
                        hit_rate = (cache_read / total_prompt) * 100.0
                        self.session_usage["latestCacheHitRate"] = hit_rate
                        self.session_usage["cacheHitRate"] = hit_rate

                    model_id = getattr(self.agent.agent, "model", "") or ""
                    model_lower = model_id.lower()
                    if "gemini" in model_lower:
                        self.session_usage["cost"] += (
                            prompt_tok * 0.1 + comp_tok * 0.4 + cache_read * 0.025
                        ) / 1000000.0
                    elif "claude" in model_lower:
                        if "opus" in model_lower:
                            self.session_usage["cost"] += (
                                prompt_tok * 15.0 + comp_tok * 75.0 + cache_read * 1.5
                            ) / 1000000.0
                        else:
                            self.session_usage["cost"] += (
                                prompt_tok * 3.0 + comp_tok * 15.0 + cache_read * 0.3
                            ) / 1000000.0
                    elif "deepseek" in model_lower:
                        self.session_usage["cost"] += (
                            prompt_tok * 0.14 + comp_tok * 0.28 + cache_read * 0.014
                        ) / 1000000.0
                    elif "gpt-4o" in model_lower:
                        self.session_usage["cost"] += (
                            prompt_tok * 2.5 + comp_tok * 10.0 + cache_read * 1.25
                        ) / 1000000.0

            model_name = getattr(self.agent.agent, "model", "") if self.agent else ""
            ctx_win = resolve_model_context_window(model_name)
            context_tok = 0
            ctx_inst = getattr(self.agent, "_ctx", None) or getattr(getattr(self.agent, "agent", None), "_ctx", None)
            if ctx_inst is not None:
                context_tok = getattr(ctx_inst, "total_tokens", 0) or getattr(ctx_inst, "last_token_count", 0)
            if not context_tok:
                context_tok = self.session_usage["total"]

            stats = {
                "usage": {
                    "input": self.session_usage["input"],
                    "output": self.session_usage["output"],
                    "cacheRead": self.session_usage["cacheRead"],
                    "cacheWrite": self.session_usage["cacheWrite"],
                    "cacheHitRate": self.session_usage["latestCacheHitRate"],
                    "total": self.session_usage["total"],
                    "contextTokens": context_tok,
                    "cost": self.session_usage["cost"],
                },
                "contextWindow": ctx_win,
            }

            serialized = serialize_event(event, stats=stats)
            self.send_notification("event", serialized)

        return self.send_response(req_id, result={"status": "completed"})

    def _handle_login(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        provider = params.get("provider", "").lower().strip()
        key = params.get("key", "").strip()

        paths = self.paths or AgentPaths()
        paths.ensure_directories()
        self.paths = paths
        auth_mgr = self.auth_mgr or AuthManager(auth_path=paths.auth_path)
        self.auth_mgr = auth_mgr

        # 1. 特殊处理 antigravity：自动关联本地 pi-antigravity 的 auth.json，免 Web 登录
        if provider == "antigravity":
            home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~").expanduser()
            pi_auth_candidates = [
                paths.auth_path,
                home / ".my-pi-agent" / "auth.json",
                home / ".pi" / "agent" / "auth.json",
                home / ".pi" / "auth.json",
            ]
            synced_cred: dict[str, Any] | None = None
            source_file: Path | None = None
            for p in pi_auth_candidates:
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            entry = data.get("antigravity") or data.get("google-antigravity")
                            if entry and isinstance(entry, dict):
                                synced_cred = entry
                                source_file = p
                                break
                    except Exception:
                        continue

            if synced_cred:
                target_auth = paths.auth_path
                target_auth.parent.mkdir(parents=True, exist_ok=True)
                current_data: dict[str, Any] = {}
                if target_auth.exists():
                    try:
                        current_data = json.loads(target_auth.read_text(encoding="utf-8"))
                    except Exception:
                        current_data = {}
                current_data["antigravity"] = synced_cred
                target_auth.write_text(json.dumps(current_data, indent=2, ensure_ascii=False), encoding="utf-8")

                access_tok = synced_cred.get("access") or synced_cred.get("access_token")
                if access_tok:
                    os.environ["ANTIGRAVITY_ACCESS_TOKEN"] = str(access_tok)
                email_info = f" (Google 账号: {synced_cred.get('email')})" if synced_cred.get("email") else ""
                return self.send_response(
                    req_id,
                    result={
                        "status": "ok",
                        "message": f"✓ 已成功同步并绑定 pi-antigravity 认证凭据 ({source_file}{email_info})，无需网页登录！",
                    },
                )
            elif key:
                os.environ["ANTIGRAVITY_ACCESS_TOKEN"] = key
                auth_mgr.set_api_key(provider="antigravity", key=key)
                return self.send_response(
                    req_id,
                    result={
                        "status": "ok",
                        "message": "✓ 已成功绑定 Antigravity 凭据至凭据中心！",
                    },
                )
            else:
                return self.send_response(
                    req_id,
                    result={
                        "status": "error",
                        "message": "未在 ~/.my-pi-agent/auth.json 或 ~/.pi/agent/auth.json 中检测到 antigravity 凭据。请将包含 antigravity 字段的 auth.json 放置到上述路径，或直接在登录框中粘贴 Access Token。",
                    },
                )

        # 2. 其它提供商（如 deepseek, openai, anthropic）：配置 API Key
        if not provider or not key:
            return self.send_response(
                req_id,
                result={
                    "status": "info",
                    "message": "请使用: /login <provider> <key>，例如: /login deepseek sk-xxxx 或 /login openai sk-xxxx",
                },
            )

        key_name = f"{provider.upper()}_API_KEY"
        os.environ[key_name] = key
        auth_mgr.set_api_key(provider=provider, key=key)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "message": f"✓ 已成功绑定 {provider} API Key 至全局凭据中心 (~/.my-pi-agent/auth.json)！",
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
        sessions_meta = list_project_sessions(paths, workspace_path, all_projects=all_projects)
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

        target_file, matches = resolve_session_file(session_id, paths, workspace_path)
        if matches:
            return self.send_response(
                req_id,
                error={
                    "code": -32003,
                    "message": f"Ambiguous session_id '{session_id}': {matches}",
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
        skill_dirs = get_all_skill_dirs(workspace_path, paths)
        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=llm,
            session=new_session,
            permission_gate=gate,
            skill_dirs=skill_dirs,
        )
        if self.debug_mode and self.tracer:
            self.agent.subscribe(self.tracer)

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        actual_model = self._get_current_model_name()
        ctx_win = resolve_model_context_window(actual_model)
        self.session_usage = self._compute_session_usage(new_session, actual_model)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "session_id": new_session.id,
                "session_name": new_session.metadata.get("name") or new_session.metadata.get("title") or new_session.id,
                "session_file": str(target_file),
                "cwd": new_session.cwd,
                "model": actual_model,
                "context_window": ctx_win,
                "usage": self.session_usage,
                "messages": messages_repr,
            },
        )

    def _handle_session_delete(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """删除指定历史会话文件（严格对标 Pi 规范，禁止删除当前正在使用的活跃会话）。"""
        session_id = params.get("session_id") or params.get("id") or params.get("path") or params.get("session_file")
        if not session_id:
            return self.send_response(
                req_id,
                error={"code": -32602, "message": "Missing session_id parameter"},
            )

        # 检查是否为当前正在运行的活跃会话
        current_id = self.agent.session.id if self.agent and self.agent.session else None
        current_path = (
            str(self.agent.session.path) if self.agent and self.agent.session and self.agent.session.path else ""
        )

        if session_id == current_id or session_id == current_path:
            return self.send_response(
                req_id,
                error={"code": -32005, "message": "Cannot delete the currently active session"},
            )

        paths = self.paths or AgentPaths()
        workspace_path = Path(self.agent.workspace if self.agent else params.get("workspace", ".")).resolve()

        target_file, _ = resolve_session_file(session_id, paths, workspace_path)
        if target_file is None or not target_file.is_file():
            return self.send_response(
                req_id,
                error={"code": -32004, "message": f"Session file not found for '{session_id}'"},
            )

        if current_path and target_file.resolve() == Path(current_path).resolve():
            return self.send_response(
                req_id,
                error={"code": -32005, "message": "Cannot delete the currently active session"},
            )

        try:
            target_file.unlink()
            return self.send_response(
                req_id,
                result={
                    "status": "ok",
                    "deleted": str(target_file),
                },
            )
        except Exception as exc:
            return self.send_response(
                req_id,
                error={"code": -32000, "message": f"Failed to delete session file: {exc}"},
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

    def _handle_session_stats(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """对标 Pi 官方 getSessionStats()，汇总会话全局 Message/Token/Cost 统计。"""
        if not self.agent or not self.agent.session:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        default_model = self.agent.agent.model or "default"
        default_provider = getattr(self.agent.agent.llm, "provider", "model")
        stats = compute_session_stats(
            self.agent.session,
            default_model=default_model,
            default_provider=default_provider,
        )
        return self.send_response(req_id, result={"status": "ok", "stats": stats})

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
        self.session_usage["contextTokens"] = tokens_after

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
        skill_dirs = get_all_skill_dirs(workspace_path, paths)

        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=self.agent.agent.llm,
            session=new_session,
            permission_gate=gate,
            skill_dirs=skill_dirs,
        )

        if self.debug_mode and self.tracer:
            self.agent.subscribe(self.tracer)

        # 彻底重置会话统计指标为 0
        self.session_usage = {
            "input": 0,
            "output": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "latestCacheHitRate": None,
            "cacheHitRate": None,
            "total": 0,
            "contextTokens": 0,
            "cost": 0.0,
        }
        actual_model = self._get_current_model_name()
        ctx_win = resolve_model_context_window(actual_model)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "session_id": session_id,
                "session_name": session_id,
                "session_file": str(session_file),
                "context_window": ctx_win,
                "contextWindow": ctx_win,
                "usage": self.session_usage,
                "messages": [],
            },
        )

    def _handle_session_tree(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )

        nodes, active_leaf_id, root_id = build_tree_nodes(self.agent.session)
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "nodes": nodes,
                "tree": nodes,
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

        target_id = params.get("target_id") or params.get("node_id") or params.get("entry_id") or params.get("id")
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

        self.agent.abort()
        summarize = bool(params.get("summarize", False))

        try:
            system_msgs = [m for m in self.agent.agent.messages if m.role == "system"]
            new_leaf_id, editor_text, branch_summary_text, repaired_messages = await branch_session_tree(
                session=session,
                target_id=target_id,
                summarize=summarize,
                llm=self.agent.agent.llm,
                system_messages=system_msgs,
            )
        except ValueError as exc:
            return self.send_response(
                req_id,
                error={"code": -32005, "message": str(exc)},
            )

        self.agent.agent.messages = repaired_messages
        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        actual_model = self._get_current_model_name()
        ctx_win = resolve_model_context_window(actual_model)
        self.session_usage = self._compute_session_usage(session, actual_model)

        res_payload: dict[str, Any] = {
            "status": "ok",
            "leaf_id": new_leaf_id,
            "editor_text": editor_text,
            "session_id": session.id,
            "context_window": ctx_win,
            "contextWindow": ctx_win,
            "usage": self.session_usage,
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

        self.agent.abort()
        workspace_path = Path(self.agent.workspace).resolve()
        paths = self.paths or AgentPaths()

        new_session, prompt_text, new_session_file = fork_session_tree(
            session=session,
            entry_id=entry_id,
            paths=paths,
            workspace_path=workspace_path,
        )

        mode = getattr(self.settings, "default_permission_mode", None)
        gate = self.agent.permission_gate or (PermissionGate(mode=mode) if mode else None)
        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=self.agent.agent.llm,
            session=new_session,
            permission_gate=gate,
        )
        if self.debug_mode and self.tracer:
            self.agent.subscribe(self.tracer)

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        actual_model = self._get_current_model_name()
        ctx_win = resolve_model_context_window(actual_model)
        self.session_usage = self._compute_session_usage(new_session, actual_model)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "new_session_id": new_session.id,
                "session_id": new_session.id,
                "session_name": new_session.metadata.get("name") or new_session.id,
                "session_file": str(new_session_file),
                "context_window": ctx_win,
                "contextWindow": ctx_win,
                "usage": self.session_usage,
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

        self.agent.abort()
        workspace_path = Path(self.agent.workspace).resolve()
        paths = self.paths or AgentPaths()

        new_session, clone_title, new_session_file = clone_session_tree(
            session=self.agent.session,
            paths=paths,
            workspace_path=workspace_path,
        )

        mode = getattr(self.settings, "default_permission_mode", None)
        gate = self.agent.permission_gate or (PermissionGate(mode=mode) if mode else None)
        self.agent = CodingAgent(
            workspace=workspace_path,
            llm=self.agent.agent.llm,
            session=new_session,
            permission_gate=gate,
        )
        if self.debug_mode and self.tracer:
            self.agent.subscribe(self.tracer)

        messages_repr = [serialize_message(m) for m in self.agent.agent.messages if m.role != "system"]

        actual_model = self._get_current_model_name()
        ctx_win = resolve_model_context_window(actual_model)
        self.session_usage = self._compute_session_usage(new_session, actual_model)

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "new_session_id": new_session.id,
                "session_id": new_session.id,
                "session_name": clone_title,
                "session_file": str(new_session_file),
                "context_window": ctx_win,
                "contextWindow": ctx_win,
                "usage": self.session_usage,
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

        sm = getattr(self.agent.agent, "skill_manager", None) if self.agent else None
        expanded_text, is_expanded = self.macro_engine.expand_macro(
            text,
            skills_dir=skills_dir,
            prompts_dir=prompts_dir,
            skill_manager=sm,
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

        provider = params.get("provider")
        paths = self.paths or AgentPaths()
        auth_mgr = self.auth_mgr or AuthManager(auth_path=paths.auth_path)
        default_prov = (self.settings.default_provider if self.settings else "openai") or "openai"

        new_llm, model_name, resolved_prov, err = switch_llm_model(
            current_llm=self.agent.agent.llm,
            raw_model=raw_model,
            provider=provider,
            paths=paths,
            auth_mgr=auth_mgr,
            default_provider=default_prov,
        )
        if err or new_llm is None:
            err_msg = err or "构造模型实例失败"
            code = -32602 if "Missing" in err_msg else (-32002 if "未检测到" in err_msg else -32000)
            return self.send_response(req_id, error={"code": code, "message": err_msg})

        self.agent.agent.model = model_name
        self.agent.agent.llm = new_llm
        # 压缩预算跟随模型窗口（阀值 = 80%×窗口）
        self.agent.agent.context_manager.set_budget(resolve_model_context_window(model_name))

        # 向 Session 追加 ModelChangeEntry
        entry = ModelChangeEntry(
            model=model_name,
            provider=resolved_prov,
            parent_id=self.agent.session.tree.current_id,
        )
        self.agent.session.append_entry(entry)

        # 若 persist=True，更新并持久化 settings.json
        persist = bool(params.get("persist", False))
        if persist:
            if self.settings is None:
                self.settings = load_settings(paths)
            self.settings.default_model = model_name
            if resolved_prov:
                self.settings.default_provider = resolved_prov
            save_settings(self.settings, paths.settings_path)

        ctx_win = resolve_model_context_window(model_name)
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "model": model_name,
                "provider": resolved_prov,
                "context_window": ctx_win,
                "contextWindow": ctx_win,
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

    def _handle_models_list(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        scope = params.get("scope", "configured")
        paths = self.paths or AgentPaths()
        auth_mgr = self.auth_mgr or AuthManager(auth_path=paths.auth_path)
        ws = Path(self.agent.workspace if self.agent else ".").resolve()
        configured_providers, models = build_models_catalog(
            paths=paths,
            auth_mgr=auth_mgr,
            workspace=ws,
            scope=scope,
        )
        curr = self._get_current_model_name()
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
        skill_dirs = get_all_skill_dirs(workspace_path, paths)
        skill_mgr = SkillManager(dirs=skill_dirs)
        if self.agent and hasattr(self.agent.agent, "skill_manager"):
            self.agent.agent.skill_manager = skill_mgr
        skill_count = len(skill_mgr.skills)

        resources = scan_loaded_resources(workspace_path, paths)
        template_count = len(resources.get("prompts", []))
        summary = f"Reloaded settings, project context, {skill_count} skills, and {template_count} prompt templates."
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "summary": summary,
                "skills_count": skill_count,
                "templates_count": template_count,
                "resources": resources,
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

    def _handle_debug_dump(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.agent:
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        paths = self.paths or AgentPaths()
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        dump_path = paths.logs_dir / "debug-dump.json"
        data = export_debug_dump(self.agent, dump_path)
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "dump_file": str(dump_path),
                "snapshot": data,
            },
        )

    async def _handle_shutdown(self, req_id: Any) -> dict[str, Any]:
        self.is_shutting_down = True
        if self.tracer:
            self.tracer.close()
            self.tracer = None
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
            elif method == "session_delete":
                return self._handle_session_delete(req_id, params)
            elif method == "session_history":
                return self._handle_session_history(req_id, params)
            elif method == "session_stats":
                return self._handle_session_stats(req_id, params)
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
            elif method == "debug_dump":
                return self._handle_debug_dump(req_id, params)
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
    parser = argparse.ArgumentParser(description="my-coding-agent stdio JSON-RPC server")
    parser.add_argument("-w", "--workspace", default=".", help="工作区路径")
    parser.add_argument("-m", "--model", default=None, help="LLM 模型标识符")
    parser.add_argument("-c", "--continue", dest="continue_session", action="store_true", help="续接最近一次会话")
    parser.add_argument("-r", "--resume", nargs="?", const=True, default=None, help="恢复指定会话或打开选择器")
    parser.add_argument("-n", "--name", default=None, help="为当前会话命名")
    parser.add_argument("--thinking", default=None, help="思考深度等级")
    parser.add_argument("--no-session", action="store_true", help="内存无痕模式")
    parser.add_argument("--new-session", action="store_true", help="强制开启新会话")
    parser.add_argument("-d", "--debug", action="store_true", help="启用事件级 Debug 日志落盘模式")
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
                    "debug": args.debug,
                },
            }
        )

    await server.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
