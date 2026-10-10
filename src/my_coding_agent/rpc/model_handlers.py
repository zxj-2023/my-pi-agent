# pyright: reportAttributeAccessIssue=false
"""RPC model & authentication handling mixin."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from my_agent_core.session import ModelChangeEntry, ThinkingLevelChangeEntry
from my_agent_llm.auth.manager import AuthManager
from my_coding_agent import AgentPaths
from my_coding_agent.model_catalog import (
    build_models_catalog,
    resolve_model_context_window,
    switch_llm_model,
)
from my_coding_agent.rpc.decorators import require_agent
from my_coding_agent.settings import load_settings, save_settings


class ModelRpcMixin:
    """提供模型管理、切换、登录与认证的 RPC Handler 能力。"""

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

        # 3. 若当前模型正在使用该提供商，立刻原地热更新当前活跃模型实例
        if self.agent and getattr(self.agent.agent, "llm", None):
            current_prov = getattr(getattr(self.agent.agent.llm, "config", None), "provider", None)
            if current_prov == provider:
                current_model = self._get_current_model_name()
                new_llm, _, _, _ = switch_llm_model(
                    current_llm=self.agent.agent.llm,
                    raw_model=current_model,
                    provider=current_prov,
                    paths=paths,
                    auth_mgr=auth_mgr,
                    default_provider=self.settings.default_provider if self.settings else "openai",
                )
                if new_llm is not None:
                    self.agent.agent.llm = new_llm

        return self.send_response(
            req_id,
            result={
                "status": "ok",
                "message": f"✓ 已成功绑定 {provider} API Key 至全局凭据中心 (~/.my-pi-agent/auth.json)！",
            },
        )

    @require_agent
    def _handle_model_switch(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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

    @require_agent
    def _handle_thinking_set(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
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

        self.agent.thinking_level = level

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


__all__ = [
    "ModelRpcMixin",
]
