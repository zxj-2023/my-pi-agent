# pyright: reportMissingImports=false
import pytest
from unittest.mock import AsyncMock, MagicMock
from my_pi_eval.agent import MyPiAgent


def test_my_pi_agent_metadata():
    agent = MyPiAgent()
    assert agent.name() == "my-pi-agent"
    assert agent.version() == "0.1.1"


@pytest.mark.anyio
async def test_my_pi_agent_run_execution(tmp_path):
    agent = MyPiAgent()
    fake_env = MagicMock()
    fake_context = MagicMock()
    fake_context.model = "fake-model"
    fake_context.logs_dir = tmp_path

    agent._build_coding_agent = MagicMock()
    mock_inner_agent = MagicMock()
    mock_inner_agent.run = AsyncMock(return_value="Task complete")
    mock_inner_agent.agent = MagicMock()
    mock_inner_agent.agent.context_manager = MagicMock()
    mock_inner_agent.agent.context_manager.token_tracker = MagicMock()
    mock_inner_agent.agent.context_manager.token_tracker.prompt_tokens = 100
    mock_inner_agent.agent.context_manager.token_tracker.completion_tokens = 50
    mock_inner_agent.agent.context_manager.token_tracker.cache_read_tokens = 20
    agent._build_coding_agent.return_value = mock_inner_agent

    await agent.run("Fix the bug", fake_env, fake_context)
    mock_inner_agent.run.assert_awaited_once_with("Fix the bug")
    assert (tmp_path / "metrics.json").exists()


def test_resolve_eval_llm_deepseek_env(monkeypatch):
    from my_pi_eval.agent import resolve_eval_llm

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake-deepseek-key")
    llm = resolve_eval_llm("deepseek/deepseek-chat")
    assert llm.config.provider == "deepseek"
    assert llm.config.model == "deepseek-chat"
    assert llm.config.api_key == "sk-fake-deepseek-key"
    assert llm.config.base_url == "https://api.deepseek.com"


def test_resolve_eval_llm_missing_key_raises(monkeypatch):
    from my_pi_eval.agent import resolve_eval_llm

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="my-pi-eval/.env"):
        resolve_eval_llm("deepseek/deepseek-chat")
