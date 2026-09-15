"""AuthStore 强类型凭证实体模型与模式定义。"""

from __future__ import annotations

from enum import Enum
import os
import shlex
import subprocess
import time
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field

__all__ = [
    "CredentialType",
    "ApiKeyCredential",
    "OAuthCredential",
    "Credential",
    "AuthStore",
]


class CredentialType(str, Enum):
    """凭证类型枚举。"""

    API_KEY = "api_key"
    OAUTH = "oauth"


class ApiKeyCredential(BaseModel):
    """API Key 凭据模型。"""

    type: Literal[CredentialType.API_KEY, "api_key"] = CredentialType.API_KEY
    key: str
    base_url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    def resolve_key(self) -> str:
        """解析 API Key：处理字面量、!command 子进程输出与 $ENV_VAR/${ENV_VAR} 语法。"""
        raw = self.key.strip()
        if raw.startswith("!"):
            cmd = raw[1:].strip()
            if os.name == "nt":
                parts = [
                    p.strip('"') if (p.startswith('"') and p.endswith('"')) else p
                    for p in shlex.split(cmd, posix=False)
                ]
            else:
                parts = shlex.split(cmd)
            if not parts:
                return ""
            res = subprocess.run(parts, capture_output=True, text=True, check=True)
            return res.stdout.strip()
        if raw.startswith("$"):
            var_name = raw[1:].strip("{}")
            return os.environ.get(var_name, "")
        return raw


class OAuthCredential(BaseModel):
    """OAuth 凭据模型（支持 Google Cloud Code / Antigravity）。"""

    type: Literal[CredentialType.OAUTH, "oauth"] = CredentialType.OAUTH
    access: str
    refresh: str
    expires: int = 0  # 毫秒时间戳，<=0 表示永久或不计算过期
    project_id: str = "aicode-consumers"
    email: str | None = None
    client_id: str | None = None
    client_secret: str | None = None

    def is_expired(self, buffer_ms: int = 300_000) -> bool:
        """判定凭证是否已过期。

        默认包含 5 分钟 (300,000ms) 缓冲期，保证在真正过期前完成自动刷新。
        当 expires <= 0 时视为不计算过期。
        """
        if self.expires <= 0:
            return False
        return self.expires <= int(time.time() * 1000) + buffer_ms


# 使用 Pydantic 区分联合体，基于 `type` 字段精准反序列化
Credential = Annotated[
    Union[ApiKeyCredential, OAuthCredential],
    Field(discriminator="type"),
]


class AuthStore(BaseModel):
    """全局统一凭证存储实体（映射 ~/.my-pi-agent/auth.json）。"""

    version: int = 1
    active_profiles: dict[str, str] = Field(default_factory=dict)
    providers: dict[str, dict[str, Credential]] = Field(default_factory=dict)
