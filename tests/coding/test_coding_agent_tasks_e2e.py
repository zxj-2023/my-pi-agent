import asyncio
import json
import sys
from pathlib import Path

from my_agent_core.session import Session  # pyright: ignore[reportMissingImports]
from my_agent_core.task_store import TaskStore  # pyright: ignore[reportMissingImports]
from my_agent_llm.models import StreamChunk  # pyright: ignore[reportMissingImports]

from my_coding_agent.agent import CodingAgent  # pyright: ignore[reportMissingImports]


class ScriptedCodingLLM:
    def __init__(self, py_exe: str):
        self.py_exe = py_exe
        self.turns = 0
        self.calls = []

    async def achat_stream(self, messages, tools=None, **kwargs):
        self.turns += 1
        self.calls.append(list(messages))
        if self.turns == 1:
            cmd = f'"{self.py_exe}" -c "import time; time.sleep(0.1); print(\'All 10 tests passed\')"'
            yield StreamChunk(
                content="Starting background test task.",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "todo",
                            "arguments": json.dumps(
                                {"action": "create", "subject": "Run test suite"}
                            ),
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps(
                                {"command": cmd, "run_in_background": True}
                            ),
                        },
                    },
                ],
            )
        elif self.turns == 2:
            yield StreamChunk(content="Waiting for background task...")
        else:
            yield StreamChunk(
                content="Completed!",
                tool_calls=[
                    {
                        "id": "call_3",
                        "type": "function",
                        "function": {
                            "name": "todo",
                            "arguments": json.dumps(
                                {
                                    "action": "update",
                                    "task_id": "task_1",
                                    "status": "completed",
                                }
                            ),
                        },
                    }
                ]
                if self.turns == 3
                else None,
            )


def test_coding_agent_tasks_and_background_e2e(tmp_path: Path):
    async def _test():
        py_exe = sys.executable
        fake_llm = ScriptedCodingLLM(py_exe)
        session = Session(path=tmp_path / "session.jsonl")
        store = TaskStore(tmp_path)

        agent = CodingAgent(
            workspace=tmp_path,
            llm=fake_llm,
            session=session,
            task_store=store,
            memory_dir=False,
            plugin_dirs=[],
            subagent_dirs=[],
        )

        ans1 = await agent.run("Please run tests in background.")
        assert ans1 == "Waiting for background task..."

        await asyncio.sleep(0.3)

        ans2 = await agent.run("Check status")
        assert ans2 == "Completed!"
        assert store.get("task_1").status == "completed"

    asyncio.run(_test())
