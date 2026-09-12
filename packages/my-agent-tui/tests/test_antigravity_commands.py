import io
from pathlib import Path
from unittest.mock import patch
import pytest
from rich.console import Console

from my_coding_agent import CodingAgent
from my_agent_tui.cli import SLASH_COMMANDS
from my_agent_tui.commands import CommandDispatcher
from my_agent_llm.auth.antigravity import AntigravityCredentials
from my_agent_llm.auth.quota import QuotaBucket
from my_agent_llm.config import Config
from my_agent_llm.models import Response


class FakeLLM:
    def __init__(self, model: str = "fake"):
        self.config = Config(provider="openai", model=model, api_key="fake")

    async def achat(self, *a, **kw):
        return Response(content="ok", model="fake")

    async def achat_stream(self, *a, **kw):
        return
        yield


@pytest.mark.anyio
async def test_cmd_quota(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    mock_buckets = [
        QuotaBucket(
            bucket_id="gemini-weekly",
            display_name="Weekly Limit",
            remaining_fraction=0.85,
            reset_time="2026-09-13T00:00:00Z",
        )
    ]
    with patch(
        "my_agent_llm.auth.quota.retrieve_user_quota_summary",
        return_value=mock_buckets,
    ):
        handled = await dispatcher.dispatch("/quota", console)
        assert handled is True
        output = buf.getvalue()
        assert "85%" in output
        assert "Weekly Limit" in output


@pytest.mark.anyio
async def test_cmd_quota_empty(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    with patch(
        "my_agent_llm.auth.quota.retrieve_user_quota_summary",
        return_value=[],
    ):
        handled = await dispatcher.dispatch("/quota", console)
        assert handled is True
        output = buf.getvalue()
        assert "未能获取到配额信息" in output


@pytest.mark.anyio
async def test_cmd_model_switch(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/model gemini-3.8-flash", console)
    assert handled is True
    assert "gemini-3.8-flash" in buf.getvalue()
    assert agent.agent.llm.config.model == "gemini-3.8-flash"


@pytest.mark.anyio
async def test_cmd_model_display_current(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(model="gpt-4o"), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/model", console)
    assert handled is True
    output = buf.getvalue()
    assert "gpt-4o" in output
    assert "当前模型" in output


@pytest.mark.anyio
async def test_cmd_login_no_args(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/login", console)
    assert handled is True
    assert "用法: /login" in buf.getvalue()


@pytest.mark.anyio
async def test_cmd_login_unsupported_provider(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/login unsupported_provider", console)
    assert handled is True
    assert "暂不支持" in buf.getvalue()


@pytest.mark.anyio
async def test_cmd_login_antigravity_success(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    mock_creds = AntigravityCredentials(
        access_token="fake-token",
        project_id="test-project",
        email="test@example.com",
        auth_file_path=Path("/home/user/.pi/agent/auth.json"),
    )

    with (
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.resolve_credentials_raw",
            return_value=mock_creds,
        ),
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.is_expired",
            return_value=False,
        ),
    ):
        handled = await dispatcher.dispatch("/login antigravity", console)
        assert handled is True
        output = buf.getvalue()
        assert "成功连接本地 Antigravity 凭据" in output
        assert "test-project" in output
        assert "test@example.com" in output


@pytest.mark.anyio
async def test_cmd_login_antigravity_not_found(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    with patch(
        "my_agent_llm.auth.antigravity.AntigravityAuthResolver.resolve_credentials_raw",
        return_value=None,
    ):
        handled = await dispatcher.dispatch("/login antigravity", console)
        assert handled is True
        assert "未在本地检测到 Antigravity 鉴权凭据" in buf.getvalue()


@pytest.mark.anyio
async def test_cmd_login_antigravity_expired_and_refreshed(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    mock_creds = AntigravityCredentials(
        access_token="old-token",
        refresh_token="ref-token",
        project_id="test-project",
    )
    refreshed_creds = AntigravityCredentials(
        access_token="new-token",
        refresh_token="ref-token",
        project_id="test-project",
    )

    with (
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.resolve_credentials_raw",
            return_value=mock_creds,
        ),
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.is_expired",
            return_value=True,
        ),
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.refresh",
            return_value=refreshed_creds,
        ),
    ):
        handled = await dispatcher.dispatch("/login antigravity", console)
        assert handled is True
        output = buf.getvalue()
        assert "已成功刷新" in output
        assert "成功连接本地 Antigravity 凭据" in output


@pytest.mark.anyio
async def test_cmd_quota_exception(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    with patch(
        "my_agent_llm.auth.quota.retrieve_user_quota_summary",
        side_effect=RuntimeError("Network failure"),
    ):
        handled = await dispatcher.dispatch("/quota", console)
        assert handled is True
        output = buf.getvalue()
        assert "查询配额失败: Network failure" in output


@pytest.mark.anyio
async def test_cmd_login_expired_no_refresh_token(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    mock_creds = AntigravityCredentials(
        access_token="old-token",
        refresh_token=None,
        project_id="test-project",
    )

    with (
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.resolve_credentials_raw",
            return_value=mock_creds,
        ),
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.is_expired",
            return_value=True,
        ),
    ):
        handled = await dispatcher.dispatch("/login antigravity", console)
        assert handled is True
        output = buf.getvalue()
        assert "已过期且无可用的 refresh_token" in output


@pytest.mark.anyio
async def test_cmd_login_refresh_failure(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    mock_creds = AntigravityCredentials(
        access_token="old-token",
        refresh_token="ref-token",
        project_id="test-project",
    )

    with (
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.resolve_credentials_raw",
            return_value=mock_creds,
        ),
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.is_expired",
            return_value=True,
        ),
        patch(
            "my_agent_llm.auth.antigravity.AntigravityAuthResolver.refresh",
            side_effect=RuntimeError("Refresh failed"),
        ),
    ):
        handled = await dispatcher.dispatch("/login antigravity", console)
        assert handled is True
        output = buf.getvalue()
        assert "刷新 Antigravity 凭据失败: Refresh failed" in output


@pytest.mark.anyio
async def test_help_contains_new_commands(tmp_path: Path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    dispatcher = CommandDispatcher(agent)

    handled = await dispatcher.dispatch("/help", console)
    assert handled is True
    output = buf.getvalue()
    assert "/quota" in output
    assert "/login" in output
    assert "/model" in output


def test_slash_commands_list():
    assert "/quota" in SLASH_COMMANDS
    assert "/model" in SLASH_COMMANDS
    assert "/login" in SLASH_COMMANDS

