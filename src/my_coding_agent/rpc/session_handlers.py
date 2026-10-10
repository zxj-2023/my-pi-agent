# pyright: reportAttributeAccessIssue=false
"""RPC session handling mixin with @require_agent guard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from my_agent_core.session import Session, SessionInfoEntry
from my_coding_agent import AgentPaths, CodingAgent, PermissionGate
from my_coding_agent.model_catalog import resolve_model_context_window
from my_coding_agent.resource_scanner import get_all_skill_dirs
from my_coding_agent.rpc.decorators import require_agent
from my_coding_agent.serialization import serialize_message
from my_coding_agent.session_ops import (
    branch_session_tree,
    build_tree_nodes,
    clone_session_tree,
    compute_session_stats,
    fork_session_tree,
    list_project_sessions,
    resolve_session_file,
    uuid7_str,
)


class SessionRpcMixin:
    """提供所有 _handle_session_* RPC 请求的处理能力。"""

    @require_agent
    def _handle_session_name(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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
        self.agent.session.append_entry(entry)

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
        if self.debug_mode:
            self._bind_tracer_to_session(workspace_path, new_session.id)

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

    @require_agent
    def _handle_session_history(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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

    @require_agent
    def _handle_session_stats(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """对标 Pi 官方 getSessionStats()，汇总会话全局 Message/Token/Cost 统计。"""
        default_model = self.agent.agent.model or "default"
        default_provider = getattr(self.agent.agent.llm, "provider", "model")
        stats = compute_session_stats(
            self.agent.session,
            default_model=default_model,
            default_provider=default_provider,
        )
        return self.send_response(req_id, result={"status": "ok", "stats": stats})

    @require_agent
    async def _handle_session_compact(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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

    @require_agent
    def _handle_session_new(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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

        if self.debug_mode:
            self._bind_tracer_to_session(workspace_path, session_id)

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

    @require_agent
    def _handle_session_tree(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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

    @require_agent
    async def _handle_session_branch(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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

    @require_agent
    def _handle_session_fork(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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
        if self.debug_mode:
            self._bind_tracer_to_session(workspace_path, new_session.id)

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

    @require_agent
    def _handle_session_clone(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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
        if self.debug_mode:
            self._bind_tracer_to_session(workspace_path, new_session.id)

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


__all__ = [
    "SessionRpcMixin",
]
