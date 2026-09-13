import asyncio
import json
from pathlib import Path

from my_agent_llm.models import (  # pyright: ignore[reportMissingImports]
    StreamChunk,
)

from my_agent_core.agent import Agent  # pyright: ignore[reportMissingImports]
from my_agent_core.session import Session  # pyright: ignore[reportMissingImports]
from my_agent_core.task_store import TaskStore  # pyright: ignore[reportMissingImports]


class NudgeTestLLM:
    def __init__(self):
        self.turns = 0
        self.received_messages = []

    async def achat_stream(self, messages, tools=None, **kwargs):
        self.turns += 1
        self.received_messages.append(list(messages))
        if self.turns == 1:
            # Turn 1: Create task and mark in_progress
            yield StreamChunk(
                content="Starting task.",
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "todo",
                            "arguments": json.dumps({"action": "create", "subject": "Write code"}),
                        },
                    },
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {
                            "name": "todo",
                            "arguments": json.dumps(
                                {
                                    "action": "update",
                                    "task_id": "task_1",
                                    "status": "in_progress",
                                }
                            ),
                        },
                    },
                ],
            )
        elif self.turns == 2:
            # Turn 2: Model forgot to call todo(completed), just says it's done without tools
            yield StreamChunk(content="I have written all the code, job is finished!")
        elif self.turns == 3:
            # Turn 3: Model receives the nudge and marks completed
            yield StreamChunk(
                content="Oh sorry, marking it completed now.",
                tool_calls=[
                    {
                        "id": "c3",
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
                ],
            )
        else:
            # Turn 4: Final wrap up
            yield StreamChunk(content="Everything completed!")


def test_agent_nudges_model_when_in_progress_task_remains(tmp_path: Path):
    async def _test():
        store = TaskStore(tmp_path)
        session = Session(path=tmp_path / "session.jsonl")
        llm = NudgeTestLLM()

        agent = Agent(
            llm=llm,
            session=session,
            tools=[],
            task_store=store,
            memory_dir=False,
            plugin_dirs=[],
            subagent_dirs=[],
        )

        ans = await agent.run("Start working on the task.")
        assert ans == "Everything completed!"
        assert store.get("task_1").status == "completed"
        assert llm.turns >= 3

        # Verify Turn 3 received the reminder message
        turn3_msgs = llm.received_messages[2]
        all_text = "".join(m.content for m in turn3_msgs if isinstance(m.content, str))
        assert "is still marked as 'in_progress'" in all_text

    asyncio.run(_test())
