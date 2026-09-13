from pathlib import Path
import subprocess
from unittest.mock import patch
from rich.console import Console

from my_coding_agent import CodingAgent
from my_agent_llm.models import Response
from my_agent_tui.components import FooterComponent
from my_agent_tui.components.footer import (
    format_cwd_for_footer,
    format_tokens,
    resolve_git_branch,
)


class FakeLLM:
    def __init__(self, model: str = "fake"):
        self.model = model

    async def achat(self, *a, **kw):
        return Response(content="ok", model=self.model)

    async def achat_stream(self, *a, **kw):
        pass


def test_format_tokens():
    assert format_tokens(0) == "0"
    assert format_tokens(500) == "500"
    assert format_tokens(1000) == "1.0k"
    assert format_tokens(14200) == "14.2k"
    assert format_tokens(1000000) == "1.0M"
    assert format_tokens(2500000) == "2.5M"
    assert format_tokens("invalid") == "0"


def test_format_cwd_for_footer():
    home = Path("/home/alice")
    cwd = Path("/home/alice/projects/my-pi")
    res = format_cwd_for_footer(cwd, home=home)
    assert res.startswith("~")
    assert "projects/my-pi" in res

    # Exactly home dir
    res_home = format_cwd_for_footer(home, home=home)
    assert res_home == "~"


def test_format_cwd_for_footer_outside_home():
    home = Path("/home/alice")
    cwd = Path("/var/log/my-app")
    res = format_cwd_for_footer(cwd, home=home)
    assert not res.startswith("~")
    assert "var/log/my-app" in res


def test_resolve_git_branch_success(tmp_path: Path):
    # Initialize a temporary git repository
    try:
        subprocess.run(
            ["git", "init", "-b", "feature-test"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        branch = resolve_git_branch(tmp_path)
        assert branch == "feature-test"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return


def test_resolve_git_branch_not_git(tmp_path: Path):
    non_git = tmp_path / "empty_dir"
    non_git.mkdir()
    branch = resolve_git_branch(non_git)
    assert branch is None


def test_resolve_git_branch_handles_exception():
    with patch("subprocess.run", side_effect=OSError("Command failed")):
        assert resolve_git_branch(Path("/invalid/path")) is None


def test_footer_render_output(tmp_path: Path):
    console = Console(record=True)
    footer = FooterComponent(console=console)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    footer.render(agent)
    out = console.export_text()
    assert "📁" in out
    assert "🤖" in out
    assert "fake" in out
    assert "Tokens:" in out


def test_footer_render_with_elapsed(tmp_path: Path):
    console = Console(record=True)
    footer = FooterComponent(console=console)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    footer.render(agent, elapsed=2.345)
    out = console.export_text()
    assert "⏱️" in out
    assert "2.3s" in out


def test_footer_render_with_session_entries(tmp_path: Path):
    console = Console(record=True)
    footer = FooterComponent(console=console)
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    agent.session.add_message("user", "hello", usage={"total_tokens": 350})
    agent.session.add_message("assistant", "world", usage={"total_tokens": 650})

    footer.render(agent)
    out = console.export_text()
    assert "1.0k" in out
