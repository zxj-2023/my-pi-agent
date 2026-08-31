import asyncio
from pathlib import Path

from my_agent_core.task_store import TaskStore  # pyright: ignore
from my_agent_core.tools.builtin import (  # pyright: ignore
    make_task_tools,
)


def test_task_tools_crud_lifecycle(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        tools = {t.name: t for t in make_task_tools(store)}

        assert "task_create" in tools
        assert "task_update" in tools
        assert "task_get" in tools
        assert "task_list" in tools
        assert "todo_write" in tools

        # 1. task_create
        res1 = await tools["task_create"](
            subject="Implement Auth", description="JWT based auth"
        )
        assert res1.ok
        assert res1.data["task"]["id"] == "task_1"

        # 2. task_create second
        res2 = await tools["task_create"](subject="Implement Tests")
        assert res2.ok
        assert res2.data["task"]["id"] == "task_2"

        # 3. task_update (addBlockedBy)
        res_up = await tools["task_update"](task_id="task_2", add_blocked_by=["task_1"])
        assert res_up.ok
        assert res_up.data["task"]["blocked_by"] == ["task_1"]

        # 4. task_get
        res_get = tools["task_get"](task_id="task_1")
        assert res_get.ok
        assert res_get.data["description"] == "JWT based auth"

        # 5. task_list
        res_list = tools["task_list"]()
        assert res_list.ok
        assert len(res_list.data["tasks"]) == 2

        # 6. complete task_1 -> unlocks task_2
        res_comp = await tools["task_update"](task_id="task_1", status="completed")
        assert res_comp.ok
        assert "task_2" in res_comp.data["unblocked"]

    asyncio.run(_test())


def test_todo_write_tool(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        tools = {t.name: t for t in make_task_tools(store)}

        res = await tools["todo_write"](
            todos=[
                {"subject": "Step 1", "status": "completed"},
                {"subject": "Step 2", "status": "in_progress"},
            ]
        )
        assert res.ok
        assert len(store.list()) == 2
        assert "[x] task_1: Step 1" in res.data["board"]

    asyncio.run(_test())


def test_task_tools_never_throw_on_error(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        tools = {t.name: t for t in make_task_tools(store)}

        # Empty subject
        res_err1 = await tools["task_create"](subject="   ")
        assert not res_err1.ok
        assert "cannot be empty" in res_err1.error

        # Non-existent task update
        res_err2 = await tools["task_update"](task_id="task_999", status="completed")
        assert not res_err2.ok
        assert "not found" in res_err2.error

    asyncio.run(_test())


def test_task_tools_parallel_execution(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        tools = {t.name: t for t in make_task_tools(store)}

        # Concurrently execute 10 task_create tool calls
        results = await asyncio.gather(
            *(
                tools["task_create"].execute({"subject": f"Tool Task {i}"})
                for i in range(10)
            )
        )
        for res in results:
            assert res.ok
            assert "task" in res.data

        assert len(store.list()) == 10

    asyncio.run(_test())
