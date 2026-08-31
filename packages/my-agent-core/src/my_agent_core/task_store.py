"""TaskItem 数据模型与 TaskStore DAG 依赖状态机。"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["pending", "in_progress", "completed", "deleted"]


@dataclass
class TaskItem:
    """单个结构化工单项（对标 OpenHands TaskItem 与 trpc-agent TaskRecord）。"""

    id: str
    subject: str
    description: str = ""
    status: TaskStatus = "pending"
    owner: str | None = None
    active_form: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskStore:
    """基于 DAG 依赖图与原子持久化的项目任务仓库。"""

    def __init__(
        self, workspace: Path | str, enforce_single_in_progress: bool = True
    ) -> None:
        self.workspace = Path(workspace)
        self.store_dir = self.workspace / ".my_agent_core"
        self.file_path = self.store_dir / "tasks.json"
        self.enforce_single_in_progress = enforce_single_in_progress
        self.tasks: dict[str, TaskItem] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self.file_path.exists():
            return
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            self._next_id = data.get("next_id", 1)
            for item in data.get("tasks", []):
                task = TaskItem(**item)
                self.tasks[task.id] = task
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            # 损坏文件或空文件容错，保留初始空状态
            pass

    def _save_to_disk(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "next_id": self._next_id,
            "tasks": [asdict(t) for t in self.tasks.values()],
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        fd, tmp_path = tempfile.mkstemp(
            dir=self.store_dir, prefix="tasks_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.file_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def _depends_on(self, task_id: str, target_id: str) -> bool:
        """检查 task_id 是否传递性依赖于 target_id。"""
        visited = set()
        queue = [task_id]
        while queue:
            curr = queue.pop(0)
            if curr == target_id:
                return True
            if curr in visited:
                continue
            visited.add(curr)
            if curr in self.tasks:
                queue.extend(self.tasks[curr].blocked_by)
        return False

    async def create(
        self,
        subject: str,
        description: str = "",
        active_form: str | None = None,
        metadata: dict | None = None,
    ) -> TaskItem:
        """创建新任务，自动分配递增 ID。"""
        async with self._lock:
            sub = subject.strip()
            if not sub:
                raise ValueError("Task subject cannot be empty")
            task_id = f"task_{self._next_id}"
            self._next_id += 1
            task = TaskItem(
                id=task_id,
                subject=sub,
                description=description,
                status="pending",
                active_form=active_form,
                metadata=metadata or {},
            )
            self.tasks[task_id] = task
            self._save_to_disk()
            return task

    async def update(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        owner: str | None = None,
        metadata: dict | None = None,
        add_blocked_by: list[str] | None = None,
        remove_blocked_by: list[str] | None = None,
    ) -> tuple[TaskItem, list[str]]:
        """局部增量更新任务字段与 DAG 依赖，并计算自动解锁列表。"""
        async with self._lock:
            if task_id not in self.tasks:
                raise KeyError(f"Task '{task_id}' not found")
            task = self.tasks[task_id]

            if status == "in_progress" and self.enforce_single_in_progress:
                for other_id, other in self.tasks.items():
                    if other_id != task_id and other.status == "in_progress":
                        raise ValueError(f"Task '{other_id}' is already in progress")

            if add_blocked_by:
                for dep in add_blocked_by:
                    if dep == task_id:
                        raise ValueError("Task cannot depend on itself")
                    if dep not in self.tasks:
                        raise KeyError(f"Dependency task '{dep}' not found")
                    if self._depends_on(dep, task_id):
                        raise ValueError(
                            f"Cycle detected: {task_id} -> {dep} -> {task_id}"
                        )
                    if dep not in task.blocked_by:
                        task.blocked_by.append(dep)

            if remove_blocked_by:
                task.blocked_by = [
                    d for d in task.blocked_by if d not in remove_blocked_by
                ]

            if status is not None:
                task.status = status
            if subject is not None:
                task.subject = subject.strip()
            if description is not None:
                task.description = description
            if active_form is not None:
                task.active_form = active_form
            if owner is not None:
                task.owner = owner
            if metadata is not None:
                task.metadata.update(metadata)

            unblocked: list[str] = []
            if status == "completed":
                for other_id, other in self.tasks.items():
                    if other.status == "pending" and task_id in other.blocked_by:
                        other.blocked_by.remove(task_id)
                        if len(other.blocked_by) == 0:
                            unblocked.append(other_id)

            self._save_to_disk()
            return task, unblocked

    def get(self, task_id: str) -> TaskItem:
        """获取单个任务详情。"""
        if task_id not in self.tasks:
            raise KeyError(f"Task '{task_id}' not found")
        return self.tasks[task_id]

    def list(self, include_deleted: bool = False) -> list[TaskItem]:
        """列出所有活跃任务。"""
        return [
            t for t in self.tasks.values() if include_deleted or t.status != "deleted"
        ]

    async def batch_write(self, todos: list[dict[str, Any]]) -> list[TaskItem]:
        """批量/便签覆盖写入。"""
        async with self._lock:
            for item in todos:
                t_id = item.get("id")
                if t_id and t_id in self.tasks:
                    t = self.tasks[t_id]
                    if "subject" in item:
                        t.subject = str(item["subject"]).strip()
                    if "status" in item and item["status"] in (
                        "pending",
                        "in_progress",
                        "completed",
                        "deleted",
                    ):
                        t.status = item["status"]
                else:
                    new_id = f"task_{self._next_id}"
                    self._next_id += 1
                    self.tasks[new_id] = TaskItem(
                        id=new_id,
                        subject=str(item.get("subject", "Untitled")).strip(),
                        description=str(item.get("description", "")),
                        status=item.get("status", "pending"),
                    )
            self._save_to_disk()
            return self.list()

    def render_board(self) -> str:
        """渲染紧凑 Markdown 看板。"""
        tasks = self.list()
        if not tasks:
            return "(No active tasks)"
        lines: list[str] = []
        for t in tasks:
            if t.status == "completed":
                icon = "[x]"
            elif t.status == "in_progress":
                icon = "[>]"
            else:
                icon = "[ ]"

            status_desc = f"{t.status}"
            if t.active_form and t.status == "in_progress":
                status_desc += f" - {t.active_form}"
            if t.blocked_by:
                status_desc += f", blocked by: {t.blocked_by}"

            lines.append(f"{icon} {t.id}: {t.subject} ({status_desc})")
        return "\n".join(lines)
