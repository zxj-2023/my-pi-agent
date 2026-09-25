"""Tests for scripts/build_dist.py packaging tool."""

from __future__ import annotations

from pathlib import Path

from scripts.build_dist import (
    generate_launcher_scripts,
    get_version_from_pyproject,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_get_version_from_pyproject():
    version = get_version_from_pyproject(REPO_ROOT / "pyproject.toml")
    assert version == "0.1.1"


def test_generate_launcher_scripts(tmp_path: Path):
    cmd_file, sh_file = generate_launcher_scripts(tmp_path)
    assert cmd_file.exists()
    assert sh_file.exists()

    cmd_content = cmd_file.read_text(encoding="utf-8")
    assert "my-agent.js" in cmd_content
    assert "%*" in cmd_content

    sh_content = sh_file.read_text(encoding="utf-8")
    assert "my-agent.js" in sh_content
    assert '"$@"' in sh_content
