"""统一待办任务工具：基于 TaskStore 的单一标准 todo 工具与 discrete 工具族。"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal

from my_agent_core.tools.core import Tool, ToolResult, tool

if TYPE_CHECKING:
    from my_agent_core.task_store import (  # pyright: ignore[reportMissingImports]
        TaskStore,
    )


TODO_GUIDELINES = """\
Manage a task list for tracking multi-step progress.
Actions:
- create: add a new task with subject (and optional description, active_form)
- update: change task status, fields, or add/remove dependencies
- list: review all active tasks and current board
- get: get full details of a specific task by task_id
- clear: clear all tasks from the board
- write: batch overwrite scratchpad todo items

Rules:
- Keep exactly one task in_progress at a time.
- Mark completed immediately when done.
- Upstream task must complete before blocked downstream tasks can start.
"""


def make_todo_tool(store: TaskStore) -> Tool:
    """生成单一统一的标准 todo 工具（对标 Pi & Hermes-Agent）。"""

    @tool(
        name="todo",
        description=TODO_GUIDELINES,
        is_parallel_safe=False,
    )
    async def todo(
        action: Literal["create", "update", "list", "get", "clear", "write"],
        subject: str | None = None,
        task_id: str | None = None,
        status: Literal["pending", "in_progress", "completed", "deleted"] | None = None,
        description: str | None = None,
        active_form: str | None = None,
        owner: str | None = None,
        add_blocked_by: list[str] | None = None,
        remove_blocked_by: list[str] | None = None,
        todos: list[dict[str, Any]] | None = None,
        include_deleted: bool = False,
    ) -> ToolResult:
        try:
            if action == "create":
                if not subject:
                    return ToolResult(
                        ok=False,
                        error="Parameter 'subject' is required for action 'create'",
                    )
                task = await store.create(
                    subject=subject,
                    description=description or "",
                    active_form=active_form,
                )
                return ToolResult(
                    ok=True,
                    data={
                        "action": "create",
                        "task": {
                            "id": task.id,
                            "subject": task.subject,
                            "status": task.status,
                        },
                        "board": store.render_board(),
                        "message": f"Created {task.id}",
                    },
                )

            elif action == "update":
                if not task_id:
                    return ToolResult(
                        ok=False,
                        error="Parameter 'task_id' is required for action 'update'",
                    )
                task, unblocked = await store.update(
                    task_id=task_id,
                    status=status,
                    subject=subject,
                    description=description,
                    active_form=active_form,
                    owner=owner,
                    add_blocked_by=add_blocked_by,
                    remove_blocked_by=remove_blocked_by,
                )
                return ToolResult(
                    ok=True,
                    data={
                        "action": "update",
                        "task": {
                            "id": task.id,
                            "subject": task.subject,
                            "status": task.status,
                            "blocked_by": task.blocked_by,
                        },
                        "unblocked": unblocked,
                        "board": store.render_board(),
                        "message": f"Updated {task.id}",
                    },
                )

            elif action == "list":
                tasks = store.list(include_deleted=include_deleted)
                return ToolResult(
                    ok=True,
                    data={
                        "action": "list",
                        "tasks": [
                            {
                                "id": t.id,
                                "subject": t.subject,
                                "status": t.status,
                                "owner": t.owner,
                                "active_form": t.active_form,
                                "blocked_by": t.blocked_by,
                            }
                            for t in tasks
                        ],
                        "board": store.render_board(),
                    },
                )

            elif action == "get":
                if not task_id:
                    return ToolResult(
                        ok=False,
                        error="Parameter 'task_id' is required for action 'get'",
                    )
                task = store.get(task_id)
                return ToolResult(
                    ok=True,
                    data={"action": "get", "task": asdict(task)},
                )

            elif action == "clear":
                store.clear()
                return ToolResult(
                    ok=True,
                    data={
                        "action": "clear",
                        "message": "Cleared all tasks",
                        "board": "(No active tasks)",
                    },
                )

            elif action == "write":
                if todos is None:
                    return ToolResult(
                        ok=False,
                        error="Parameter 'todos' is required for action 'write'",
                    )
                items = await store.batch_write(todos)
                return ToolResult(
                    ok=True,
                    data={
                        "action": "write",
                        "tasks": [
                            {"id": t.id, "subject": t.subject, "status": t.status}
                            for t in items
                        ],
                        "board": store.render_board(),
                    },
                )

            return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    return todo


def make_task_tools(store: TaskStore) -> list[Tool]:
    """导出单一 todo 标准工具（对标 Pi & Hermes）。"""
    return [make_todo_tool(store)]
