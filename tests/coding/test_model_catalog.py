from __future__ import annotations


from my_coding_agent.model_catalog import (
    KNOWN_MODEL_CATALOG,
    get_antigravity_catalog,
    get_deepseek_catalog,
    resolve_model_context_window,
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
