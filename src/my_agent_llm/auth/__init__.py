"""凭据管理与鉴权模块。"""

from .antigravity import (  # pyright: ignore[reportMissingImports]
    ANTIGRAVITY_USER_AGENT,
    DEFAULT_ANTIGRAVITY_ENDPOINT,
    GOOGLE_OAUTH_TOKEN_URL,
    AntigravityAuthResolver,
    AntigravityCredentials,
)
from .manager import (  # pyright: ignore[reportMissingImports]
    DEFAULT_ANTIGRAVITY_CLIENT_ID,
    DEFAULT_ANTIGRAVITY_CLIENT_SECRET,
    GOOGLE_TOKEN_URL,
    AuthManager,
)
from .quota import (  # pyright: ignore[reportMissingImports]
    QuotaBucket,
    retrieve_user_quota_summary,
)
from .schema import (  # pyright: ignore[reportMissingImports]
    ApiKeyCredential,
    AuthStore,
    Credential,
    CredentialType,
    OAuthCredential,
)

__all__ = [
    "ANTIGRAVITY_USER_AGENT",
    "DEFAULT_ANTIGRAVITY_ENDPOINT",
    "GOOGLE_OAUTH_TOKEN_URL",
    "AntigravityAuthResolver",
    "AntigravityCredentials",
    "QuotaBucket",
    "retrieve_user_quota_summary",
    # AuthManager & 凭据模型
    "DEFAULT_ANTIGRAVITY_CLIENT_ID",
    "DEFAULT_ANTIGRAVITY_CLIENT_SECRET",
    "GOOGLE_TOKEN_URL",
    "AuthManager",
    "ApiKeyCredential",
    "AuthStore",
    "Credential",
    "CredentialType",
    "OAuthCredential",
]
