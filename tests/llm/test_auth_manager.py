"""AuthManager 与凭据模型单元测试。

验证 ApiKeyCredential 解析、OAuthCredential 过期判定、AuthStore 序列化/反序列化、
平铺简写兼容、文件跨进程锁并发安全、0600 原子替换落盘与 OAuth 自动刷新。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

from filelock import FileLock, Timeout  # pyright: ignore[reportMissingImports]
import httpx
import pytest

from my_agent_llm.auth.manager import (  # pyright: ignore[reportMissingImports]
    DEFAULT_ANTIGRAVITY_CLIENT_ID,
    DEFAULT_ANTIGRAVITY_CLIENT_SECRET,
    GOOGLE_TOKEN_URL,
    AuthManager,
)
from my_agent_llm.auth.schema import (  # pyright: ignore[reportMissingImports]
    ApiKeyCredential,
    AuthStore,
    CredentialType,
    OAuthCredential,
)


def test_api_key_credential_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 API Key 解析：支持字面量、环境变量（$VAR 与 ${VAR}）及子进程执行输出（!cmd）。"""
    # 1. 字面量
    cred_literal = ApiKeyCredential(key="sk-literal-12345")
    assert cred_literal.resolve_key() == "sk-literal-12345"
    assert cred_literal.type == CredentialType.API_KEY

    # 2. 环境变量 $VAR
    monkeypatch.setenv("TEST_KEY_VAR", "sk-secret-env-123")
    cred_env = ApiKeyCredential(key="$TEST_KEY_VAR")
    assert cred_env.resolve_key() == "sk-secret-env-123"

    # 3. 环境变量 ${VAR}
    cred_env_braces = ApiKeyCredential(key="${TEST_KEY_VAR}")
    assert cred_env_braces.resolve_key() == "sk-secret-env-123"

    # 4. 未定义环境变量返回空字符串
    cred_env_unset = ApiKeyCredential(key="$UNSET_SECRET_KEY")
    assert cred_env_unset.resolve_key() == ""

    # 5. 命令执行 !command
    cmd = f"!{sys.executable} -c \"print('secret-from-command')\""
    cred_cmd = ApiKeyCredential(key=cmd)
    assert cred_cmd.resolve_key() == "secret-from-command"


def test_oauth_credential_expiration() -> None:
    """验证 OAuth 凭据过期判定逻辑与缓冲区。"""
    # 1. 远古时间戳（已过期）
    cred_expired = OAuthCredential(access="ya29.val", refresh="1//ref", expires=int(1e12))
    assert cred_expired.is_expired() is True
    assert cred_expired.type == CredentialType.OAUTH

    # 2. 遥远未来时间戳（未过期）
    cred_future = OAuthCredential(access="ya29.val", refresh="1//ref", expires=int(3e12))
    assert cred_future.is_expired() is False

    # 3. expires <= 0 表示不计算过期
    cred_permanent = OAuthCredential(access="ya29.val", refresh="1//ref", expires=0)
    assert cred_permanent.is_expired() is False

    # 4. 5分钟缓冲区测试 (buffer_ms = 300_000)
    now_ms = int(time.time() * 1000)
    # 剩余 100 秒（小于 300 秒），判定为过期
    cred_in_buffer = OAuthCredential(
        access="ya29.val",
        refresh="1//ref",
        expires=now_ms + 100_000,
    )
    assert cred_in_buffer.is_expired() is True

    # 剩余 600 秒（大于 300 秒），判定为有效
    cred_outside_buffer = OAuthCredential(
        access="ya29.val",
        refresh="1//ref",
        expires=now_ms + 600_000,
    )
    assert cred_outside_buffer.is_expired() is False


