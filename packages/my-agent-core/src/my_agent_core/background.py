"""后台异步任务执行器与孤儿进程防御调度引擎。"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from my_agent_core.message_queue import (  # pyright: ignore[reportMissingImports]
        MessageQueue,
    )


@dataclass
class BackgroundJob:
    """单个后台作业状态。"""

    id: str
    description: str
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    result: str | None = None
    exit_code: int | None = None
    process: asyncio.subprocess.Process | None = None
    started_at: float = field(default_factory=time.time)


class BackgroundRunner:
    """管理后台异步作业生命周期并自动向 MessageQueue 投递完成通知。"""

    def __init__(self, message_queue: MessageQueue) -> None:
        self.message_queue = message_queue
        self.jobs: dict[str, BackgroundJob] = {}
        self._counter = 0
        atexit.register(self._sync_cleanup)

    def _sync_cleanup(self) -> None:
        """进程退出时强制清理所有存活的子进程，杜绝孤儿进程。"""
        for job in self.jobs.values():
            if (
                job.status == "running"
                and job.process
                and job.process.returncode is None
            ):
                with contextlib.suppress(Exception):
                    job.process.kill()

    async def run_process(
        self, command: str, cwd: Path | str, description: str = ""
    ) -> str:
        """异步启动操作系统后台子进程，立即返回 job_id。"""
        self._counter += 1
        job_id = f"bg_{self._counter:06x}"
        job = BackgroundJob(
            id=job_id, description=description or command, status="running"
        )
        self.jobs[job_id] = job

        async def _worker() -> None:
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    cwd=str(cwd),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                job.process = proc
                stdout, stderr = await proc.communicate()
                output = (
                    stdout.decode(errors="replace") + stderr.decode(errors="replace")
                ).strip()
                job.exit_code = proc.returncode
                job.result = output[:20000] if output else "(no output)"
                job.status = "completed" if proc.returncode == 0 else "failed"
            except Exception as e:
                job.status = "failed"
                job.result = str(e)
                job.exit_code = 1

            notification = (
                f'<task_notification id="{job.id}">\n'
                f"Background task {job.id} ({job.description}) {job.status} (exit code {job.exit_code}):\n"
                f"{job.result}\n"
                f"</task_notification>"
            )
            self.message_queue.add_followup(notification)

        asyncio.create_task(_worker())
        return job_id

    async def cancel_all(self) -> None:
        """取消所有正在运行的后台子进程。"""
        for job in self.jobs.values():
            if job.status == "running":
                job.status = "cancelled"
                if job.process and job.process.returncode is None:
                    with contextlib.suppress(Exception):
                        job.process.terminate()
                        await job.process.wait()
