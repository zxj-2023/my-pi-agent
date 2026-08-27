"""Unit tests for Claude Code Plugin system (PluginManifest, Plugin, PluginManager)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from my_agent_core.plugins import (
    Plugin,
    PluginAuthor,
    PluginManager,
)


def test_plugin_author_parsing():
    # 字符串形式解析（含 email）
    a1 = PluginAuthor.from_value("Anthropic <support@anthropic.com>")
    assert a1.name == "Anthropic"
    assert a1.email == "support@anthropic.com"
    assert a1.url is None

    # 纯字符串形式
    a2 = PluginAuthor.from_value("OpenHands")
    assert a2.name == "OpenHands"
    assert a2.email is None

    # 字典形式解析
    a3 = PluginAuthor.from_value(
        {
            "name": "OpenHands",
            "email": "dev@openhands.dev",
            "url": "https://openhands.dev",
        }
    )
    assert a3.name == "OpenHands"
    assert a3.email == "dev@openhands.dev"
    assert a3.url == "https://openhands.dev"

    # 非法值兜底
    a4 = PluginAuthor.from_value(12345)
    assert a4.name == "unknown"


def test_plugin_manifest_loading_and_fallback():
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. 包含 .claude-plugin/plugin.json 的标准插件
        p1 = Path(tmpdir) / "plugin-one"
        (p1 / ".claude-plugin").mkdir(parents=True)
        (p1 / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "code-quality",
                    "version": "1.2.0",
                    "description": "Quality tools",
                    "author": "Tester <test@test.com>",
                    "homepage": "https://example.com",
                    "license": "MIT",
                    "keywords": ["lint", "test"],
                }
            ),
            encoding="utf-8",
        )
        plugin1 = Plugin.from_directory(p1)
        assert plugin1.name == "code-quality"
        assert plugin1.manifest.version == "1.2.0"
        assert plugin1.manifest.author is not None
        assert plugin1.manifest.author.email == "test@test.com"
        assert plugin1.manifest.homepage == "https://example.com"
        assert plugin1.manifest.license == "MIT"
        assert plugin1.manifest.keywords == ["lint", "test"]

        # 2. 包含 .plugin/plugin.json 的通用插件
        p2 = Path(tmpdir) / "plugin-two"
        (p2 / ".plugin").mkdir(parents=True)
        (p2 / ".plugin" / "plugin.json").write_text(
            json.dumps({"name": "lint-suite"}),
            encoding="utf-8",
        )
        plugin2 = Plugin.from_directory(p2)
        assert plugin2.name == "lint-suite"
        assert plugin2.manifest.version == "1.0.0"

        # 3. 包含根级 plugin.json 的插件
        p3 = Path(tmpdir) / "plugin-three"
        p3.mkdir(parents=True)
        (p3 / "plugin.json").write_text(
            json.dumps({"name": "root-json-plugin"}),
            encoding="utf-8",
        )
        plugin3 = Plugin.from_directory(p3)
        assert plugin3.name == "root-json-plugin"

        # 4. 根目录直接放 SKILL.md 的单技能插件简写（无 manifest，目录名兜底）
        p4 = Path(tmpdir) / "single-skill-plugin"
        p4.mkdir(parents=True)
        (p4 / "SKILL.md").write_text(
            "---\ndescription: single skill\n---\n\nBody", encoding="utf-8"
        )
        plugin4 = Plugin.from_directory(p4)
        assert plugin4.name == "single-skill-plugin"
        assert plugin4.manifest.version == "1.0.0"
        assert plugin4.skills_dir == p4

        # 5. 损坏的 JSON 语法错误，降级为目录名兜底推断
        p5 = Path(tmpdir) / "broken-json-plugin"
        (p5 / ".claude-plugin").mkdir(parents=True)
        (p5 / ".claude-plugin" / "plugin.json").write_text(
            "{broken json", encoding="utf-8"
        )
        plugin5 = Plugin.from_directory(p5)
        assert plugin5.name == "broken-json-plugin"


def test_plugin_resource_directories():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "bundle"
        (p / ".claude-plugin").mkdir(parents=True)
        (p / ".claude-plugin" / "plugin.json").write_text('{"name": "bundle"}')
        (p / "skills").mkdir()
        (p / "agents").mkdir()
        (p / ".mcp.json").write_text('{"mcpServers": {}}')

        plugin = Plugin.from_directory(p)
        assert plugin.skills_dir == p / "skills"
        assert plugin.agents_dir == p / "agents"
        assert plugin.mcp_config_path == p / ".mcp.json"


def test_plugin_commands_fallback_for_skills():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "legacy-commands-plugin"
        p.mkdir(parents=True)
        (p / "commands").mkdir()

        plugin = Plugin.from_directory(p)
        assert plugin.skills_dir == p / "commands"


def test_plugin_manager_discovery_and_extraction():
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_root = Path(tmpdir) / "plugins"
        p1 = plugins_root / "plugin-a"
        (p1 / ".claude-plugin").mkdir(parents=True)
        (p1 / ".claude-plugin" / "plugin.json").write_text('{"name": "plugin-a"}')
        (p1 / "skills").mkdir()
        (p1 / ".mcp.json").write_text('{"mcpServers": {}}')

        p2 = plugins_root / "plugin-b"
        (p2 / "agents").mkdir(parents=True)

        manager = PluginManager(dirs=[plugins_root])
        assert len(manager.plugins) == 2
        assert "plugin-a" in manager.plugins
        assert "plugin-b" in manager.plugins

        assert manager.get_skill_dirs() == [p1 / "skills"]
        assert manager.get_subagent_dirs() == [p2 / "agents"]
        assert manager.get_mcp_config_paths() == [p1 / ".mcp.json"]

        # 禁用其中一个插件
        manager.plugins["plugin-a"].enabled = False
        assert manager.get_skill_dirs() == []
        assert manager.get_mcp_config_paths() == []
        assert manager.get_subagent_dirs() == [p2 / "agents"]


def test_plugin_manager_direct_plugin_dir_and_disabled():
    with tempfile.TemporaryDirectory() as tmpdir:
        p1 = Path(tmpdir) / "single-plugin"
        (p1 / ".claude-plugin").mkdir(parents=True)
        (p1 / ".claude-plugin" / "plugin.json").write_text('{"name": "single-plugin"}')
        (p1 / "skills").mkdir()

        # 直接指定单个插件目录
        manager_single = PluginManager(dirs=[p1])
        assert len(manager_single.plugins) == 1
        assert "single-plugin" in manager_single.plugins

        # 显式禁用 dirs=[]
        manager_disabled = PluginManager(dirs=[])
        assert len(manager_disabled.plugins) == 0
        assert manager_disabled.get_skill_dirs() == []