def test_auth_manager_save_and_load(tmp_path: Path) -> None:
    """验证基础凭据的设置、持久化与加载。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)

    # 1. 初始文件不存在时加载空存储
    store = mgr.load_store()
    assert store.version == 1
    assert len(store.providers) == 0

    # 2. 设置 API Key 并重新加载验证
    mgr.set_api_key("deepseek", "sk-test-deepseek")
    store_loaded = mgr.load_store()
    assert "deepseek" in store_loaded.providers
    assert store_loaded.active_profiles.get("deepseek") == "default"

    cred = mgr.get_credential("deepseek")
    assert isinstance(cred, ApiKeyCredential)
    assert cred.key == "sk-test-deepseek"

    # 3. 验证平铺简写兼容性
    flat_data = '{"openai": {"type": "api_key", "key": "sk-flat-key"}}'
    auth_file.write_text(flat_data, encoding="utf-8")
    cred_flat = mgr.get_credential("openai")
    assert isinstance(cred_flat, ApiKeyCredential)
    assert cred_flat.key == "sk-flat-key"


def test_auth_manager_flat_shorthand_oauth(tmp_path: Path) -> None:
    """验证平铺简写格式中 OAuth 凭据的兼容规范化。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)

    flat_data = {
        "antigravity": {
            "type": "oauth",
            "access": "ya29.flat-access",
            "refresh": "1//flat-refresh",
            "expires": int(3e12),
            "project_id": "custom-proj",
            "email": "user@example.com",
        }
    }
    auth_file.write_text(json.dumps(flat_data), encoding="utf-8")

    cred = mgr.get_credential("antigravity")
    assert isinstance(cred, OAuthCredential)
    assert cred.access == "ya29.flat-access"
    assert cred.refresh == "1//flat-refresh"
    assert cred.project_id == "custom-proj"
    assert cred.email == "user@example.com"


def test_auth_manager_multi_profiles(tmp_path: Path) -> None:
    """验证多 Profile 存储与指定 Profile 获取。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)

    mgr.set_api_key("openai", "sk-default-key", profile="default")
    mgr.set_api_key("openai", "sk-work-key", profile="work", base_url="https://api.work.com/v1")

    # 默认生效 profile 为 default
    cred_default = mgr.get_credential("openai")
    assert isinstance(cred_default, ApiKeyCredential)
    assert cred_default.key == "sk-default-key"

    # 显式获取 work profile
    cred_work = mgr.get_credential("openai", profile="work")
    assert isinstance(cred_work, ApiKeyCredential)
    assert cred_work.key == "sk-work-key"
    assert cred_work.base_url == "https://api.work.com/v1"

    # 切换 active profile
    store = mgr.load_store()
    store.active_profiles["openai"] = "work"
    mgr.save_store(store)

    cred_switched = mgr.get_credential("openai")
    assert isinstance(cred_switched, ApiKeyCredential)
    assert cred_switched.key == "sk-work-key"


def test_auth_manager_atomic_replacement_and_permissions(tmp_path: Path) -> None:
    """验证 save_store 使用临时文件进行原子替换并设置 0o600 权限。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)

    store = AuthStore()
    store.providers["deepseek"] = {"default": ApiKeyCredential(key="sk-atomic")}

    with patch("pathlib.Path.chmod") as mock_chmod:
        mgr.save_store(store)
        assert mock_chmod.called
        # 验证尝试调用 chmod 0o600
        mock_chmod.assert_any_call(0o600)

    # 验证最终文件存在且无残留临时文件
    assert auth_file.exists()
    assert not auth_file.with_suffix(".tmp").exists()
    assert not auth_file.with_name(f"{auth_file.name}.tmp").exists()

    # 验证落盘内容合法
    data = json.loads(auth_file.read_text(encoding="utf-8"))
    assert data["providers"]["deepseek"]["default"]["key"] == "sk-atomic"


def test_auth_manager_file_locking(tmp_path: Path) -> None:
    """验证跨进程文件锁对临界区操作的互斥保护。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file, lock_timeout=0.1)

    # 模拟外部进程持有锁
    mgr.lock_path.parent.mkdir(parents=True, exist_ok=True)
    external_lock = FileLock(str(mgr.lock_path))
    external_lock.acquire()

    try:
        # 锁被占用时，在超时后抛出 Timeout
        with pytest.raises(Timeout):
            mgr.set_api_key("deepseek", "sk-fail")
    finally:
        external_lock.release()

    # 锁释放后操作恢复正常
    mgr.set_api_key("deepseek", "sk-success")
    cred = mgr.get_credential("deepseek")
    assert isinstance(cred, ApiKeyCredential)
    assert cred.key == "sk-success"


def test_auth_manager_get_valid_token_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 API Key 获取 token 时自动解析。"""
    monkeypatch.setenv("MY_TEST_DS_KEY", "sk-ds-resolved-999")
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)
    mgr.set_api_key("deepseek", "$MY_TEST_DS_KEY")

    token = asyncio.run(mgr.get_valid_token("deepseek"))
    assert token == "sk-ds-resolved-999"


