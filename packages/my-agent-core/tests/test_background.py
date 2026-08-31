import asyncio
import sys
from pathlib import Path

from my_agent_llm.models import StreamChunk  # pyright: ignore[reportMissingImports]

from my_agent_core.agent import Agent  # pyright: ignore[reportMissingImports]
from my_agent_core.background import BackgroundRunner  # pyright: ignore
from my_agent_core.message_queue import (
    MessageQueue,  # pyright: ignore[reportMissingImports]
)
from my_agent_core.session import Session  # pyright: ignore[reportMissingImports]


class _DummyLLM:
    async def achat_stream(self, messages, tools=None, **kwargs):
        yield StreamChunk(content="Hello")


def test_background_runner_executes_and_notifies(tmp_path: Path):
    async def _test():
        mq = MessageQueue()
        runner = BackgroundRunner(mq)

        # Run a quick python print command using current sys.executable
        py_exe = sys.executable
        cmd = f'"{py_exe}" -c "import time; time.sleep(0.1); print(\'Hello from background\')"'
        job_id = await runner.run_process(cmd, cwd=tmp_path, description="test task")
        assert job_id.startswith("bg_")
        assert runner.jobs[job_id].status == "running"

        # Wait for completion
        await asyncio.sleep(0.4)
        assert runner.jobs[job_id].status == "completed"
        assert "Hello from background" in (runner.jobs[job_id].result or "")

        # Verify MessageQueue received the follow-up notification
        assert mq.has_followup()
        notifications = mq.get_followup_messages()
        assert len(notifications) == 1
        assert f'<task_notification id="{job_id}">' in notifications[0].content

    asyncio.run(_test())


def test_background_runner_cancel_all(tmp_path: Path):
    async def _test():
        mq = MessageQueue()
        runner = BackgroundRunner(mq)

        py_exe = sys.executable
        cmd = f'"{py_exe}" -c "import time; time.sleep(5); print(\'Should be cancelled\')"'
        job_id = await runner.run_process(cmd, cwd=tmp_path, description="long sleep")

        await asyncio.sleep(0.1)
        await runner.cancel_all()

        assert runner.jobs[job_id].status == "cancelled"

    asyncio.run(_test())


def test_agent_abort_cancels_background_processes(tmp_path: Path):
    async def _test():
        session = Session(path=tmp_path / "session.jsonl")
        agent = Agent(
            llm=_DummyLLM(),
            session=session,
            tools=[],
            memory_dir=False,
            task_store=False,
            plugin_dirs=[],
            subagent_dirs=[],
        )

        py_exe = sys.executable
        cmd = f'"{py_exe}" -c "import time; time.sleep(5); print(\'Should abort\')"'
        job_id = await agent.background_runner.run_process(
            cmd, cwd=tmp_path, description="long job"
        )

        assert agent.background_runner.jobs[job_id].status == "running"

        # Call agent.abort()
        agent.abort()
        await asyncio.sleep(0.3)

        assert agent.background_runner.jobs[job_id].status == "cancelled"

    asyncio.run(_test())
