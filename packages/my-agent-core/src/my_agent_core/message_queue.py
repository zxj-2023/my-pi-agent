"""动态干预消息队列 —— 驱动 Pi 风格的 Steer 转向与 Follow-up 追问。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class MessageType(str, Enum):
    """排队干预消息类型。"""

    STEERING = "steering"  # 内层循环即时转向（安全点打断）
    FOLLOWUP = "followup"  # 外层循环排队追问（任务完成后驱动）


@dataclass
class QueuedMessage:
    """队列中的一条干预消息。"""

    content: str
    type: MessageType
    created_at: float = field(default_factory=time.time)


class MessageQueue:
    """管理运行期动态干预消息的队列。"""

    def __init__(
        self,
        steering_mode: Literal["one-at-a-time", "all"] = "one-at-a-time",
        followup_mode: Literal["one-at-a-time", "all"] = "one-at-a-time",
    ) -> None:
        self.queue: list[QueuedMessage] = []
        self.steering_mode = steering_mode
        self.followup_mode = followup_mode

    def add_steering(self, message: str) -> None:
        """追加一条 Steering 转向消息。"""
        self.queue.append(QueuedMessage(content=message, type=MessageType.STEERING))

    def add_followup(self, message: str) -> None:
        """追加一条 Follow-up 追问消息。"""
        self.queue.append(QueuedMessage(content=message, type=MessageType.FOLLOWUP))

    def get_steering_messages(self) -> list[QueuedMessage]:
        """获取并弹出待消费的 steering 消息。"""
        steering = [m for m in self.queue if m.type == MessageType.STEERING]
        if not steering:
            return []

        if self.steering_mode == "one-at-a-time":
            first = steering[0]
            self.queue.remove(first)
            return [first]

        self.queue = [m for m in self.queue if m.type != MessageType.STEERING]
        return steering

    def get_followup_messages(self) -> list[QueuedMessage]:
        """获取并弹出待消费的 followup 消息。"""
        followup = [m for m in self.queue if m.type == MessageType.FOLLOWUP]
        if not followup:
            return []

        if self.followup_mode == "one-at-a-time":
            first = followup[0]
            self.queue.remove(first)
            return [first]

        self.queue = [m for m in self.queue if m.type != MessageType.FOLLOWUP]
        return followup

    def has_steering(self) -> bool:
        """检查是否存在未决的 steering 消息。"""
        return any(m.type == MessageType.STEERING for m in self.queue)

    def has_followup(self) -> bool:
        """检查是否存在未决的 followup 消息。"""
        return any(m.type == MessageType.FOLLOWUP for m in self.queue)

    def peek(self) -> QueuedMessage | None:
        """查看队首消息但不弹出。"""
        return self.queue[0] if self.queue else None

    def clear(self) -> list[QueuedMessage]:
        """清空队列并返回被清除的消息列表。"""
        cleared = list(self.queue)
        self.queue.clear()
        return cleared

    def get_status(self) -> str:
        """获取当前队列的可读状态。"""
        if not self.queue:
            return "Queue empty"
        steering_count = sum(1 for m in self.queue if m.type == MessageType.STEERING)
        followup_count = sum(1 for m in self.queue if m.type == MessageType.FOLLOWUP)
        parts = []
        if steering_count:
            parts.append(f"{steering_count} steering")
        if followup_count:
            parts.append(f"{followup_count} follow-up")
        return f"Queued: {', '.join(parts)}"

    def __len__(self) -> int:
        return len(self.queue)

    def __bool__(self) -> bool:
        return len(self.queue) > 0
