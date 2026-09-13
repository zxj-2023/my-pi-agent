from pathlib import Path

from my_agent_llm.models import Response
from my_coding_agent import CodingAgent


class FakeLLM:
    async def achat(self, *a, **kw):
        return Response(content="ok", model="fake")

    async def achat_stream(self, *a, **kw):
        pass


def test_coding_agent_forwards_steer_and_abort(tmp_path: Path):
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    agent.steer("立即停止修改")
    assert agent.agent.message_queue.has_steering()
    assert agent.agent.message_queue.get_steering_messages()[0].content == "立即停止修改"

    agent.follow_up("随后运行测试")
    assert agent.agent.message_queue.has_followup()
    assert agent.agent.message_queue.get_followup_messages()[0].content == "随后运行测试"

    # abort 不抛异常
    agent.abort()


def test_coding_agent_steer_and_follow_up_queues(tmp_path: Path):
    agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")
    agent.steer("指令1")
    agent.steer("指令2")
    assert len(agent.agent.message_queue.queue) == 2
    steering1 = agent.agent.message_queue.get_steering_messages()
    assert [m.content for m in steering1] == ["指令1"]
    steering2 = agent.agent.message_queue.get_steering_messages()
    assert [m.content for m in steering2] == ["指令2"]

    agent.follow_up("追问1")
    agent.follow_up("追问2")
    assert len(agent.agent.message_queue.queue) == 2
    followup1 = agent.agent.message_queue.get_followup_messages()
    assert [m.content for m in followup1] == ["追问1"]
    followup2 = agent.agent.message_queue.get_followup_messages()
    assert [m.content for m in followup2] == ["追问2"]

    # abort 清空队列
    agent.steer("未处理转向")
    agent.follow_up("未处理追问")
    assert agent.agent.message_queue.has_steering()
    assert agent.agent.message_queue.has_followup()
    agent.abort()
    assert not agent.agent.message_queue.has_steering()
    assert not agent.agent.message_queue.has_followup()
    assert agent.agent._aborted is True
