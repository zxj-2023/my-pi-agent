"""Tests for installation scripts (install.sh and install.ps1)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_install_sh_content_and_structure():
    sh_file = REPO_ROOT / "install.sh"
    assert sh_file.exists()
    content = sh_file.read_text(encoding="utf-8")

    assert "#!/usr/bin/env sh" in content
    assert ".my-pi-agent" in content
    assert "my-pi-agent" in content
    assert "export PATH=" in content
    assert "node" in content


def test_install_ps1_content_and_structure():
    ps1_file = REPO_ROOT / "install.ps1"
    assert ps1_file.exists()
    content = ps1_file.read_text(encoding="utf-8")

    assert ".my-pi-agent" in content
    assert "my-pi-agent.cmd" in content
    assert "[Environment]::SetEnvironmentVariable" in content
    assert "Path" in content
