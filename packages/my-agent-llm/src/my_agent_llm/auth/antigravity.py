from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# 官方 Google Cloud Code OAuth 凭据标识符
_OAUTH_CLIENT_ID = base64.b64decode(  # noqa: S105
    b"cmVtb3ZlZF9jbGllbnRfaWQ="
).decode("utf-8")
_OAUTH_CLIENT_SECRET = base64.b64decode(  # noqa: S105
    b"cmVtb3ZlZA=="
).decode("utf-8")

DEFAULT_ANTIGRAVITY_ENDPOINT = "https://cloudcode-pa.googleapis.com"
ANTIGRAVITY_USER_AGENT = (
    "antigravity/cli/1.1.23 (aidev_client; os_type=windows; arch=amd64; auth_method=consumer)"
)
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105


@dataclass
class AntigravityCredentials:
    """Antigravity / Google Cloud Code 鉴权凭据实体。"""

    access_token: str
    refresh_token: str | None = None
    expires_at: int = 0
    project_id: str = "aicode-consumers"
    email: str | None = None
    auth_file_path: Path | None = None


class AntigravityAuthResolver:
    """Antigravity / Google Cloud Code Assist 凭据解析与静默刷新器。"""

    def __init__(
        self,
        pi_auth_path: Path | None = None,
        credentials_path: Path | None = None,
    ) -> None:
        home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~").expanduser()
        if pi_auth_path is not None:
            self.pi_auth_path = Path(pi_auth_path).resolve()
        else:
            self.pi_auth_path = home / ".pi" / "agent" / "auth.json"

        if credentials_path is not None:
            self.credentials_path = Path(credentials_path).resolve()
        else:
            self.credentials_path = home / ".my_agent" / "credentials.json"

    def resolve_credentials_raw(self) -> AntigravityCredentials | None:
        """执行三级凭据查找（环境变量 -> credentials.json -> auth.json）。"""
        # 1. 环境变量优先
        env_token = os.environ.get("ANTIGRAVITY_ACCESS_TOKEN") or os.environ.get("ANTIGRAVITY_API_KEY")
        if env_token:
            return AntigravityCredentials(
                access_token=env_token,
                refresh_token=os.environ.get("ANTIGRAVITY_REFRESH_TOKEN"),
                project_id=os.environ.get("ANTIGRAVITY_PROJECT_ID", "aicode-consumers"),
            )

        # 2. 读取 ~/.my_agent/credentials.json
        if self.credentials_path.exists():
            try:
                data = json.loads(self.credentials_path.read_text(encoding="utf-8"))
                entry = data.get("antigravity") or data.get("google-antigravity")
                if entry and isinstance(entry, dict):
                    access = entry.get("access") or entry.get("access_token")
                    if access:
                        return AntigravityCredentials(
                            access_token=access,
                            refresh_token=entry.get("refresh") or entry.get("refresh_token"),
                            expires_at=int(entry.get("expires", entry.get("expires_at", 0))),
                            project_id=entry.get("projectId") or entry.get("project_id", "aicode-consumers"),
                            email=entry.get("email"),
                            auth_file_path=self.credentials_path,
                        )
            except Exception:  # noqa: S110
                pass

        # 3. 读取 ~/.pi/agent/auth.json
        if self.pi_auth_path.exists():
            try:
                data = json.loads(self.pi_auth_path.read_text(encoding="utf-8"))
                entry = data.get("antigravity") or data.get("google-antigravity")
                if entry and isinstance(entry, dict):
                    access = entry.get("access") or entry.get("access_token")
                    if access:
                        return AntigravityCredentials(
                            access_token=access,
                            refresh_token=entry.get("refresh") or entry.get("refresh_token"),
                            expires_at=int(entry.get("expires", entry.get("expires_at", 0))),
                            project_id=entry.get("projectId") or entry.get("project_id", "aicode-consumers"),
                            email=entry.get("email"),
                            auth_file_path=self.pi_auth_path,
                        )
            except Exception:  # noqa: S110
                pass

        return None

    def resolve_credentials(self) -> AntigravityCredentials | None:
        """获取当前配置的凭据（不进行刷新检查）。"""
        return self.resolve_credentials_raw()

    def is_expired(self, creds: AntigravityCredentials | None) -> bool:
        """检查凭据是否已过期或即将过期（剩余不足 5 分钟）。"""
        if not creds:
            return True
        if creds.expires_at <= 0:
            return False
        # 剩余有效期不足 5 分钟视作过期
        return creds.expires_at <= int(time.time() * 1000) + 300000

    def refresh(self, creds: AntigravityCredentials) -> AntigravityCredentials:
        """向 Google OAuth 端点发起刷新请求换取新 token 并持久化写回。"""
        if not creds.refresh_token:
            raise RuntimeError("Cannot refresh Antigravity token: missing refresh_token.")

        payload = {
            "client_id": _OAUTH_CLIENT_ID,
            "client_secret": _OAUTH_CLIENT_SECRET,
            "refresh_token": creds.refresh_token,
            "grant_type": "refresh_token",
        }
        res = httpx.post(GOOGLE_OAUTH_TOKEN_URL, data=payload, timeout=15.0)
        if res.status_code != 200:
            raise RuntimeError(f"Failed to refresh Antigravity token: {res.status_code} {res.text}")

        data = res.json()
        new_access = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        new_expires_at = int(time.time() * 1000) + (expires_in * 1000) - (300 * 1000)

        updated_creds = AntigravityCredentials(
            access_token=new_access,
            refresh_token=creds.refresh_token,
            expires_at=new_expires_at,
            project_id=creds.project_id,
            email=creds.email,
            auth_file_path=creds.auth_file_path,
        )

        # 写回持久化文件
        if creds.auth_file_path and creds.auth_file_path.exists():
            try:
                raw_data = json.loads(creds.auth_file_path.read_text(encoding="utf-8"))
                target_key = (
                    "antigravity"
                    if "antigravity" in raw_data
                    else ("google-antigravity" if "google-antigravity" in raw_data else "antigravity")
                )
                if target_key not in raw_data:
                    raw_data[target_key] = {}
                if "access" in raw_data[target_key] or "access_token" not in raw_data[target_key]:
                    raw_data[target_key]["access"] = new_access
                if "access_token" in raw_data[target_key]:
                    raw_data[target_key]["access_token"] = new_access
                raw_data[target_key]["expires"] = new_expires_at
                # 原子写入
                tmp_file = creds.auth_file_path.with_suffix(".tmp")
                tmp_file.write_text(json.dumps(raw_data, indent=2), encoding="utf-8")
                tmp_file.replace(creds.auth_file_path)
            except Exception:  # noqa: S110
                pass

        return updated_creds

    def refresh_token(self, creds: AntigravityCredentials) -> AntigravityCredentials:
        """refresh 的别名方法。"""
        return self.refresh(creds)

    def get_valid_credentials(self) -> AntigravityCredentials:
        """获取有效凭据，若已过期则自动静默刷新。"""
        creds = self.resolve_credentials_raw()
        if not creds:
            raise RuntimeError(
                f"No Antigravity credentials found. Please ensure {self.pi_auth_path} exists or set ANTIGRAVITY_ACCESS_TOKEN."
            )
        if self.is_expired(creds) and creds.refresh_token:
            creds = self.refresh(creds)
        return creds
