# pyright: reportMissingImports=false
import pytest
from my_agent_llm import Message, Response, StreamChunk

from my_agent_core.events import (
    AgentEnd,
    AutoRetryEnd,
    AutoRetryStart,
)
from my_agent_core.loop import run_agent_loop
from my_agent_core.registry import ToolRegistry
from my_agent_core.retry import AutoRetryPolicy


class FlakyFakeLLM:
    """可配置前 N 次失败、随后成功的 FakeLLM。"""

    def __init__(self, failures: list[Exception], final_response: Response):
        self.failures = list(failures)
        self.final_response = final_response
        self.attempts = 0

    async def achat_stream(self, *, messages, tools=None, model=None, **kwargs):
        _ = (messages, tools, model, kwargs)
        self.attempts += 1
        if self.failures:
            exc = self.failures.pop(0)
            raise exc

        yield StreamChunk(content=self.final_response.content)


@pytest.mark.anyio
async def test_agent_loop_retries_on_503_and_recovers():
    # 模拟第 1 次报 503 瞬时错误，第 2 次成功
    flaky = FlakyFakeLLM(
        failures=[RuntimeError("Error code 503: Service Unavailable")],
        final_response=Response(content="Recovered after 503!", model="fake-model"),
    )
    # 使用极小的 base_delay_ms 加快测试速度
    fast_policy = AutoRetryPolicy(max_retries=3, base_delay_ms=10.0, max_delay_ms=50.0, jitter=0.0)

    events = []
    async for ev in run_agent_loop(
        llm=flaky,
        messages=[Message(role="user", content="hello")],
        tools=ToolRegistry(),
        retry_policy=fast_policy,
    ):
        events.append(ev)

    # 1. 验证重试事件发射
    retry_starts = [e for e in events if isinstance(e, AutoRetryStart)]
    assert len(retry_starts) == 1
    assert retry_starts[0].attempt == 1
    assert retry_starts[0].max_attempts == 3

    retry_ends = [e for e in events if isinstance(e, AutoRetryEnd)]
    assert len(retry_ends) == 1
    assert retry_ends[0].success is True
    assert retry_ends[0].attempt == 1

    # 2. 验证最终成功交付
    agent_ends = [e for e in events if isinstance(e, AgentEnd)]
    assert len(agent_ends) == 1
    assert agent_ends[0].stop_reason == "end_turn"
    assert agent_ends[0].final_text == "Recovered after 503!"
    assert flaky.attempts == 2


@pytest.mark.anyio
async def test_agent_loop_fails_fast_on_401_without_retry():
    # 模拟 401 致命凭证错误
    fatal = FlakyFakeLLM(
        failures=[RuntimeError("Error code: 401 - Authentication Fails, Your api key is invalid")],
        final_response=Response(content="never reached", model="fake-model"),
    )
    fast_policy = AutoRetryPolicy(max_retries=3, base_delay_ms=10.0)

    events = []
    async for ev in run_agent_loop(
        llm=fatal,
        messages=[Message(role="user", content="hello")],
        tools=ToolRegistry(),
        retry_policy=fast_policy,
    ):
        events.append(ev)

    # 401 必须立即熔断，绝不发射 AutoRetryStart
    retry_starts = [e for e in events if isinstance(e, AutoRetryStart)]
    assert len(retry_starts) == 0

    agent_ends = [e for e in events if isinstance(e, AgentEnd)]
    assert len(agent_ends) == 1
    assert agent_ends[0].stop_reason == "error"
    assert fatal.attempts == 1


@pytest.mark.anyio
async def test_agent_loop_retries_exhausted():
    # 模拟持续 503 错误耗尽重试次数
    always_flaky = FlakyFakeLLM(
        failures=[
            RuntimeError("503 Service Unavailable"),
            RuntimeError("503 Service Unavailable"),
            RuntimeError("503 Service Unavailable"),
            RuntimeError("503 Service Unavailable"),
        ],
        final_response=Response(content="never", model="fake-model"),
    )
    fast_policy = AutoRetryPolicy(max_retries=2, base_delay_ms=10.0, max_delay_ms=30.0, jitter=0.0)

    events = []
    async for ev in run_agent_loop(
        llm=always_flaky,
        messages=[Message(role="user", content="hello")],
        tools=ToolRegistry(),
        retry_policy=fast_policy,
    ):
        events.append(ev)

    retry_starts = [e for e in events if isinstance(e, AutoRetryStart)]
    assert len(retry_starts) == 2  # attempt 1, 2

    retry_ends = [e for e in events if isinstance(e, AutoRetryEnd)]
    assert len(retry_ends) == 1
    assert retry_ends[0].success is False
    assert retry_ends[0].attempt == 2

    agent_ends = [e for e in events if isinstance(e, AgentEnd)]
    assert len(agent_ends) == 1
    assert agent_ends[0].stop_reason == "error"
    assert always_flaky.attempts == 3  # initial + 2 retries
