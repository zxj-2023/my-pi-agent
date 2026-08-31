import asyncio
from pathlib import Path

from my_agent_llm import StreamChunk  # pyright: ignore

from my_agent_core.agent import Agent  # pyright: ignore
from my_agent_core.session import Session  # pyright: ignore
from my_agent_core.task_store import TaskStore  # pyright: ignore


class CapturingFakeLLM:
    def __init__(self):
        self.captured_views = []

    async def achat_stream(self, messages, tools=None, **kwargs):
        self.captured_views.append(list(messages))
        yield StreamChunk(content="Task processed successfully.")


def test_agent_task_board_projection_and_zero_session_pollution(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        await store.create(subject="Build database schema")
        await store.create(subject="Write API endpoints")
        await store.update("task_1", status="in_progress")

        session = Session(path=tmp_path / "session.jsonl")
        fake_llm = CapturingFakeLLM()

        agent = Agent(
            llm=fake_llm,
            session=session,
            tools=[],
            task_store=store,
            memory_dir=False,
            plugin_dirs=[],
            subagent_dirs=[],
        )

        await agent.run("What is on my task board?")

        # Check LLM view received the board
        assert len(fake_llm.captured_views) >= 1
        last_view = fake_llm.captured_views[-1]
        all_text = "".join(m.content for m in last_view if isinstance(m.content, str))
        assert "<TASK_BOARD>" in all_text
        assert "[>] task_1: Build database schema" in all_text

        # Check Session disk is completely clean of <TASK_BOARD>
        disk_messages = session.get_current_path_messages()
        for msg in disk_messages:
            if isinstance(msg.content, str):
                assert "<TASK_BOARD>" not in msg.content

    asyncio.run(_test())


def test_agent_task_store_disabled(tmp_path: Path):
    async def _test():
        session = Session(path=tmp_path / "session.jsonl")
        fake_llm = CapturingFakeLLM()

        agent = Agent(
            llm=fake_llm,
            session=session,
            tools=[],
            task_store=False,
            memory_dir=False,
            plugin_dirs=[],
            subagent_dirs=[],
        )

        assert agent.task_store is None
        # task_* tools should not be registered
        tool_names = [t.name for t in agent.registry.list()]
        assert "task_create" not in tool_names
        assert "todo_write" not in tool_names

        await agent.run("Hello")
        last_view = fake_llm.captured_views[-1]
        all_text = "".join(m.content for m in last_view if isinstance(m.content, str))
        assert "<TASK_BOARD>" not in all_text

    asyncio.run(_test())
