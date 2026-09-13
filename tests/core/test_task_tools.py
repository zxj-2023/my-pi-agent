import asyncio
from pathlib import Path

from my_agent_core.task_store import TaskStore  # pyright: ignore
from my_agent_core.tools.builtin.task_tools import (  # pyright: ignore
    make_task_tools,
    make_todo_tool,
)


def test_todo_tool_crud_lifecycle(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        todo_tool = make_todo_tool(store)

        assert todo_tool.name == "todo"
        assert not todo_tool.is_parallel_safe

        # 1. create
        res1 = await todo_tool.execute(
            {
                "action": "create",
                "subject": "Implement Auth",
                "description": "JWT based auth",
            }
        )
        assert res1.ok
        assert res1.data["task"]["id"] == "task_1"
        assert "task_1: Implement Auth" in res1.data["board"]

        # 2. create second
        res2 = await todo_tool.execute({"action": "create", "subject": "Implement Tests"})
        assert res2.ok
        assert res2.data["task"]["id"] == "task_2"

        # 3. update (addBlockedBy)
        res_up = await todo_tool.execute({"action": "update", "task_id": "task_2", "add_blocked_by": ["task_1"]})
        assert res_up.ok
        assert res_up.data["task"]["blocked_by"] == ["task_1"]

        # 4. get
        res_get = await todo_tool.execute({"action": "get", "task_id": "task_1"})
        assert res_get.ok
        assert res_get.data["task"]["description"] == "JWT based auth"

        # 5. list
        res_list = await todo_tool.execute({"action": "list"})
        assert res_list.ok
        assert len(res_list.data["tasks"]) == 2

        # 6. complete task_1 -> unlocks task_2
        res_comp = await todo_tool.execute({"action": "update", "task_id": "task_1", "status": "completed"})
        assert res_comp.ok
        assert "task_2" in res_comp.data["unblocked"]
        assert "[x] task_1: Implement Auth" in res_comp.data["board"]

        # 7. clear
        res_clear = await todo_tool.execute({"action": "clear"})
        assert res_clear.ok
        assert len(store.list()) == 0

    asyncio.run(_test())


def test_todo_tool_batch_write(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        todo_tool = make_todo_tool(store)

        res = await todo_tool.execute(
            {
                "action": "write",
                "todos": [
                    {"subject": "Step 1", "status": "completed"},
                    {"subject": "Step 2", "status": "in_progress"},
                ],
            }
        )
        assert res.ok
        assert len(store.list()) == 2
        assert "[x] task_1: Step 1" in res.data["board"]

    asyncio.run(_test())


def test_todo_tool_never_throw_on_error(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        todo_tool = make_todo_tool(store)

        # Empty subject on create
        res_err1 = await todo_tool.execute({"action": "create", "subject": "   "})
        assert not res_err1.ok
        assert res_err1.error is not None and "cannot be empty" in res_err1.error

        # Non-existent task update
        res_err2 = await todo_tool.execute({"action": "update", "task_id": "task_999", "status": "completed"})
        assert not res_err2.ok
        assert res_err2.error is not None and "not found" in res_err2.error

        # Missing task_id for update
        res_err3 = await todo_tool.execute({"action": "update", "status": "completed"})
        assert not res_err3.ok
        assert res_err3.error is not None and "task_id" in res_err3.error

    asyncio.run(_test())


def test_make_task_tools_wrapper(tmp_path: Path):
    store = TaskStore(tmp_path)
    tools = make_task_tools(store)
    assert len(tools) == 1
    assert tools[0].name == "todo"
