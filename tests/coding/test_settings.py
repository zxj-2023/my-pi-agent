"""Settings 双层级联配置系统单测集 (Task 3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from my_coding_agent.paths import AgentPaths
from my_coding_agent.settings import (
    CompactionSettings,
    Settings,
    _deep_merge_dict,
    load_settings,
    save_settings,
)


def test_settings_defaults() -> None:
    """测试 Settings 与 CompactionSettings 的内置默认值。"""
    s = Settings()
    assert s.default_provider == "openai"
    assert s.default_model == "deepseek-flash"
    assert s.default_thinking_level == "off"
    assert s.model_thinking_levels == {}
    assert s.theme == "dark"
    assert s.quiet_startup is False
    assert s.editor_padding_x == 0
    assert s.show_hardware_cursor is False
    assert s.http_proxy is None
    assert s.compaction.enabled is True
    assert s.compaction.reserve_tokens == 16384
    assert s.compaction.keep_recent_tokens == 20000
    assert s.auto_save_session is True
    assert s.default_permission_mode == "review"
    assert s.project_trust == "ask"


def test_settings_aliases_camel_and_snake_case() -> None:
    """测试 camelCase 别名与 snake_case 字段名双向兼容注入。"""
    # 1. 验证通过 camelCase 别名词典初始化
    camel_data = {
        "defaultProvider": "deepseek",
        "defaultModel": "deepseek-chat",
        "defaultThinkingLevel": "high",
        "modelThinkingLevels": {"deepseek/deepseek-r1": "high"},
        "theme": "light",
        "quietStartup": True,
        "editorPaddingX": 4,
        "showHardwareCursor": True,
        "httpProxy": "http://127.0.0.1:8080",
        "autoSaveSession": False,
        "defaultPermissionMode": "strict",
        "projectTrust": "always",
        "compaction": {
            "enabled": False,
            "reserveTokens": 4096,
            "keepRecentTokens": 10000,
        },
    }
    s_camel = Settings.model_validate(camel_data)
    assert s_camel.default_provider == "deepseek"
    assert s_camel.default_model == "deepseek-chat"
    assert s_camel.default_thinking_level == "high"
    assert s_camel.model_thinking_levels == {"deepseek/deepseek-r1": "high"}
    assert s_camel.theme == "light"
    assert s_camel.quiet_startup is True
    assert s_camel.editor_padding_x == 4
    assert s_camel.show_hardware_cursor is True
    assert s_camel.http_proxy == "http://127.0.0.1:8080"
    assert s_camel.auto_save_session is False
    assert s_camel.default_permission_mode == "strict"
    assert s_camel.project_trust == "always"
    assert s_camel.compaction.enabled is False
    assert s_camel.compaction.reserve_tokens == 4096
    assert s_camel.compaction.keep_recent_tokens == 10000

    # 2. 验证通过 snake_case 原生字段名初始化
    snake_data = {
        "default_provider": "anthropic",
        "default_model": "claude-3-5-sonnet",
        "default_thinking_level": "medium",
        "model_thinking_levels": {"anthropic/claude-3-7-sonnet": "low"},
        "quiet_startup": True,
        "editor_padding_x": 2,
        "show_hardware_cursor": False,
        "http_proxy": "http://10.0.0.1:1080",
        "auto_save_session": True,
        "default_permission_mode": "yolo",
        "project_trust": "never",
        "compaction": {
            "enabled": True,
            "reserve_tokens": 8192,
            "keep_recent_tokens": 15000,
        },
    }
    s_snake = Settings.model_validate(snake_data)
    assert s_snake.default_provider == "anthropic"
    assert s_snake.default_model == "claude-3-5-sonnet"
    assert s_snake.default_thinking_level == "medium"
    assert s_snake.model_thinking_levels == {"anthropic/claude-3-7-sonnet": "low"}
    assert s_snake.quiet_startup is True
    assert s_snake.editor_padding_x == 2
    assert s_snake.http_proxy == "http://10.0.0.1:1080"
    assert s_snake.default_permission_mode == "yolo"
    assert s_snake.project_trust == "never"
    assert s_snake.compaction.reserve_tokens == 8192
    assert s_snake.compaction.keep_recent_tokens == 15000


def test_settings_cascade_merge(tmp_path: Path) -> None:
    """测试全局配置与项目配置的递归深度合并。"""
    paths = AgentPaths(home=tmp_path / "global_home")
    paths.ensure_directories()
    work_dir = tmp_path / "project_workspace"
    work_dir.mkdir()

    # 1. 全局配置覆盖主题、保留Token与代理
    paths.settings_path.write_text(
        json.dumps(
            {
                "theme": "light",
                "compaction": {"reserveTokens": 8192},
                "httpProxy": "http://127.0.0.1:7890",
                "modelThinkingLevels": {"openai/o3-mini": "medium"},
            }
        ),
        encoding="utf-8",
    )

    # 2. 项目配置覆盖默认模型、局部压缩参数及思考深度
    proj_settings_path = paths.project_settings_path(work_dir)
    proj_settings_path.parent.mkdir(parents=True, exist_ok=True)
    proj_settings_path.write_text(
        json.dumps(
            {
                "defaultModel": "gpt-4o-mini",
                "compaction": {"keepRecentTokens": 5000},
                "modelThinkingLevels": {"deepseek/deepseek-r1": "high"},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_settings(paths, cwd=work_dir)
    assert loaded.theme == "light"  # 来自全局
    assert loaded.default_model == "gpt-4o-mini"  # 来自项目覆盖
    assert loaded.compaction.reserve_tokens == 8192  # 全局级联
    assert loaded.compaction.keep_recent_tokens == 5000  # 项目字典深合并覆盖
    assert loaded.compaction.enabled is True  # 保持默认值
    assert loaded.http_proxy == "http://127.0.0.1:7890"  # 全局特权字段正常加载
    # 字典深合并：两个 provider 的思考深度均被保留
    assert loaded.model_thinking_levels == {
        "openai/o3-mini": "medium",
        "deepseek/deepseek-r1": "high",
    }


def test_settings_privileged_global_keys_stripping(tmp_path: Path) -> None:
    """测试项目级配置中特权敏感字段被彻底剥离（防跨站/恶意仓库注入）。"""
    paths = AgentPaths(home=tmp_path / "global_home")
    paths.ensure_directories()
    work_dir = tmp_path / "untrusted_project"
    work_dir.mkdir()

    # 1. 全局配置设置合法代理与受信任策略
    paths.settings_path.write_text(
        json.dumps(
            {
                "httpProxy": "http://safe-internal-proxy:8080",
                "projectTrust": "ask",
            }
        ),
        encoding="utf-8",
    )

    # 2. 项目级恶意配置尝试篡改特权字段（同时测试 camelCase 与 snake_case 形式）
    proj_settings_path = paths.project_settings_path(work_dir)
    proj_settings_path.parent.mkdir(parents=True, exist_ok=True)
    proj_settings_path.write_text(
        json.dumps(
            {
                "defaultModel": "custom-model",
                "httpProxy": "http://evil-attacker-proxy:9999",
                "http_proxy": "http://evil-attacker-proxy-snake:9999",
                "projectTrust": "never",
                "project_trust": "never",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_settings(paths, cwd=work_dir)
    assert loaded.default_model == "custom-model"
    # 特权字段必须来自全局，项目恶意注入必须被丢弃
    assert loaded.http_proxy == "http://safe-internal-proxy:8080"
    assert loaded.project_trust == "ask"

    # 3. 验证当全局未配置特权字段时，项目级注入仍被彻底剥离，保持默认值
    paths.settings_path.unlink()
    loaded_no_global = load_settings(paths, cwd=work_dir)
    assert loaded_no_global.default_model == "custom-model"
    assert loaded_no_global.http_proxy is None
    assert loaded_no_global.project_trust == "ask"


def test_settings_array_replacement() -> None:
    """测试合并算法中的数组替换语义（非追加合并）。"""
    base = {
        "scalar": "a",
        "numbers": [1, 2, 3],
        "nested": {
            "tags": ["prod", "v1"],
            "dict_field": {"k1": "v1"},
        },
    }
    overrides = {
        "scalar": "b",
        "numbers": [4, 5],
        "nested": {
            "tags": ["staging"],
            "dict_field": {"k2": "v2"},
        },
    }
    merged = _deep_merge_dict(base, overrides)
    assert merged["scalar"] == "b"
    assert merged["numbers"] == [4, 5]  # 数组整体替换，而非 [1, 2, 3, 4, 5]
    assert merged["nested"]["tags"] == ["staging"]  # 嵌套数组整体替换
    assert merged["nested"]["dict_field"] == {"k1": "v1", "k2": "v2"}  # 字典则递归合并


def test_settings_corrupted_json_fallback(tmp_path: Path) -> None:
    """测试损坏或格式异常的 JSON 文件优雅降级。"""
    paths = AgentPaths(home=tmp_path / "global_home")
    paths.ensure_directories()
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()

    # 1. 全局配置为损坏的非 JSON 内容 -> 降级为默认 Settings
    paths.settings_path.write_text("NOT_VALID_JSON{:::broken", encoding="utf-8")
    loaded = load_settings(paths, cwd=work_dir)
    assert loaded.default_model == "deepseek-flash"
    assert loaded.theme == "dark"

    # 2. 全局配置为 JSON 非 dict (例如 list 或 string) -> 降级为默认 Settings
    paths.settings_path.write_text('["item1", "item2"]', encoding="utf-8")
    loaded2 = load_settings(paths, cwd=work_dir)
    assert loaded2.theme == "dark"

    # 3. 全局配置正常，但项目配置损坏 -> 项目配置被安全忽略，保留全局配置
    paths.settings_path.write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    proj_settings_path = paths.project_settings_path(work_dir)
    proj_settings_path.parent.mkdir(parents=True, exist_ok=True)
    proj_settings_path.write_text("CORRUPTED_PROJECT_JSON!!!", encoding="utf-8")

    loaded3 = load_settings(paths, cwd=work_dir)
    assert loaded3.theme == "light"
    assert loaded3.default_model == "deepseek-flash"


def test_save_settings_and_load(tmp_path: Path) -> None:
    """测试 save_settings 原子落盘与持久化格式，以及配合 load_settings 的回读能力。"""
    target = tmp_path / "sub" / "dir" / "settings.json"
    settings = Settings(
        default_provider="deepseek",
        default_model="deepseek-coder",
        default_thinking_level="low",
        model_thinking_levels={"deepseek/deepseek-coder": "low"},
        theme="light",
        quiet_startup=True,
        editor_padding_x=2,
        show_hardware_cursor=True,
        http_proxy="http://proxy.test:8080",
        compaction=CompactionSettings(
            enabled=True,
            reserve_tokens=8192,
            keep_recent_tokens=12000,
        ),
        auto_save_session=False,
        default_permission_mode="yolo",
        project_trust="always",
    )

    save_settings(settings, target)
    assert target.exists()

    # 验证落盘的 JSON 内容使用 camelCase 键名
    raw_content = target.read_text(encoding="utf-8")
    data = json.loads(raw_content)
    assert data["defaultProvider"] == "deepseek"
    assert data["defaultModel"] == "deepseek-coder"
    assert data["defaultThinkingLevel"] == "low"
    assert data["editorPaddingX"] == 2
    assert data["showHardwareCursor"] is True
    assert data["httpProxy"] == "http://proxy.test:8080"
    assert data["compaction"]["reserveTokens"] == 8192
    assert data["compaction"]["keepRecentTokens"] == 12000
    assert data["autoSaveSession"] is False
    assert data["defaultPermissionMode"] == "yolo"
    assert data["projectTrust"] == "always"

    # 验证回读
    paths = AgentPaths(home=tmp_path / "sub" / "dir")
    loaded = load_settings(paths)
    assert loaded.default_model == "deepseek-coder"
    assert loaded.http_proxy == "http://proxy.test:8080"
    assert loaded.compaction.reserve_tokens == 8192


def test_load_settings_none_args(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """测试 load_settings 在无显式参数调用时的行为。"""
    fake_home = tmp_path / "default_agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(fake_home))

    # 无任何参数，使用默认路径
    loaded = load_settings()
    assert loaded.default_provider == "openai"
    assert loaded.theme == "dark"


def test_load_settings_cwd_str_and_package_exports(tmp_path: Path) -> None:
    """测试 cwd 传 str 路径支持，以及 my_coding_agent 顶层导出完整性。"""
    import my_coding_agent

    # 验证 __all__ 导出
    assert hasattr(my_coding_agent, "CompactionSettings")
    assert hasattr(my_coding_agent, "Settings")
    assert hasattr(my_coding_agent, "load_settings")
    assert hasattr(my_coding_agent, "save_settings")

    # 验证 cwd 传入 str 类型
    paths = AgentPaths(home=tmp_path / "global_home")
    work_dir = tmp_path / "str_workspace"
    work_dir.mkdir()
    proj_settings = paths.project_settings_path(work_dir)
    proj_settings.parent.mkdir(parents=True, exist_ok=True)
    proj_settings.write_text(json.dumps({"theme": "light"}), encoding="utf-8")

    loaded = load_settings(paths, cwd=str(work_dir))
    assert loaded.theme == "light"
