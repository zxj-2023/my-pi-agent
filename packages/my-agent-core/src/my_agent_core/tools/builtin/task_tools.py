"""标准 4 增量 CRUD 任务工具与 todo_write 工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from my_agent_core.tools.core import Tool, ToolResult, tool

if TYPE_CHECKING:
    from my_agent_core.task_store import (  # pyright: ignore[reportMissingImports]
        TaskStore,
    )


def make_task_tools(store: TaskStore) -> list[Tool]:
    """生成标准 4 增量 CRUD 任务工具族与 todo_write 便捷工具。"""

    @tool(
        name="task_create",
        description="Create a new task on the task board with an assigned id.",
        is_parallel_safe=True,
    )
    async def task_create(
        subject: str,
        description: str = "",
        active_form: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            task = await store.create(
                subject=subject,
                description=description,
                active_form=active_form,
                metadata=metadata,
            )
            return ToolResult(
                ok=True,
                data={
                    "task": {
                        "id": task.id,
                        "subject": task.subject,
                        "status": task.status,
                    },
                    "message": f"Created {task.id}",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    @tool(
        name="task_update",
        description="Update an existing task's status, fields, or DAG dependencies.",
        is_parallel_safe=True,
    )
    async def task_update(
        task_id: str,
        status: Literal["pending", "in_progress", "completed", "deleted"] | None = None,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        owner: str | None = None,
        metadata: dict[str, Any] | None = None,
        add_blocked_by: list[str] | None = None,
        remove_blocked_by: list[str] | None = None,
    ) -> ToolResult:
        try:
            task, unblocked = await store.update(
                task_id=task_id,
                status=status,
                subject=subject,
                description=description,
                active_form=active_form,
                owner=owner,
                metadata=metadata,
                add_blocked_by=add_blocked_by,
                remove_blocked_by=remove_blocked_by,
            )
            return ToolResult(
                ok=True,
                data={
                    "task": {
                        "id": task.id,
                        "subject": task.subject,
                        "status": task.status,
                        "blocked_by": task.blocked_by,
                    },
                    "unblocked": unblocked,
                    "message": f"Updated {task.id}",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    @tool(
        name="task_get",
        description="Get full task details including description and dependencies.",
        is_parallel_safe=True,
    )
    def task_get(task_id: str) -> ToolResult:
        try:
            task = store.get(task_id)
            return ToolResult(
                ok=True,
                data={
                    "id": task.id,
                    "subject": task.subject,
                    "description": task.description,
                    "status": task.status,
                    "owner": task.owner,
                    "active_form": task.active_form,
                    "blocked_by": task.blocked_by,
                    "metadata": task.metadata,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    @tool(
        name="task_list",
        description="List all active tasks on the task board (concise summary).",
        is_parallel_safe=True,
    )
    def task_list(include_deleted: bool = False) -> ToolResult:
        try:
            tasks = store.list(include_deleted=include_deleted)
            return ToolResult(
                ok=True,
                data={
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
                    ]
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    @tool(
        name="todo_write",
        description="Batch overwrite or update scratchpad todo items.",
        is_parallel_safe=True,
    )
    async def todo_write(todos: list[dict[str, Any]]) -> ToolResult:
        try:
            items = await store.batch_write(todos)
            return ToolResult(
                ok=True,
                data={
                    "tasks": [
                        {"id": t.id, "subject": t.subject, "status": t.status}
                        for t in items
                    ],
                    "board": store.render_board(),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    return [task_create, task_update, task_get, task_list, todo_write]
