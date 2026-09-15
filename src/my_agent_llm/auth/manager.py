"""AuthManager: 管理 ~/.my-pi-agent/auth.json 的线程与进程安全凭据中心。"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import time
from typing import Any

from filelock import FileLock  # pyright: ignore[reportMissingImports]
import httpx

from my_agent_llm.auth.schema import (
    ApiKeyCredential,
    AuthStore,
    OAuthCredential,
)

__all__ = [
    "DEFAULT_ANTIGRAVITY_CLIENT_ID",
    "DEFAULT_ANTIGRAVITY_CLIENT_SECRET",
    "GOOGLE_TOKEN_URL",
    "AuthManager",
]

DEFAULT_ANTIGRAVITY_CLIENT_ID = os.environ.get(
    "ANTIGRAVITY_CLIENT_ID",
    "my-pi-agent-desktop-client-id",
)
DEFAULT_ANTIGRAVITY_CLIENT_SECRET = os.environ.get(
    "ANTIGRAVITY_CLIENT_SECRET",
    "my-pi-agent-desktop-client-secret",
)
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class AuthManager:
    """产品级全局凭据管理器。

    提供线程安全与跨进程文件锁保护的 auth.json 读写、Profile 调度与 OAuth 静默续期。
    """

    def __init__(
        self,
        auth_path: Path | str | None = None,
        lock_path: Path | str | None = None,
        lock_timeout: float = 5.0,
    ) -> None:
        if auth_path:
            self.auth_path = Path(auth_path).resolve()
        else:
            home = Path(
                os.environ.get("MY_AGENT_HOME")
                or Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~").expanduser() / ".my-pi-agent"
            ).resolve()
            self.auth_path = home / "auth.json"

        if lock_path:
            self.lock_path = Path(lock_path).resolve()
        else:
            self.lock_path = self.auth_path.with_name(f"{self.auth_path.name}.lock")
        self.lock_timeout = lock_timeout

    def load_store(self) -> AuthStore:
        """从 auth.json 加载并自动归一化格式。

        支持标准的 AuthStore 结构以及简写平铺格式。如果文件不存在或损坏，优雅降级为空 AuthStore。
        """
        if not self.auth_path.exists():
            return AuthStore()

        try:
            content = self.auth_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                return AuthStore()

            # 兼容扁平平铺简写格式：{"deepseek": {"type": "api_key", ...}}
            if "providers" not in data:
                normalized_providers: dict[str, Any] = {}
                for prov, item in data.items():
                    if isinstance(item, dict) and "type" in item:
                        normalized_providers[prov] = {"default": item}
                active_profiles = data.get("active_profiles")
                if not isinstance(active_profiles, dict):
                    active_profiles = {}
                version = data.get("version", 1)
                return AuthStore(
                    version=version,
                    active_profiles=active_profiles,
                    providers=normalized_providers,
                )
            return AuthStore.model_validate(data)
        except Exception:
            return AuthStore()

    def save_store(self, store: AuthStore) -> None:
        """以 0o600 权限与临时文件原子替换保存凭证。"""
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.auth_path.with_name(f"{self.auth_path.name}.tmp")
        tmp_path.write_text(store.model_dump_json(indent=2), encoding="utf-8")
        with contextlib.suppress(Exception):
            tmp_path.chmod(0o600)
        tmp_path.replace(self.auth_path)

    def set_api_key(
        self,
        provider: str,
        key: str,
        profile: str = "default",
        base_url: str | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        """安全设置指定提供商的 API Key 凭据。"""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path), timeout=self.lock_timeout):
            store = self.load_store()
            prov_dict = store.providers.setdefault(provider, {})
            prov_dict[profile] = ApiKeyCredential(
                key=key,
                base_url=base_url,
                env=env or {},
            )
            store.active_profiles.setdefault(provider, profile)
            self.save_store(store)

    def set_oauth(
        self,
        provider: str,
        access: str,
        refresh: str,
        expires: int,
        profile: str = "default",
        project_id: str = "aicode-consumers",
        email: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        **kwargs: Any,
    ) -> None:
        """安全设置指定提供商的 OAuth 凭据。"""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path), timeout=self.lock_timeout):
            store = self.load_store()
            prov_dict = store.providers.setdefault(provider, {})
            prov_dict[profile] = OAuthCredential(
                access=access,
                refresh=refresh,
                expires=expires,
                project_id=project_id,
                email=email,
                client_id=client_id,
                client_secret=client_secret,
            )
            store.active_profiles.setdefault(provider, profile)
            self.save_store(store)

    def get_credential(self, provider: str, profile: str | None = None) -> ApiKeyCredential | OAuthCredential | None:
        """获取指定提供商在指定 Profile 下的凭证（缺省为 active profile 或 default）。"""
        store = self.load_store()
        profile_name = profile or store.active_profiles.get(provider, "default")
        return store.providers.get(provider, {}).get(profile_name)

    def remove_credential(self, provider: str, profile: str | None = None) -> bool:
        """安全删除指定提供商的凭据。

        若未指定 profile，则删除该 provider 下的所有凭据及 active_profiles 映射；
        若指定了 profile，则删除对应 Profile 的凭据；若删除后该 provider 无其他 Profile，
        则同时清理其映射。
        返回 True 表示成功删除，False 表示目标凭据不存在。
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path), timeout=self.lock_timeout):
            store = self.load_store()
            removed = False
            if profile is None:
                if provider in store.providers:
                    del store.providers[provider]
                    removed = True
                if provider in store.active_profiles:
                    del store.active_profiles[provider]
                    removed = True
            else:
                if provider in store.providers and profile in store.providers[provider]:
                    del store.providers[provider][profile]
                    removed = True
                    if not store.providers[provider]:
                        del store.providers[provider]
                if store.active_profiles.get(provider) == profile:
                    if provider in store.providers and store.providers[provider]:
                        store.active_profiles[provider] = next(iter(store.providers[provider]))
                    else:
                        store.active_profiles.pop(provider, None)
            if removed:
                self.save_store(store)
            return removed

    async def get_valid_token(self, provider: str, profile: str | None = None) -> str:
        """获取有效的调用 Token，自动完成 API Key 变量解析或 OAuth 静默刷新。"""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path), timeout=max(self.lock_timeout, 10.0)):
            store = self.load_store()
            profile_name = profile or store.active_profiles.get(provider, "default")
            prov_dict = store.providers.get(provider, {})
            cred = prov_dict.get(profile_name)

            if not cred:
                raise RuntimeError(f"未找到提供商 '{provider}' (Profile: {profile_name}) 的有效凭据，请先配置或登录。")

            if isinstance(cred, ApiKeyCredential):
                return cred.resolve_key()

            if isinstance(cred, OAuthCredential):
                if not cred.is_expired():
                    return cred.access

                # 执行 OAuth 静默刷新
                client_id = cred.client_id or DEFAULT_ANTIGRAVITY_CLIENT_ID
                client_secret = cred.client_secret or DEFAULT_ANTIGRAVITY_CLIENT_SECRET
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.post(
                            GOOGLE_TOKEN_URL,
                            data={
                                "client_id": client_id,
                                "client_secret": client_secret,
                                "refresh_token": cred.refresh,
                                "grant_type": "refresh_token",
                            },
                        )
                        if resp.status_code != 200:
                            raise RuntimeError(f"OAuth Token 自动刷新失败 ({resp.status_code}): {resp.text}")
                        data = resp.json()
                except httpx.RequestError as exc:
                    raise RuntimeError(f"OAuth Token 自动刷新网络连接失败: {exc}") from exc

                new_access = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                try:
                    exp_seconds = int(expires_in)
                    now_ms = int(time.time() * 1000)
                except (ValueError, TypeError):
                    exp_seconds = 3600
                    now_ms = 0
                update_kwargs: dict[str, Any] = {
                    "access": new_access,
                    "expires": now_ms + (exp_seconds - 300) * 1000,
                }
                if "refresh_token" in data and data["refresh_token"]:
                    update_kwargs["refresh"] = data["refresh_token"]

                updated_cred = cred.model_copy(update=update_kwargs)
                prov_dict[profile_name] = updated_cred
                self.save_store(store)
                return new_access

            raise RuntimeError(f"未知的凭据类型: {type(cred)}")
