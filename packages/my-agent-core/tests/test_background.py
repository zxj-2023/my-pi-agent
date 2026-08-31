import asyncio
import sys
from pathlib import Path

from my_agent_core.background import (  # pyright: ignore
    BackgroundRunner,
)

from my_agent_core.message_queue import (
    MessageQueue,  # pyright: ignore[reportMissingImports]
)


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
