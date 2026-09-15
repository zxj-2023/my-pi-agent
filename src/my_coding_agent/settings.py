"""Settings: 全局 (~/.my-pi-agent/settings.json) 与项目双层级联配置系统。"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from my_coding_agent.paths import AgentPaths

# 特权字段：仅允许在全局 settings.json 中配置，项目级配置一律忽略
PRIVILEGED_GLOBAL_KEYS: set[str] = {
    "http_proxy",
    "httpProxy",
    "project_trust",
    "projectTrust",
}


class CompactionSettings(BaseModel):
    """上下文压缩管线配置参数。"""

    enabled: bool = True
    reserve_tokens: int = Field(default=16384, alias="reserveTokens")
    keep_recent_tokens: int = Field(default=20000, alias="keepRecentTokens")

    model_config = ConfigDict(populate_by_name=True)


class Settings(BaseModel):
    """统一管理全局偏好与项目覆盖的强类型配置实体。"""

    # ── 默认模型与思考深度 ──
    default_provider: str = Field(default="openai", alias="defaultProvider")
    default_model: str = Field(default="deepseek-flash", alias="defaultModel")
    default_thinking_level: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] = Field(
        default="off", alias="defaultThinkingLevel"
    )
    model_thinking_levels: dict[str, str] = Field(default_factory=dict, alias="modelThinkingLevels")

    # ── UI 表现层 ──
    theme: str = "dark"
    quiet_startup: bool = Field(default=False, alias="quietStartup")
    editor_padding_x: int = Field(default=0, alias="editorPaddingX")
    show_hardware_cursor: bool = Field(default=False, alias="showHardwareCursor")

    # ── 网络与代理 (特权级) ──
    http_proxy: str | None = Field(default=None, alias="httpProxy")

    # ── 会话与压缩管线 ──
    compaction: CompactionSettings = Field(default_factory=CompactionSettings)
    auto_save_session: bool = Field(default=True, alias="autoSaveSession")

    # ── 权限与安全 ──
    default_permission_mode: Literal["review", "yolo", "strict"] = Field(
        default="review", alias="defaultPermissionMode"
    )
    project_trust: Literal["ask", "always", "never"] = Field(default="ask", alias="projectTrust")

    model_config = ConfigDict(populate_by_name=True)


def _deep_merge_dict(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """递归合并字典；数组/列表整体替换。"""
    result = dict(base)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dict(result[k], v)
        else:
            result[k] = v
    return result


def load_settings(paths: AgentPaths | None = None, cwd: Path | str | None = None) -> Settings:
    """加载并级联合并全局与项目级配置。

    优先级：默认内置值 < 全局 settings.json < 项目级 settings.json（受限覆盖）
    """
    active_paths = paths or AgentPaths()
    merged: dict[str, Any] = {}

    # 1. 全局配置
    if active_paths.settings_path.exists():
        try:
            content = active_paths.settings_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                merged = dict(data)
        except Exception:
            pass

    # 2. 项目级受控覆盖
    if cwd:
        proj_settings = active_paths.project_settings_path(Path(cwd))
        if proj_settings.exists():
            try:
                content = proj_settings.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    # 剥离项目级越权特权字段
                    safe_data = {k: v for k, v in data.items() if k not in PRIVILEGED_GLOBAL_KEYS}
                    merged = _deep_merge_dict(merged, safe_data)
            except Exception:
                pass

    try:
        return Settings.model_validate(merged)
    except Exception:
        return Settings()


def save_settings(settings: Settings, target_path: Path) -> None:
    """以 0o600 权限与临时文件原子替换保存配置。"""
    resolved_target = Path(target_path).resolve()
    resolved_target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = resolved_target.with_name(f"{resolved_target.name}.tmp")
    tmp_path.write_text(
        settings.model_dump_json(by_alias=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with contextlib.suppress(Exception):
        tmp_path.chmod(0o600)
    tmp_path.replace(resolved_target)
