"""Session entry definitions for the modular session subsystem.

Provides 9 polymorphic discriminated entry types backed by Pydantic v2,
supporting camelCase and snake_case aliasing and strict extra field rejection.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal
from uuid import uuid4

from my_agent_llm.models import Message
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class BaseSessionEntry(BaseModel):
    """会话树节点基类。

    提供自增 ID、父节点指针、浮点时间戳，并开启 camelCase 互转与未知字段禁止。
    """

    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
    )

    id: str = Field(default_factory=lambda: uuid4().hex)
    parent_id: str | None = None
    timestamp: float = Field(default_factory=time.time)


class SessionInfoEntry(BaseSessionEntry):
    """记录会话元数据（工作目录、标题、创建时间），通常作为流首项。"""

    type: Literal["session_info", "sessionInfo"] = "session_info"
    cwd: str | None = None
    title: str | None = None
    created_at: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageEntry(BaseSessionEntry):
    """包装 Agent 对话消息（User / Assistant / Tool 交互）。"""

    type: Literal["message"] = "message"
    message: Message


class ModelChangeEntry(BaseSessionEntry):
    """记录运行时大模型变更。"""

    type: Literal["model_change", "modelChange"] = "model_change"
    model: str
    provider: str | None = None


class ThinkingLevelChangeEntry(BaseSessionEntry):
    """记录推理思考等级调整。"""

    type: Literal["thinking_level_change", "thinkingLevelChange"] = (
        "thinking_level_change"
    )
    thinking_level: str


class CompactionEntry(BaseSessionEntry):
    """记录上下文压缩覆盖的条目 ID 清单与折叠摘要。"""

    type: Literal["compaction"] = "compaction"
    summary: str
    replaces_entry_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BranchSummaryEntry(BaseSessionEntry):
    """记录分支折叠探索摘要。"""

    type: Literal["branch_summary", "branchSummary"] = "branch_summary"
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class LabelEntry(BaseSessionEntry):
    """用户书签/检查点。"""

    type: Literal["label"] = "label"
    label: str
    target_id: str | None = None


class LeafEntry(BaseSessionEntry):
    """指向当前分支活动叶节点的指针（分支切换仅需追加一条 LeafEntry，零文件重写）。"""

    type: Literal["leaf"] = "leaf"
    leaf_id: str


class CustomEntry(BaseSessionEntry):
    """扩展与遥测隔离槽位。"""

    type: Literal["custom"] = "custom"
    namespace: str
    data: dict[str, Any] = Field(default_factory=dict)


SessionEntry = Annotated[
    SessionInfoEntry
    | MessageEntry
    | ModelChangeEntry
    | ThinkingLevelChangeEntry
    | CompactionEntry
    | BranchSummaryEntry
    | LabelEntry
    | LeafEntry
    | CustomEntry,
    Field(discriminator="type"),
]

__all__ = [
    "BaseSessionEntry",
    "SessionInfoEntry",
    "MessageEntry",
    "ModelChangeEntry",
    "ThinkingLevelChangeEntry",
    "CompactionEntry",
    "BranchSummaryEntry",
    "LabelEntry",
    "LeafEntry",
    "CustomEntry",
    "SessionEntry",
]
