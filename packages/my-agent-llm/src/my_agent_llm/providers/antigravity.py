from __future__ import annotations

import os
from typing import Any

import openai

from ..auth.antigravity import (
    ANTIGRAVITY_USER_AGENT,
    DEFAULT_ANTIGRAVITY_ENDPOINT,
    AntigravityAuthResolver,
)
from ..config import Config
from .openai import OpenAIProvider


class AntigravityProvider(OpenAIProvider):
    """Google Cloud Code Assist (Antigravity) 模型提供商适配器。"""

    def __init__(
        self,
        config: Config,
        client: Any | None = None,
        async_client: Any | None = None,
    ) -> None:
        self.auth_resolver = AntigravityAuthResolver()
        base_url = (
            config.base_url
            or os.environ.get("ANTIGRAVITY_BASE_URL")
            or DEFAULT_ANTIGRAVITY_ENDPOINT
        )

        # 自动解析有效 Token
        api_key = config.api_key
        self.project_id = os.environ.get("ANTIGRAVITY_PROJECT_ID", "aicode-consumers")
        if not api_key:
            try:
                creds = self.auth_resolver.get_valid_credentials()
                api_key = creds.access_token
                self.project_id = creds.project_id
            except Exception:
                api_key = "placeholder_token"  # noqa: S105

        config = config.model_copy(
            update={
                "base_url": base_url,
                "api_key": api_key,
            }
        )
        self.base_url = base_url
        self.config = config

        if client is None or async_client is None:
            headers = self._build_headers()
            kwargs: dict[str, Any] = {
                "api_key": config.api_key,
                "timeout": config.timeout,
                "max_retries": config.max_retries,
                "base_url": config.base_url,
                "default_headers": headers,
            }
            if client is None:
                client = openai.OpenAI(**kwargs)
            if async_client is None:
                async_client = openai.AsyncOpenAI(**kwargs)

        super().__init__(config, client=client, async_client=async_client)

    def _build_headers(self) -> dict[str, str]:
        token = self.config.api_key or ""
        return {
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": self.project_id,
            "User-Agent": ANTIGRAVITY_USER_AGENT,
            "Content-Type": "application/json",
        }
