# pyright: reportOptionalMemberAccess=false
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
    ThinkingLevelChangeEntry,
)
from my_agent_llm.auth.manager import AuthManager
from my_coding_agent.agent import CodingAgent
from my_coding_agent.macro import MacroEngine
from my_coding_agent.rpc import ModelRpcMixin, SessionRpcMixin, SystemRpcMixin, require_agent
from my_coding_agent.model_catalog import (
    resolve_initial_llm,
    resolve_model_context_window,
    switch_llm_model,
)
from my_coding_agent.paths import AgentPaths
from my_coding_agent.permissions import PermissionGate
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
    estimate_model_cost,
    fork_session_tree,
    list_project_sessions,
    resolve_session_file,
)
from my_coding_agent.settings import Settings, load_settings
from my_coding_agent.tracer import DebugEventTracer

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


class RpcServer(SessionRpcMixin, ModelRpcMixin, SystemRpcMixin):
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
        self._prompt_lock = asyncio.Lock()
        self._is_prompt_running = False
        self._active_prompt_task: asyncio.Task[Any] | None = None
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

    def _bind_tracer_to_session(self, workspace_path: Path, session_id: str) -> None:
        """为当前会话动态绑定/重绑定独立的日志与事件流文件句柄。"""
        if self.debug_mode and self.paths:
            log_file = self.paths.session_log_path(workspace_path, session_id)
            events_file = self.paths.session_events_path(workspace_path, session_id)
            if self.tracer is None:
                self.tracer = DebugEventTracer(log_path=log_file, events_path=events_file)
            else:
                self.tracer.rebind(log_path=log_file, events_path=events_file)
            if self.agent:
                self.agent.subscribe(self.tracer)

    @property
    def is_prompt_running(self) -> bool:
        """检查当前是否有活跃的模型推理/Prompt 任务正在执行。"""
        return self._is_prompt_running

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
        cur = getattr(self.agent, "model", None)
        if cur:
            return str(cur)
        llm = getattr(self.agent, "llm", None)
        if llm is not None:
            cfg = getattr(llm, "config", None)
            if cfg is not None and getattr(cfg, "model", None):
                return str(cfg.model)
            mod = getattr(llm, "model", None)
            if mod:
                return str(mod)
        return "default"

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
            llm = resolve_initial_llm(workspace_path, explicit_model, settings, auth_mgr)

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
                self.agent.session.append_entry(info_entry)

        if initial_thinking := params.get("thinking"):
            thinking_str = str(initial_thinking).strip().lower()
            valid_levels = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
            if thinking_str in valid_levels:
                self.agent.thinking_level = thinking_str
                t_entry = ThinkingLevelChangeEntry(
                    thinking_level=thinking_str,
                    parent_id=self.agent.session.tree.current_id,
                )
                self.agent.session.append_entry(t_entry)

        self.macro_engine = MacroEngine(workspace=workspace_path, paths=paths)

        debug_param = bool(params.get("debug", False) or os.environ.get("MY_AGENT_DEBUG"))
        self.debug_mode = debug_param
        if self.debug_mode:
            self._bind_tracer_to_session(workspace_path, target_session.id)

        messages_repr = [serialize_message(m) for m in self.agent.messages if m.role != "system"]

        actual_model = getattr(getattr(self.agent.llm, "config", None), "model", "default")
        actual_provider = getattr(getattr(self.agent.llm, "config", None), "provider", "default")
        ctx_win = resolve_model_context_window(actual_model)
        self.session_usage = compute_session_usage(target_session, actual_model)
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
        if getattr(self.agent, "llm", None) is None:
            return self.send_response(
                req_id,
                error={
                    "code": -32002,
                    "message": "未检测到有效模型凭据。请使用 /login <provider> <key> 绑定凭证，或在系统环境变量中配置对应 API Key。",
                },
            )

        # content 支持有序内容块；旧客户端仍可使用 text。
        content = params.get("content", params.get("text", ""))
        streaming_behavior = params.get("streamingBehavior") or params.get("streaming_behavior")

        # 运行期并发分流保护：若已有活跃 prompt 正在执行，根据契约转为 steer 或 followup，杜绝任务穿透竞态
        if self._is_prompt_running:
            if streaming_behavior == "steer":
                self.agent.steer(content)
                return self.send_response(req_id, result={"status": "ok", "action": "steered"})
            elif streaming_behavior in {"followUp", "followup"}:
                self.agent.follow_up(content)
                return self.send_response(req_id, result={"status": "ok", "action": "queued"})

        current_task = asyncio.current_task()
        self._active_prompt_task = current_task
        try:
            async with self._prompt_lock:
                self._is_prompt_running = True
                try:
                    async for event in self.agent.run_stream(content):
                        if isinstance(event, MessageEnd) and event.message and event.message.role == "assistant":
                            meta = event.message.metadata or {}
                            usage = meta.get("usage")
                            if usage and isinstance(usage, dict):
                                prompt_tok = usage.get("prompt_tokens") or usage.get("input") or 0
                                comp_tok = usage.get("completion_tokens") or usage.get("output") or 0
                                cache_read = (
                                    usage.get("cache_read_tokens")
                                    or usage.get("cache_read")
                                    or usage.get("cacheRead")
                                    or 0
                                )
                                cache_write = (
                                    usage.get("cache_write_tokens")
                                    or usage.get("cache_write")
                                    or usage.get("cacheWrite")
                                    or 0
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

                                model_id = self._get_current_model_name()
                                self.session_usage["cost"] += estimate_model_cost(
                                    model_id, prompt_tok, comp_tok, cache_read
                                )

                        model_name = self._get_current_model_name()
                        ctx_win = resolve_model_context_window(model_name)
                        # 上下文占用 = 本次视图的锚定估算（与压缩门控同源）；无视图时回落最近一次单次调用规模
                        ctx_inst = getattr(self.agent, "context_manager", None)
                        context_tok = getattr(ctx_inst, "context_tokens", 0) if ctx_inst is not None else 0
                        if not context_tok:
                            context_tok = self.session_usage.get("contextTokens", 0)

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
                except asyncio.CancelledError:
                    return self.send_response(req_id, result={"status": "completed"})
                finally:
                    self._is_prompt_running = False
        finally:
            if self._active_prompt_task is current_task:
                self._active_prompt_task = None

    @require_agent
    def _handle_steer(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        msg = (
            params.get("content")
            if "content" in params
            else (params.get("message") or params.get("prompt") or params.get("text") or "")
        )
        self.agent.steer(msg)
        return self.send_response(req_id, result={"status": "ok"})

    @require_agent
    def _handle_followup(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        msg = (
            params.get("content")
            if "content" in params
            else (params.get("message") or params.get("prompt") or params.get("text") or "")
        )
        self.agent.follow_up(msg)
        return self.send_response(req_id, result={"status": "ok"})

    def _handle_abort(self, req_id: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.agent:
            self.agent.abort()
        if self._active_prompt_task and not self._active_prompt_task.done():
            self._active_prompt_task.cancel()
        return self.send_response(req_id, result={"status": "ok"})

    @require_agent
    def _handle_clear_queue(self, req_id: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
        cleared = self.agent.clear_queue()
        return self.send_response(req_id, result={"cleared": True, "count": len(cleared)})

    async def _handle_shutdown(self, req_id: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
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

        dispatch = {
            "initialize": self._handle_initialize,
            "prompt": self._handle_prompt,
            "login": self._handle_login,
            "steer": self._handle_steer,
            "followup": self._handle_followup,
            "follow_up": self._handle_followup,
            "abort": self._handle_abort,
            "clear_queue": self._handle_clear_queue,
            "session_name": self._handle_session_name,
            "session_list": self._handle_session_list,
            "session_resume": self._handle_session_resume,
            "session_delete": self._handle_session_delete,
            "session_history": self._handle_session_history,
            "session_stats": self._handle_session_stats,
            "session_compact": self._handle_session_compact,
            "session_new": self._handle_session_new,
            "session_tree": self._handle_session_tree,
            "session_branch": self._handle_session_branch,
            "session_fork": self._handle_session_fork,
            "session_clone": self._handle_session_clone,
            "shell_exec": self._handle_shell_exec,
            "macro_expand": self._handle_macro_expand,
            "models_list": self._handle_models_list,
            "model_switch": self._handle_model_switch,
            "thinking_set": self._handle_thinking_set,
            "auth_logout": self._handle_auth_logout,
            "resource_reload": self._handle_resource_reload,
            "settings_get": self._handle_settings_get,
            "settings_set": self._handle_settings_set,
            "trust_set": self._handle_trust_set,
            "debug_dump": self._handle_debug_dump,
            "shutdown": self._handle_shutdown,
        }

        handler = dispatch.get(method)
        if not handler:
            return self.send_response(
                req_id,
                error={"code": -32601, "message": f"Method '{method}' not found"},
            )

        try:
            res = handler(req_id, params)
            return await res if inspect.isawaitable(res) else res
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
