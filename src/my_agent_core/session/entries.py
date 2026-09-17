"""Session entry definitions for the modular session subsystem.

Provides 9 polymorphic discriminated entry types backed by Pydantic v2,
supporting camelCase and snake_case aliasing and strict extra field rejection.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from my_agent_llm.models import Message


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
    name: str | None = None
    created_at: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_title_name(self) -> SessionInfoEntry:
        if self.name and not self.title:
            self.title = self.name
        elif self.title and not self.name:
            self.name = self.title
        return self


class MessageEntry(BaseSessionEntry):
    """包装 Agent 对话消息（User / Assistant / Tool 交互）。"""

    type: Literal["message"] = "message"
    message: Message

    @property
    def role(self) -> str:
        return self.message.role

    @property
    def content(self) -> str:
        return self.message.content

    @property
    def metadata(self) -> dict[str, Any]:
        return self.message.metadata or {}


class ModelChangeEntry(BaseSessionEntry):
    """记录运行时大模型变更（兼容 Pi 原厂 modelId 字段）。"""

    type: Literal["model_change", "modelChange"] = "model_change"
    model: str | None = None
    model_id: str | None = Field(default=None, alias="modelId")
    provider: str | None = None

    @model_validator(mode="after")
    def _sync_model_fields(self) -> ModelChangeEntry:
        if self.model_id and not self.model:
            self.model = self.model_id
        elif self.model and not self.model_id:
            self.model_id = self.model
        return self


class ThinkingLevelChangeEntry(BaseSessionEntry):
    """记录推理思考等级调整。"""

    type: Literal["thinking_level_change", "thinkingLevelChange"] = "thinking_level_change"
    thinking_level: str


class CompactionEntry(BaseSessionEntry):
    """记录上下文压缩覆盖的条目 ID 清单与折叠摘要（兼容 Pi 原厂 firstKeptEntryId 与 tokensBefore）。"""

    type: Literal["compaction"] = "compaction"
    summary: str
    first_kept_entry_id: str | None = Field(default=None, alias="firstKeptEntryId")
    tokens_before: int | None = Field(default=None, alias="tokensBefore")
    replaces_entry_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def role(self) -> str:
        return "system"

    @property
    def content(self) -> str:
        return self.summary


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
    namespace: str | None = None
    custom_type: str | None = Field(default=None, alias="customType")
    data: dict[str, Any] = Field(default_factory=dict)


class CustomMessageEntry(BaseSessionEntry):
    """扩展上下文注入消息条目（对标 Pi 原厂 CustomMessageEntry）。"""

    type: Literal["custom_message", "customMessage"] = "custom_message"
    custom_type: str = Field(default="custom", alias="customType")
    content: str | list[Any] = ""
    display: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class SessionHeaderEntry(BaseSessionEntry):
    """Pi 原厂会话头节点。"""

    type: Literal["session"] = "session"
    version: int = 3
    cwd: str = ""
    parent_session: str | None = Field(default=None, alias="parentSession")


SessionEntry = Annotated[
    SessionInfoEntry
    | SessionHeaderEntry
    | MessageEntry
    | ModelChangeEntry
    | ThinkingLevelChangeEntry
    | CompactionEntry
    | BranchSummaryEntry
    | LabelEntry
    | LeafEntry
    | CustomEntry
    | CustomMessageEntry,
    Field(discriminator="type"),
]

__all__ = [
    "BaseSessionEntry",
    "SessionInfoEntry",
    "SessionHeaderEntry",
    "MessageEntry",
    "ModelChangeEntry",
    "ThinkingLevelChangeEntry",
    "CompactionEntry",
    "BranchSummaryEntry",
    "LabelEntry",
    "LeafEntry",
    "CustomEntry",
    "CustomMessageEntry",
    "SessionEntry",
]