def test_auth_manager_get_valid_token_oauth_unexpired(tmp_path: Path) -> None:
    """验证未过期的 OAuth 凭据直接返回 access token，不触发网络请求。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)
    mgr.set_oauth(
        provider="antigravity",
        access="ya29.current-valid-token",
        refresh="1//refresh",
        expires=int(3e12),
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        token = asyncio.run(mgr.get_valid_token("antigravity"))
        assert token == "ya29.current-valid-token"
        assert not mock_post.called


def test_auth_manager_get_valid_token_oauth_refresh_success(tmp_path: Path) -> None:
    """验证已过期的 OAuth 凭据自动触发 Google OAuth 静默刷新并保存更新。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)
    mgr.set_oauth(
        provider="antigravity",
        access="ya29.old-expired-token",
        refresh="1//valid-refresh-token",
        expires=int(1e12),  # 已过期
    )

    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "access_token": "ya29.newly-refreshed-token",
        "expires_in": 3600,
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        token = asyncio.run(mgr.get_valid_token("antigravity"))

        assert token == "ya29.newly-refreshed-token"
        assert mock_post.called
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == GOOGLE_TOKEN_URL
        assert call_kwargs[1]["data"]["refresh_token"] == "1//valid-refresh-token"
        assert call_kwargs[1]["data"]["client_id"] == DEFAULT_ANTIGRAVITY_CLIENT_ID
        assert call_kwargs[1]["data"]["client_secret"] == DEFAULT_ANTIGRAVITY_CLIENT_SECRET

    # 验证新 token 已原子更新并持久化到 auth.json
    store = mgr.load_store()
    cred = store.providers["antigravity"]["default"]
    assert isinstance(cred, OAuthCredential)
    assert cred.access == "ya29.newly-refreshed-token"
    assert not cred.is_expired()


def test_auth_manager_get_valid_token_oauth_refresh_failure(tmp_path: Path) -> None:
    """验证 OAuth 自动刷新返回非 200 时抛出明确的 RuntimeError。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)
    mgr.set_oauth(
        provider="antigravity",
        access="ya29.old",
        refresh="1//invalid-refresh",
        expires=int(1e12),
    )

    mock_resp = MagicMock(status_code=400, text='{"error": "invalid_grant"}')

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(RuntimeError, match="OAuth Token 自动刷新失败.*400"):
            asyncio.run(mgr.get_valid_token("antigravity"))


def test_auth_manager_get_valid_token_oauth_refresh_network_error(tmp_path: Path) -> None:
    """验证 OAuth 自动刷新遭遇网络连接异常时抛出明确的 RuntimeError。"""
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)
    mgr.set_oauth(
        provider="antigravity",
        access="ya29.old",
        refresh="1//refresh-token",
        expires=int(1e12),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Network unreachable")
        with pytest.raises(RuntimeError, match="OAuth Token 自动刷新网络连接失败.*Network unreachable"):
            asyncio.run(mgr.get_valid_token("antigravity"))


def test_auth_manager_get_valid_token_missing_cred(tmp_path: Path) -> None:
    """验证未配置凭据时抛出友好提示。"""
    mgr = AuthManager(auth_path=tmp_path / "auth.json")
    with pytest.raises(RuntimeError, match="未找到提供商 'nonexistent'"):
        asyncio.run(mgr.get_valid_token("nonexistent"))


def test_auth_manager_corrupted_file(tmp_path: Path) -> None:
    """验证 auth.json 损坏或非合法 JSON 时优雅降级为空存储。"""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text("invalid json content { [ ]", encoding="utf-8")
    mgr = AuthManager(auth_path=auth_file)

    store = mgr.load_store()
    assert store.version == 1
    assert len(store.providers) == 0


def test_auth_manager_default_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """验证默认构造函数使用 MY_AGENT_HOME 环境变量解析 auth.json 路径。"""
    custom_home = tmp_path / "my_custom_agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))

    mgr = AuthManager()
    assert mgr.auth_path == (custom_home / "auth.json").resolve()
    assert mgr.lock_path == (custom_home / "auth.json.lock").resolve()
