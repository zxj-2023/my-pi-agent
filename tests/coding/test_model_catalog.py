from __future__ import annotations


from pathlib import Path
import pytest

from my_agent_llm.auth.manager import AuthManager
from my_coding_agent.paths import AgentPaths
from my_coding_agent.model_catalog import (
    KNOWN_MODEL_CATALOG,
    get_antigravity_catalog,
    get_deepseek_catalog,
    resolve_model_context_window,
    switch_llm_model,
)


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
