"""模型目录、规格与远程探测模块。

负责维护模型规格、上下文窗口计算、动态探测（DeepSeek / Antigravity）与基础 LLM 实例解析。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from my_agent_llm import LLM, Config
from my_agent_llm.auth.manager import AuthManager
from my_agent_llm.auth.schema import ApiKeyCredential, OAuthCredential
from my_coding_agent.paths import AgentPaths
from my_coding_agent.settings import Settings

logger = logging.getLogger(__name__)


def resolve_model_context_window(model_name: str) -> int:
    """归一化解析模型的实际最大上下文窗口大小（Tokens）。"""
    m = (model_name or "").lower()
    if m.startswith("gemini-"):
        return 1048576
    if "opus" in m:
        return 250000
    if "sonnet" in m:
        return 200000
    if "gpt-4o" in m:
        return 128000
    if "deepseek" in m:
        return 1000000 if ("v4" in m or "flash" in m) else 64000
    return 128000


KNOWN_MODEL_CATALOG: list[dict[str, Any]] = [
    # OpenAI
    {"id": "gpt-4o", "provider": "openai", "name": "GPT-4o", "contextWindow": 128000},
    {"id": "gpt-4o-mini", "provider": "openai", "name": "GPT-4o mini", "contextWindow": 128000},
    {"id": "o1", "provider": "openai", "name": "o1", "contextWindow": 200000},
    {"id": "o3-mini", "provider": "openai", "name": "o3-mini", "contextWindow": 200000},
    # Anthropic
    {"id": "claude-3-5-sonnet-20241022", "provider": "anthropic", "name": "Claude 3.5 Sonnet", "contextWindow": 200000},
    {"id": "claude-3-5-haiku-20241022", "provider": "anthropic", "name": "Claude 3.5 Haiku", "contextWindow": 200000},
    {"id": "claude-3-opus-20240229", "provider": "anthropic", "name": "Claude 3 Opus", "contextWindow": 200000},
]


def discover_deepseek_models_remote(
    base_url: str = "https://api.deepseek.com", timeout: float = 5.0
) -> list[dict[str, Any]]:
    """主动向 DeepSeek 官方或兼容端点的 /models 接口发起探测，实时获取当前账户可用的最新模型列表。"""
    try:
        import httpx

        paths = AgentPaths()
        auth_mgr = AuthManager(auth_path=paths.auth_path)
        cred = auth_mgr.get_credential("deepseek")
        api_key = None
        if isinstance(cred, ApiKeyCredential):
            api_key = cred.resolve_key()
        elif isinstance(cred, OAuthCredential):
            api_key = cred.access
        if not api_key:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return []

        target_base = os.environ.get("DEEPSEEK_BASE_URL") or base_url
        target_base_clean = target_base.rstrip("/")
        models_url = f"{target_base_clean}/models"

        res = httpx.get(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        if res.status_code != 200:
            return []

        data = res.json()
        models_data = data.get("data", [])
        if not isinstance(models_data, list) or not models_data:
            return []

        models: list[dict[str, Any]] = []
        for item in models_data:
            m_id = item.get("id")
            if not m_id:
                continue
            ctx = 1000000 if ("v4" in m_id or "flash" in m_id) else 64000
            name = m_id
            if m_id == "deepseek-chat":
                name = "DeepSeek-V3"
            elif m_id == "deepseek-reasoner":
                name = "DeepSeek-R1"
            elif m_id == "deepseek-flash":
                name = "DeepSeek-Flash"
            elif m_id == "deepseek-v4-pro":
                name = "DeepSeek-V4 Pro"

            models.append(
                {
                    "id": m_id,
                    "provider": "deepseek",
                    "name": name,
                    "contextWindow": ctx,
                }
            )

        if models:
            cache_file = Path.home() / ".my-pi-agent" / "deepseek-model-catalog.json"
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    checked_at_ts = int(time.time() * 1000)
                except Exception:
                    checked_at_ts = 0
                cache_data = {"version": 1, "checkedAt": checked_at_ts, "models": models}
                cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.debug("写入 deepseek 缓存异常: %s", exc)

        return models
    except Exception as exc:
        logger.debug("DeepSeek 远程动态模型探测失败: %s", exc)
        return []


def get_deepseek_catalog(force: bool = False) -> list[dict[str, Any]]:
    """纯动态获取 DeepSeek 模型目录（带 4 小时本地缓存与远程动态探测）。"""
    try:
        now_ms = int(time.time() * 1000)
    except Exception:
        now_ms = 0

    cache_file = Path.home() / ".my-pi-agent" / "deepseek-model-catalog.json"
    if cache_file.exists():
        try:
            raw_text = cache_file.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            checked_at = data.get("checkedAt", 0)
            if not force and checked_at > 0 and (now_ms - checked_at < 4 * 60 * 60 * 1000):
                cached = data.get("models", [])
                if cached:
                    return cached
        except Exception as exc:
            logger.debug("读取本地 deepseek 缓存异常: %s", exc)

    remote = discover_deepseek_models_remote()
    if remote:
        return remote

    # 仅当完全没有网络且没有本地缓存时的静态离线兜底
    return [
        {"id": "deepseek-chat", "provider": "deepseek", "name": "DeepSeek-V3", "contextWindow": 64000},
        {"id": "deepseek-reasoner", "provider": "deepseek", "name": "DeepSeek-R1", "contextWindow": 64000},
    ]


def _antigravity_model_rank(model_id: str) -> tuple[int, int, str]:
    """对标 pi-antigravity grouping.ts 的 comparePublicModels 优先级排序。"""
    mid = model_id.lower()
    version = 0
    m = re.match(r"^gemini-(\d+)(?:\.(\d+))?", mid)
    if m:
        try:
            v_major = int(m.group(1))
            v_minor = int(m.group(2) or 0)
            version = v_major * 1000 + v_minor
        except (ValueError, TypeError):
            version = 0

    if "flash" in mid and "pro" not in mid:
        return (0, -version, mid)
    if mid.startswith("claude-opus"):
        return (1, 0, mid)
    if mid.startswith("claude-sonnet"):
        return (2, 0, mid)
    if mid.startswith("claude-"):
        return (3, 0, mid)
    if "pro" in mid:
        return (4, -version, mid)
    if mid.startswith("gemini-"):
        return (5, -version, mid)
    if mid.startswith("gpt-oss"):
        return (6, 0, mid)
    return (7, 0, mid)


ANTIGRAVITY_CACHE_TTL_MS = 4 * 60 * 60 * 1000  # 4 小时刷新一次，对标 pi-antigravity


def discover_antigravity_models_remote(timeout: float = 6.0) -> list[dict[str, Any]]:
    """主动向 Google Cloud Code Assist 专有接口发起 fetchAvailableModels 探测，并按 pi-antigravity 规范完成规约折叠。"""
    try:
        import httpx
        from my_agent_llm.auth.antigravity import ANTIGRAVITY_USER_AGENT, AntigravityAuthResolver

        resolver = AntigravityAuthResolver()
        creds = resolver.resolve_credentials()
        if not creds:
            return []

        headers = {
            "Authorization": f"Bearer {creds.access_token}",
            "Content-Type": "application/json",
            "User-Agent": ANTIGRAVITY_USER_AGENT,
        }
        body = {"project": creds.project_id}

        endpoints = [
            "https://daily-cloudcode-pa.googleapis.com",
            "https://cloudcode-pa.googleapis.com",
        ]

        raw_models: dict[str, Any] = {}
        for ep in endpoints:
            try:
                res = httpx.post(
                    f"{ep}/v1internal:fetchAvailableModels",
                    headers=headers,
                    json=body,
                    timeout=timeout,
                )
                if res.status_code == 200:
                    raw_models = res.json().get("models", {})
                    if raw_models:
                        break
            except Exception:
                continue

        if not raw_models:
            return []

        # 归约折叠算法 (严格对齐 pi-antigravity 的 grouping.ts)
        runtime_aliases = {
            "gemini-3-flash-agent": "gemini-3.5-flash",
            "gemini-pro-agent": "gemini-3.1-pro",
        }
        thinking_suffixes = [
            "-extra-low",
            "-extra-high",
            "-thinking",
            "-minimal",
            "-medium",
            "-high",
            "-low",
            "-tiered",
        ]

        public_groups: dict[str, dict[str, Any]] = {}
        for runtime_id, info in raw_models.items():
            if not re.match(r"^(gemini-|claude-|gpt-oss-)", runtime_id, re.I):
                continue
            if (
                any(runtime_id.startswith(p) for p in ["chat_", "tab_", "MODEL_"])
                or "image" in runtime_id
                or "2.5" in runtime_id
            ):
                continue

            public_id = runtime_aliases.get(runtime_id)
            if not public_id:
                cleaned = runtime_id
                for sfx in thinking_suffixes:
                    if cleaned.endswith(sfx):
                        cleaned = cleaned[: -len(sfx)]
                        break
                public_id = cleaned

            if public_id not in public_groups:
                display_name = info.get("displayName") or public_id
                clean_name = re.sub(
                    r"\s*\((?:extra\s*low|extra\s*high|low|medium|high|minimal|thinking)\)\s*$",
                    "",
                    display_name,
                    flags=re.I,
                ).strip()
                ctx_window = (
                    1048576
                    if public_id.startswith("gemini-")
                    else (250000 if "opus" in public_id else (200000 if "sonnet" in public_id else 131072))
                )
                public_groups[public_id] = {
                    "id": public_id,
                    "provider": "antigravity",
                    "name": f"{clean_name} (Antigravity)" if "Antigravity" not in clean_name else clean_name,
                    "contextWindow": ctx_window,
                }

        models = list(public_groups.values())
        models.sort(key=lambda x: _antigravity_model_rank(x["id"]))

        # 写入持久化缓存
        cache_file = Path.home() / ".my-pi-agent" / "antigravity-model-catalog.json"
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                checked_at_ts = int(time.time() * 1000)
            except Exception:
                checked_at_ts = 0
            cache_data = {
                "version": 1,
                "checkedAt": checked_at_ts,
                "models": models,
            }
            cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("写入本地 antigravity-model-catalog.json 异常: %s", exc)

        return models
    except Exception as exc:
        logger.debug("Antigravity 远程动态模型探测失败: %s", exc)
        return []


def get_antigravity_catalog(force: bool = False) -> list[dict[str, Any]]:
    """动态获取对标 pi-antigravity 的公共模型目录。

    1. 优先检查本地缓存（~/.my-pi-agent/ 或 ~/.pi/agent/），若在 4 小时有效期内且未强制刷新，直接返回；
    2. 若缓存缺失或已过期，主动发起远程 fetchAvailableModels 探测并更新缓存；
    3. 若网络或探测失败，回退至 pi-antigravity 官方 ANTIGRAVITY_MODELS 权威静态表。
    """
    try:
        now_ms = int(time.time() * 1000)
    except Exception:
        now_ms = 0

    # 1. 优先从本地缓存加载 (4小时TTL)
    cache_path = Path.home() / ".my-pi-agent" / "antigravity-model-catalog.json"
    if cache_path.exists():
            try:
                raw_text = cache_path.read_text(encoding="utf-8")
                data = json.loads(raw_text)
                checked_at = data.get("checkedAt", 0)
                if not force and checked_at > 0 and (now_ms - checked_at < ANTIGRAVITY_CACHE_TTL_MS):
                    models = []
                    seen = set()
                    for m in data.get("models", []):
                        mid = m.get("id")
                        if not mid or mid in seen:
                            continue
                        if (
                            any(mid.startswith(p) for p in ["chat_", "tab_", "MODEL_"])
                            or "image" in mid
                            or "2.5" in mid
                        ):
                            continue
                        seen.add(mid)
                        models.append(
                            {
                                "id": mid,
                                "provider": "antigravity",
                                "name": m.get("name") or f"{mid} (Antigravity)",
                                "contextWindow": m.get("contextWindow", 1048576),
                            }
                        )
                    if models:
                        models.sort(key=lambda x: _antigravity_model_rank(x["id"]))
                        return models
            except Exception as exc:
                logger.debug("读取本地缓存 %s 异常: %s", cache_path, exc)

    # 2. 尝试远程动态探测
    remote_models = discover_antigravity_models_remote()
    if remote_models:
        return remote_models

    # 3. pi-antigravity 官方 ANTIGRAVITY_MODELS 权威静态表
    fallback = [
        {
            "id": "gemini-3.8-flash",
            "provider": "antigravity",
            "name": "Gemini 3.8 Flash (Antigravity)",
            "contextWindow": 1048576,
        },
        {
            "id": "gemini-3.7-flash",
            "provider": "antigravity",
            "name": "Gemini 3.7 Flash (Antigravity)",
            "contextWindow": 1048576,
        },
        {
            "id": "gemini-3.6-flash",
            "provider": "antigravity",
            "name": "Gemini 3.6 Flash (Antigravity)",
            "contextWindow": 1048576,
        },
        {
            "id": "gemini-3.5-flash",
            "provider": "antigravity",
            "name": "Gemini 3.5 Flash (Antigravity)",
            "contextWindow": 1048576,
        },
        {
            "id": "gemini-3.1-pro",
            "provider": "antigravity",
            "name": "Gemini 3.1 Pro (Antigravity)",
            "contextWindow": 1048576,
        },
        {
            "id": "gemini-3-pro",
            "provider": "antigravity",
            "name": "Gemini 3 Pro (Antigravity)",
            "contextWindow": 1048576,
        },
        {
            "id": "claude-3-7-sonnet",
            "provider": "antigravity",
            "name": "Claude 3.7 Sonnet (Antigravity)",
            "contextWindow": 200000,
        },
        {
            "id": "claude-3-5-sonnet",
            "provider": "antigravity",
            "name": "Claude 3.5 Sonnet (Antigravity)",
            "contextWindow": 200000,
        },
        {
            "id": "claude-3-5-haiku",
            "provider": "antigravity",
            "name": "Claude 3.5 Haiku (Antigravity)",
            "contextWindow": 200000,
        },
        {
            "id": "claude-3-opus",
            "provider": "antigravity",
            "name": "Claude 3 Opus (Antigravity)",
            "contextWindow": 250000,
        },
    ]
    fallback.sort(key=lambda x: _antigravity_model_rank(x["id"]))
    return fallback


def get_configured_providers(
    paths: AgentPaths | None = None,
    auth_mgr: AuthManager | None = None,
    workspace: Path | None = None,
) -> set[str]:
    """探测当前环境中已配置凭证的提供商集合。"""
    configured: set[str] = set()
    paths = paths or AgentPaths()
    auth_mgr = auth_mgr or AuthManager(auth_path=paths.auth_path)

    for p in ["deepseek", "openai", "anthropic", "antigravity"]:
        if auth_mgr.get_credential(p) is not None:
            configured.add(p)
            continue
        key_name = "ANTIGRAVITY_ACCESS_TOKEN" if p == "antigravity" else f"{p.upper()}_API_KEY"
        if os.environ.get(key_name):
            configured.add(p)
            continue
        if p == "antigravity":
            try:
                from my_agent_llm.auth.antigravity import AntigravityAuthResolver

                ws = (workspace or Path(".")).resolve()
                resolver = AntigravityAuthResolver(workspace=ws)
                if resolver.resolve_credentials() is not None:
                    configured.add("antigravity")
            except Exception:
                pass

    return configured


def build_models_catalog(
    paths: AgentPaths | None = None,
    auth_mgr: AuthManager | None = None,
    workspace: Path | None = None,
    scope: str = "configured",
) -> tuple[set[str], list[dict[str, Any]]]:
    """组装返回全量模型目录列表与已配置提供商集合。"""
    configured_providers = get_configured_providers(paths=paths, auth_mgr=auth_mgr, workspace=workspace)

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

    is_antigravity_configured = "antigravity" in configured_providers
    if scope == "all" or is_antigravity_configured:
        for item in get_antigravity_catalog():
            models.append(
                {
                    **item,
                    "is_configured": is_antigravity_configured,
                }
            )

    is_deepseek_configured = "deepseek" in configured_providers
    if scope == "all" or is_deepseek_configured:
        for item in get_deepseek_catalog():
            models.append(
                {
                    **item,
                    "is_configured": is_deepseek_configured,
                }
            )

    custom_model = os.environ.get("OPENAI_MODEL") or os.environ.get("DEEPSEEK_MODEL")
    if custom_model and not any(m["id"] == custom_model for m in models):
        prov = (
            "deepseek"
            if "deepseek" in configured_providers
            else ("openai" if "openai" in configured_providers else "default")
        )
        if prov in configured_providers or scope == "all":
            ctx_win = resolve_model_context_window(custom_model)
            models.insert(
                0,
                {
                    "id": custom_model,
                    "provider": prov,
                    "name": custom_model,
                    "contextWindow": ctx_win,
                    "context_window": ctx_win,
                    "is_configured": prov in configured_providers,
                },
            )

    for m in models:
        ctx = m.get("contextWindow") or m.get("context_window") or resolve_model_context_window(m.get("id", ""))
        m["contextWindow"] = ctx
        m["context_window"] = ctx

    return configured_providers, models


def resolve_initial_llm(
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
        has_deepseek_cred = bool(os.environ.get("DEEPSEEK_API_KEY") or auth_mgr.get_credential("deepseek"))
        provider = "deepseek" if has_deepseek_cred else ("openai" if explicit_model else None)
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

    if provider == "deepseek":
        cred = auth_mgr.get_credential("deepseek")
        if isinstance(cred, ApiKeyCredential):
            api_key = cred.resolve_key()
        if not api_key:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    elif provider == "openai":
        cred = auth_mgr.get_credential("openai")
        if isinstance(cred, ApiKeyCredential):
            api_key = cred.resolve_key()
        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL")
    elif provider == "anthropic":
        cred = auth_mgr.get_credential("anthropic")
        if isinstance(cred, ApiKeyCredential):
            api_key = cred.resolve_key()
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
    elif provider == "antigravity":
        from my_agent_llm.auth.antigravity import AntigravityAuthResolver

        resolver = AntigravityAuthResolver(workspace=workspace_path)
        credentials = resolver.resolve_credentials()
        if credentials:
            api_key = credentials.access_token

    if not provider:
        return None

    config = Config(
        provider=provider,
        model=model_name or "gpt-4o",
        api_key=api_key,
        base_url=base_url,
    )
    return LLM(config)


def switch_llm_model(
    current_llm: Any,
    raw_model: str,
    provider: str | None,
    paths: AgentPaths,
    auth_mgr: AuthManager,
    default_provider: str = "openai",
) -> tuple[LLM | None, str, str | None, str | None]:
    """根据请求的模型标识符与提供商推导凭证并构造/更新 LLM 实例。

    返回 (new_llm, model_name, provider, error_message)。
    若成功，error_message 为 None；若校验或构造失败，返回 (None, model_name, provider, error_message)。
    """
    raw_model = (raw_model or "").strip()
    if not raw_model:
        return None, "", None, "Missing 'model' parameter"

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
                current_config = getattr(current_llm, "config", None)
                if current_config and hasattr(current_config, "provider"):
                    provider = current_config.provider
                else:
                    provider = default_provider

    if current_llm is not None and not hasattr(current_llm, "config") and hasattr(current_llm, "model"):
        setattr(current_llm, "model", model_name)
        return current_llm, model_name, provider, None

    api_key = None
    base_url = None
    if provider:
        cred = auth_mgr.get_credential(provider)
        if cred is not None:
            if isinstance(cred, ApiKeyCredential):
                api_key = cred.resolve_key()
                if cred.base_url:
                    base_url = cred.base_url
            elif isinstance(cred, OAuthCredential):
                api_key = cred.access

        if not api_key:
            api_key = os.environ.get(f"{provider.upper()}_API_KEY")
            base_url = os.environ.get(f"{provider.upper()}_BASE_URL")
            if provider == "antigravity":
                api_key = api_key or os.environ.get("ANTIGRAVITY_ACCESS_TOKEN") or os.environ.get("GOOGLE_ACCESS_TOKEN")

        if provider == "deepseek" and not base_url:
            base_url = "https://api.deepseek.com"

    prov_name = provider or "openai"
    if not api_key and prov_name != "antigravity":
        return (
            None,
            model_name,
            provider,
            f"未检测到 {prov_name} 的有效 API Key。请使用 /login {prov_name} <key> 绑定凭据，或在系统环境变量中配置 {prov_name.upper()}_API_KEY。",
        )

    try:
        new_config = Config(
            provider=provider or "openai",
            model=model_name,
            api_key=api_key,
            base_url=base_url,
        )
        return LLM(config=new_config), model_name, provider, None
    except Exception as exc:
        return None, model_name, provider, f"构造模型实例失败: {exc}"
