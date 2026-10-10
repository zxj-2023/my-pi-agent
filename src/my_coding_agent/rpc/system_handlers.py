# pyright: reportAttributeAccessIssue=false
"""RPC system, configuration & environment management mixin."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from my_agent_core.skills import SkillManager
from my_agent_llm.auth.manager import AuthManager
from my_agent_llm.models import Message
from my_coding_agent import AgentPaths
from my_coding_agent.model_catalog import switch_llm_model
from my_coding_agent.prompt import build_default_coding_prompt
from my_coding_agent.resource_scanner import get_all_skill_dirs, scan_loaded_resources
from my_coding_agent.rpc.decorators import require_agent
from my_coding_agent.settings import load_settings, save_settings
from my_coding_agent.tracer import export_debug_dump


class SystemRpcMixin:
    """提供 Shell、宏扩展、Settings、Trust 和调试排查等系统管理 RPC 处理能力。"""

    @require_agent
    async def _handle_shell_exec(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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

    def _handle_resource_reload(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        paths = self.paths or AgentPaths()
        workspace_path = Path(self.agent.workspace if self.agent else ".").resolve()

        # 1. 重载 settings 与 auth 凭据中心
        self.settings = load_settings(paths, cwd=workspace_path)
        self.auth_mgr = AuthManager(auth_path=paths.auth_path)

        # 2. 热重载当前活跃 LLM 实例（重新绑定最新凭据）
        if self.agent and getattr(self.agent.agent, "llm", None):
            current_model = self._get_current_model_name()
            current_prov = getattr(getattr(self.agent.agent.llm, "config", None), "provider", None)
            new_llm, _, _, _ = switch_llm_model(
                current_llm=self.agent.agent.llm,
                raw_model=current_model,
                provider=current_prov,
                paths=paths,
                auth_mgr=self.auth_mgr,
                default_provider=self.settings.default_provider if self.settings else "openai",
            )
            if new_llm is not None:
                self.agent.agent.llm = new_llm

        # 3. 重载 skills 与 subagents
        skill_dirs = get_all_skill_dirs(workspace_path, paths)
        skill_mgr = SkillManager(dirs=skill_dirs)
        if self.agent and hasattr(self.agent.agent, "skill_manager"):
            self.agent.agent.skill_manager = skill_mgr
        skill_count = len(skill_mgr.skills)

        from my_agent_core.subagents import SubagentManager

        extra_subagent_dirs = (
            self.agent.agent.plugin_manager.get_subagent_dirs()
            if (self.agent and hasattr(self.agent.agent, "plugin_manager"))
            else None
        )
        subagent_mgr = SubagentManager(extra_dirs=extra_subagent_dirs)
        subagent_count = len(subagent_mgr.subagents)
        if self.agent and hasattr(self.agent.agent, "subagent_manager"):
            self.agent.agent.subagent_manager = subagent_mgr
            if subagent_mgr:
                from my_agent_core.tools.builtin.task import make_task_tool

                self.agent.agent.registry.register(make_task_tool(subagent_mgr, self.agent.agent))
            else:
                self.agent.agent.registry.unregister("task")

        # 4. 重载项目指导文件与系统提示词
        tools = self.agent.agent.registry.list() if (self.agent and hasattr(self.agent.agent, "registry")) else None
        new_prompt = build_default_coding_prompt(workspace_path, tools=tools)
        if self.agent:
            self.agent.agent._system_prompt = new_prompt

            mem_store = getattr(self.agent.agent, "memory_store", None)
            mem_prompt = (
                mem_store.format_all_for_system_prompt()
                if mem_store is not None and hasattr(mem_store, "format_all_for_system_prompt")
                else None
            )
            skill_prompt = skill_mgr.format_prompt()
            subagent_prompt = subagent_mgr.format_prompt()
            parts = [p for p in (new_prompt, skill_prompt, subagent_prompt, mem_prompt) if p]
            new_sys_content = "\n\n".join(parts)

            if self.agent.agent.messages and self.agent.agent.messages[0].role == "system":
                self.agent.agent.messages[0] = Message(role="system", content=new_sys_content)
            elif parts:
                self.agent.agent.messages.insert(0, Message(role="system", content=new_sys_content))

        resources = scan_loaded_resources(workspace_path, paths)
        template_count = len(resources.get("prompts", []))
        summary = (
            f"Reloaded settings, project context, {skill_count} skills, "
            f"{subagent_count} subagents, and {template_count} prompt templates."
        )
        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "summary": summary,
                "skills_count": skill_count,
                "subagents_count": subagent_count,
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

    @require_agent
    def _handle_debug_dump(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        paths = self.paths or AgentPaths()
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        dump_path = paths.logs_dir / "debug-dump.json"
        data = export_debug_dump(self.agent, dump_path)
        result: dict[str, Any] = {
            "status": "ok",
            "dump_file": str(dump_path),
            "snapshot": data,
        }
        if self.tracer:
            if self.tracer.log_path:
                result["log_file"] = str(self.tracer.log_path)
            if self.tracer.events_path:
                result["events_file"] = str(self.tracer.events_path)
        return self.send_response(req_id, result=result)


__all__ = [
    "SystemRpcMixin",
]
