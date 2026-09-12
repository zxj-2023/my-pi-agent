"""Antigravity OAuth 鉴权与配额模块。"""

from .antigravity import (  # pyright: ignore[reportMissingImports]
    ANTIGRAVITY_USER_AGENT,
    DEFAULT_ANTIGRAVITY_ENDPOINT,
    GOOGLE_OAUTH_TOKEN_URL,
    AntigravityAuthResolver,
    AntigravityCredentials,
)

__all__ = [
    "ANTIGRAVITY_USER_AGENT",
    "DEFAULT_ANTIGRAVITY_ENDPOINT",
    "GOOGLE_OAUTH_TOKEN_URL",
    "AntigravityAuthResolver",
    "AntigravityCredentials",
]
