# ruff: noqa: S105, S106
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from my_agent_llm.auth.antigravity import (  # pyright: ignore[reportMissingImports]
    GOOGLE_OAUTH_TOKEN_URL,
    AntigravityAuthResolver,
    AntigravityCredentials,
)


def test_resolve_credentials_from_pi_auth(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    auth_data = {
        "antigravity": {
            "refresh": "1//test_refresh",
            "access": "ya29.test_access",
            "expires": int(time.time() * 1000) + 3600000,
            "projectId": "test-project-123",
            "email": "test@gmail.com",
        }
    }
    auth_file.write_text(json.dumps(auth_data), encoding="utf-8")

    resolver = AntigravityAuthResolver(pi_auth_path=auth_file)
    creds = resolver.resolve_credentials()
    assert creds is not None
    assert creds.access_token == "ya29.test_access"
    assert creds.refresh_token == "1//test_refresh"
    assert creds.project_id == "test-project-123"
    assert creds.email == "test@gmail.com"
    assert creds.auth_file_path == auth_file


def test_resolve_credentials_from_google_antigravity_key(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    auth_data = {
        "google-antigravity": {
            "refresh": "1//test_refresh_google",
            "access": "ya29.google_access",
            "expires": int(time.time() * 1000) + 3600000,
            "project_id": "google-project-456",
            "email": "dev@example.com",
        }
    }
    auth_file.write_text(json.dumps(auth_data), encoding="utf-8")

    resolver = AntigravityAuthResolver(pi_auth_path=auth_file)
    creds = resolver.resolve_credentials()
    assert creds is not None
    assert creds.access_token == "ya29.google_access"
    assert creds.refresh_token == "1//test_refresh_google"
    assert creds.project_id == "google-project-456"
    assert creds.email == "dev@example.com"


def test_resolve_credentials_from_env(monkeypatch, tmp_path: Path):
    auth_file = tmp_path / "nonexistent.json"
    monkeypatch.setenv("ANTIGRAVITY_ACCESS_TOKEN", "ya29.env_access")
    monkeypatch.setenv("ANTIGRAVITY_PROJECT_ID", "env-project-789")

    resolver = AntigravityAuthResolver(pi_auth_path=auth_file)
    creds = resolver.resolve_credentials()
    assert creds is not None
    assert creds.access_token == "ya29.env_access"
    assert creds.project_id == "env-project-789"


def test_resolve_credentials_from_credentials_json(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ANTIGRAVITY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_API_KEY", raising=False)

    creds_file = tmp_path / "credentials.json"
    creds_data = {
        "antigravity": {
            "access_token": "ya29.global_creds_access",
            "refresh_token": "1//global_refresh",
            "expires_at": int(time.time() * 1000) + 7200000,
            "project_id": "global-project-999",
            "email": "global@example.com",
        }
    }
    creds_file.write_text(json.dumps(creds_data), encoding="utf-8")

    resolver = AntigravityAuthResolver(
        pi_auth_path=tmp_path / "nonexistent.json",
        credentials_path=creds_file,
    )
    creds = resolver.resolve_credentials()
    assert creds is not None
    assert creds.access_token == "ya29.global_creds_access"
    assert creds.refresh_token == "1//global_refresh"
    assert creds.project_id == "global-project-999"
    assert creds.email == "global@example.com"


def test_resolve_credentials_detects_expiration(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    auth_data = {
        "antigravity": {
            "refresh": "1//test_refresh",
            "access": "ya29.expired_access",
            "expires": int(time.time() * 1000) - 10000,  # 已过期
            "projectId": "test-project-123",
            "email": "test@gmail.com",
        }
    }
    auth_file.write_text(json.dumps(auth_data), encoding="utf-8")

    resolver = AntigravityAuthResolver(pi_auth_path=auth_file)
    raw = resolver.resolve_credentials_raw()
    assert raw is not None
    assert resolver.is_expired(raw) is True

    # 永不过期 (expires <= 0)
    non_expiring = AntigravityCredentials(access_token="ya29.never", expires_at=0)
    assert resolver.is_expired(non_expiring) is False

    # None 视作过期
    assert resolver.is_expired(None) is True


def test_refresh_token_replaces_auth_file(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    auth_data = {
        "antigravity": {
            "refresh": "1//test_refresh",
            "access": "ya29.old_access",
            "expires": 1000,
            "projectId": "test-project-123",
            "email": "test@gmail.com",
        }
    }
    auth_file.write_text(json.dumps(auth_data), encoding="utf-8")

    resolver = AntigravityAuthResolver(pi_auth_path=auth_file)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "ya29.new_refreshed_access",
        "expires_in": 3600,
    }

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        new_creds = resolver.get_valid_credentials()
        assert new_creds.access_token == "ya29.new_refreshed_access"
        assert new_creds.project_id == "test-project-123"

        # 验证 httpx.post 参数
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == GOOGLE_OAUTH_TOKEN_URL
        assert call_kwargs[1]["data"]["refresh_token"] == "1//test_refresh"
        assert call_kwargs[1]["data"]["grant_type"] == "refresh_token"

        # 验证写回文件
        updated = json.loads(auth_file.read_text(encoding="utf-8"))
        assert updated["antigravity"]["access"] == "ya29.new_refreshed_access"
        assert updated["antigravity"]["expires"] > int(time.time() * 1000)


def test_refresh_token_missing_refresh_token_raises():
    resolver = AntigravityAuthResolver()
    creds = AntigravityCredentials(access_token="ya29.no_refresh", refresh_token=None)
    with pytest.raises(RuntimeError, match="missing refresh_token"):
        resolver.refresh(creds)


def test_refresh_token_http_error_raises():
    resolver = AntigravityAuthResolver()
    creds = AntigravityCredentials(
        access_token="ya29.old",
        refresh_token="1//test_refresh",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "invalid_grant"

    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(
            RuntimeError, match="Failed to refresh Antigravity token: 400"
        ):
            resolver.refresh(creds)


def test_get_valid_credentials_no_creds_raises(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ANTIGRAVITY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_API_KEY", raising=False)

    resolver = AntigravityAuthResolver(
        pi_auth_path=tmp_path / "nonexistent.json",
        credentials_path=tmp_path / "no_creds.json",
    )
    with pytest.raises(RuntimeError, match="No Antigravity credentials found"):
        resolver.get_valid_credentials()


def test_get_valid_credentials_does_not_refresh_when_valid(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    auth_data = {
        "antigravity": {
            "refresh": "1//test_refresh",
            "access": "ya29.valid_access",
            "expires": int(time.time() * 1000) + 3600000,
            "projectId": "test-project-123",
            "email": "test@gmail.com",
        }
    }
    auth_file.write_text(json.dumps(auth_data), encoding="utf-8")

    resolver = AntigravityAuthResolver(pi_auth_path=auth_file)

    with patch("httpx.post") as mock_post:
        creds = resolver.get_valid_credentials()
        assert creds.access_token == "ya29.valid_access"
        mock_post.assert_not_called()
