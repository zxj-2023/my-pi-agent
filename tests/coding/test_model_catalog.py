from __future__ import annotations


from pathlib import Path
import pytest

from my_agent_llm.auth.manager import AuthManager
from my_coding_agent.paths import AgentPaths
from my_coding_agent.model_catalog import (
    KNOWN_MODEL_CATALOG,
    build_models_catalog,
    get_antigravity_catalog,
    get_deepseek_catalog,
    resolve_initial_llm,
    resolve_model_context_window,
    switch_llm_model,
)
from my_coding_agent.settings import Settings


def test_resolve_model_context_window() -> None:
    assert resolve_model_context_window("gemini-3.8-flash") == 1048576
    assert resolve_model_context_window("claude-3-opus") == 250000
    assert resolve_model_context_window("claude-3-5-sonnet") == 200000
    assert resolve_model_context_window("gpt-4o") == 128000
    assert resolve_model_context_window("deepseek-chat") == 64000
    assert resolve_model_context_window("deepseek-flash") == 1000000


def test_known_model_catalog_structure() -> None:
    assert len(KNOWN_MODEL_CATALOG) > 0
    first = KNOWN_MODEL_CATALOG[0]
    assert "id" in first
    assert "provider" in first
    assert "contextWindow" in first


def test_catalogs_offline_fallback() -> None:
    ds = get_deepseek_catalog()
    assert len(ds) > 0
    assert all(m["provider"] == "deepseek" for m in ds)

    ag = get_antigravity_catalog()
    assert any("gemini" in m["id"] for m in ag)


def test_switch_llm_model_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    paths = AgentPaths()
    auth_mgr = AuthManager(auth_path=paths.auth_path)

    # Missing model param
    llm, m_name, prov, err = switch_llm_model(
        current_llm=None,
        raw_model="",
        provider=None,
        paths=paths,
        auth_mgr=auth_mgr,
    )
    assert err == "Missing 'model' parameter"

    # Missing API key
    class FakeLLMWithConfig:
        class ConfigObj:
            provider = "openai"

        config = ConfigObj()

    llm, m_name, prov, err = switch_llm_model(
        current_llm=FakeLLMWithConfig(),
        raw_model="gpt-4o",
        provider="openai",
        paths=paths,
        auth_mgr=auth_mgr,
    )
    assert err is not None
    assert "未检测到" in err

    # Fake LLM with .model attribute (e.g. offline testing mock)
    class FakeLLMWithModel:
        model = "old-model"

    fake = FakeLLMWithModel()
    llm, m_name, prov, err = switch_llm_model(
        current_llm=fake,
        raw_model="new-model",
        provider="openai",
        paths=paths,
        auth_mgr=auth_mgr,
    )
    assert err is None
    assert fake.model == "new-model"
    assert m_name == "new-model"


def test_switch_llm_model_when_current_llm_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    paths = AgentPaths()
    auth_mgr = AuthManager(auth_path=paths.auth_path)

    # 1. current_llm is None without API key -> returns graceful error, doesn't crash with ValueError
    llm, m_name, prov, err = switch_llm_model(
        current_llm=None,
        raw_model="gpt-4o",
        provider="openai",
        paths=paths,
        auth_mgr=auth_mgr,
    )
    assert llm is None
    assert err is not None
    assert "未检测到" in err

    # 2. current_llm is None with API key in env -> creates new LLM successfully
    monkeypatch.setenv("OPENAI_API_KEY", "sk-valid-key")
    llm, m_name, prov, err = switch_llm_model(
        current_llm=None,
        raw_model="gpt-4o",
        provider="openai",
        paths=paths,
        auth_mgr=auth_mgr,
    )
    assert err is None
    assert llm is not None
    assert llm.config.model == "gpt-4o"
    assert llm.config.api_key == "sk-valid-key"


def test_build_models_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    paths = AgentPaths()
    auth_mgr = AuthManager(auth_path=paths.auth_path)
    work = tmp_path / "work"
    work.mkdir()

    # scope="all" should return full catalog
    configured, models = build_models_catalog(paths=paths, auth_mgr=auth_mgr, workspace=work, scope="all")
    assert isinstance(configured, set)
    assert len(models) > 0
    assert all("contextWindow" in m for m in models)


def test_resolve_initial_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-init-key")
    paths = AgentPaths()
    auth_mgr = AuthManager(auth_path=paths.auth_path)
    work = tmp_path / "work"
    work.mkdir()

    settings = Settings(default_model="gpt-4o", default_provider="openai")
    llm = resolve_initial_llm(
        workspace_path=work,
        explicit_model="openai/gpt-4o",
        settings=settings,
        auth_mgr=auth_mgr,
    )
    assert llm is not None
    assert llm.config.model == "gpt-4o"
    assert llm.config.provider == "openai"
    assert llm.config.api_key == "sk-init-key"
