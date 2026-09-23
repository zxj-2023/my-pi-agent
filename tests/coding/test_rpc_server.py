from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import pytest

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
)
from my_agent_llm import Config
from my_agent_llm.auth.manager import AuthManager
from my_agent_llm.auth.schema import ApiKeyCredential
from my_agent_llm.models import Message, Response, StreamChunk
from my_coding_agent import AgentPaths, CodingAgent
from my_coding_agent.rpc_server import RpcServer, serialize_event


class FakeLLM:
    def __init__(self, model: str = "fake-model"):
        self.model = model

    async def achat(self, *a, **kw):
        return Response(content="ok", model=self.model)

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="", metadata={"reasoning_content": "thinking..."})
        yield StreamChunk(content="answer text")


def test_serialize_all_events():
    msg = Message(role="assistant", content="hello")
    chunk = StreamChunk(content="delta", metadata={"reasoning_content": "think"})

    # AgentStart & AgentEnd
    start = serialize_event(AgentStart(system_prompt="sys", user_input="hi"))
    assert start["type"] == "agent_start"
    assert start["user_input"] == "hi"

    end = serialize_event(AgentEnd(messages=[msg], final_text="done", iterations=1, stop_reason="end_turn"))
    assert end["type"] == "agent_end"
    assert end["stop_reason"] == "end_turn"

    # TurnStart & TurnEnd
    t_start = serialize_event(TurnStart(iteration=1))
    assert t_start["type"] == "turn_start"
    assert t_start["iteration"] == 1

    t_end = serialize_event(TurnEnd())
    assert t_end["type"] == "turn_end"

    # Message Lifecycle
    m_start = serialize_event(MessageStart(message=msg))
    assert m_start["type"] == "message_start"
    assert m_start["message"]["role"] == "assistant"

    m_update = serialize_event(MessageUpdate(message=msg, chunk=chunk))
    assert m_update["type"] == "message_update"
    assert m_update["delta"] == "delta"
    assert m_update["reasoning_delta"] == "think"

    m_end = serialize_event(MessageEnd(message=msg))
    assert m_end["type"] == "message_end"

    # Tool Execution
    tool_start = serialize_event(ToolExecutionStart(tool_call_id="c1", tool_name="read", args={"path": "a.py"}))
    assert tool_start["type"] == "tool_execution_start"
    assert tool_start["toolCallId"] == "c1"
    assert tool_start["toolName"] == "read"

    tool_end = serialize_event(ToolExecutionEnd(tool_call_id="c1", tool_name="read", result="content", is_error=False))
    assert tool_end["type"] == "tool_execution_end"
    assert tool_end["toolCallId"] == "c1"
    assert tool_end["isError"] is False


@pytest.mark.anyio
async def test_rpc_server_initialize_and_prompt(tmp_path: Path):
    in_buf = io.StringIO()
    out_buf = io.StringIO()
    err_buf = io.StringIO()

    server = RpcServer(stdin=in_buf, stdout=out_buf, stderr=err_buf, llm=FakeLLM())

    # 1. Initialize
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"workspace": str(tmp_path), "model": "fake-model"},
    }
    resp = await server.handle_request(init_req)
    assert resp["id"] == 1
    assert resp["result"]["status"] == "ok"
    assert server.agent is not None
    assert server.agent.workspace == tmp_path.resolve()

    # Inject fake LLM to avoid real API
    server.agent.agent.llm = FakeLLM()  # type: ignore[assignment]

    # 2. Prompt Stream
    prompt_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "prompt",
        "params": {"text": "hello agent"},
    }
    resp2 = await server.handle_request(prompt_req)
    assert resp2["id"] == 2
    assert resp2["result"]["status"] == "completed"

    # 检查输出中是否有推送的事件 notifications
    output_lines = [json.loads(line) for line in out_buf.getvalue().splitlines() if line.strip()]
    event_types = [msg.get("params", {}).get("type") for msg in output_lines if msg.get("method") == "event"]
    assert "agent_start" in event_types
    assert "message_update" in event_types
    assert "agent_end" in event_types


@pytest.mark.anyio
async def test_rpc_server_steer_abort_and_shutdown(tmp_path: Path):
    in_buf = io.StringIO()
    out_buf = io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf)
    server.agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    # Steer
    steer_req = {"jsonrpc": "2.0", "id": 10, "method": "steer", "params": {"message": "即时纠偏"}}
    steer_resp = await server.handle_request(steer_req)
    assert steer_resp["result"]["status"] == "ok"
    assert server.agent.agent.message_queue.has_steering()

    # Followup
    followup_req = {"jsonrpc": "2.0", "id": 11, "method": "followup", "params": {"message": "排队任务"}}
    followup_resp = await server.handle_request(followup_req)
    assert followup_resp["result"]["status"] == "ok"
    assert server.agent.agent.message_queue.has_followup()

    # Abort
    abort_req = {"jsonrpc": "2.0", "id": 12, "method": "abort", "params": {}}
    abort_resp = await server.handle_request(abort_req)
    assert abort_resp["result"]["status"] == "ok"

    # Shutdown
    shutdown_req = {"jsonrpc": "2.0", "id": 13, "method": "shutdown", "params": {}}
    shutdown_resp = await server.handle_request(shutdown_req)
    assert shutdown_resp["result"]["status"] == "ok"
    assert server.is_shutting_down is True


@pytest.mark.anyio
async def test_rpc_server_errors_and_edge_cases(tmp_path: Path):
    in_buf = io.StringIO()
    out_buf = io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf)

    # 1. Uninitialized prompt error
    prompt_req = {"jsonrpc": "2.0", "id": 100, "method": "prompt", "params": {"text": "hi"}}
    resp = await server.handle_request(prompt_req)
    assert resp["error"]["code"] == -32001
    assert "Agent not initialized" in resp["error"]["message"]

    # 2. Unknown method error
    unknown_req = {"jsonrpc": "2.0", "id": 101, "method": "nonexistent", "params": {}}
    resp = await server.handle_request(unknown_req)
    assert resp["error"]["code"] == -32601
    assert "Method 'nonexistent' not found" in resp["error"]["message"]


@pytest.mark.anyio
async def test_rpc_server_concurrent_abort_during_prompt(tmp_path: Path):
    class SlowFakeLLM:
        def __init__(self):
            self.model = "slow-model"

        async def achat_stream(self, *a, **kw):
            for i in range(10):
                await asyncio.sleep(0.02)
                yield StreamChunk(content=f"chunk{i} ")

    in_buf = io.StringIO()
    out_buf = io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf, llm=SlowFakeLLM())

    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(tmp_path)},
        }
    )

    # 启动长时间 Prompt
    prompt_task = asyncio.create_task(
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "prompt",
                "params": {"text": "run forever"},
            }
        )
    )

    # 短暂等待生成开始
    await asyncio.sleep(0.04)

    # 发送并发中断
    abort_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "abort",
            "params": {},
        }
    )
    assert abort_resp["result"]["status"] == "ok"

    # prompt 应当迅速中止退出，而不是跑满 10 个 chunk
    prompt_resp = await prompt_task
    assert prompt_resp["result"]["status"] == "completed"


@pytest.mark.anyio
async def test_rpc_server_run_forever(tmp_path: Path):
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(tmp_path)}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "abort", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}),
    ]
    in_buf = io.StringIO("\n".join(lines) + "\n")
    out_buf = io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf, llm=FakeLLM())

    await server.run_forever()

    output = out_buf.getvalue()
    assert '"id": 1' in output
    assert '"id": 2' in output
    assert '"id": 3' in output
    assert server.is_shutting_down is True


@pytest.mark.anyio
async def test_rpc_server_zero_pollution_workspace(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "custom_agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))

    workspace_dir = tmp_path / "user_project"
    workspace_dir.mkdir()

    server = RpcServer(llm=FakeLLM())
    resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(workspace_dir)},
        }
    )
    assert resp["result"]["status"] == "ok"

    # 关键断言：用户工程工作区内绝对不能出现任何 .my_agent_core 目录！
    assert not (workspace_dir / ".my_agent_core").exists()

    # 会话必须集中存储在全局用户目录下
    paths = AgentPaths(home=custom_home)
    assert paths.sessions_dir.exists()
    assert paths.default_session_path(workspace_dir).parent.exists()


@pytest.mark.anyio
async def test_model_switch_updates_context_budget(tmp_path: Path, monkeypatch):
    """切模型后压缩预算跟随新窗口（阀值 = 80%×窗口）：业务层显式同步。"""
    custom_home = tmp_path / "agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    paths = AgentPaths(home=custom_home)
    paths.ensure_directories()
    AuthManager(auth_path=paths.auth_path).set_api_key("deepseek", "sk-test-key")

    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    server = RpcServer(llm=FakeLLM())
    init_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(workspace_dir), "model": "deepseek/deepseek-flash"},
        }
    )
    assert init_resp["result"]["status"] == "ok"
    assert server.agent is not None
    ctx = server.agent.agent.context_manager
    assert ctx.budget == 128_000  # 注入的 FakeLLM 无 config.model → 未知模型回落

    switch_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "model_switch",
            "params": {"model": "deepseek/deepseek-chat"},
        }
    )
    assert switch_resp["result"]["status"] == "ok"
    # 同一个 ContextManager 对象被就地更新（非重建）
    assert ctx.budget == 64_000  # deepseek-chat → 64K 窗口
    assert ctx.budget_threshold == 64_000 * 4 // 5


class UsageFakeLLM(FakeLLM):
    """带 usage 的替身：让会话累计量显著大于真实上下文占用。"""

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(
            content="ok",
            usage={"prompt_tokens": 50_000, "completion_tokens": 100, "total_tokens": 51_000},
        )


@pytest.mark.anyio
async def test_footer_context_tokens_is_view_estimate_not_session_total(tmp_path: Path):
    """Footer 的上下文占用必须是「本次视图估算」，不是「会话累计消耗」（回归）。"""
    in_buf, out_buf, err_buf = io.StringIO(), io.StringIO(), io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf, stderr=err_buf, llm=UsageFakeLLM())
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(tmp_path), "model": "fake-model"},
        }
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "hello"}})

    events = [json.loads(line) for line in out_buf.getvalue().splitlines() if line.strip()]
    usages = [
        e["params"]["usage"]
        for e in events
        if e.get("method") == "event" and isinstance(e.get("params", {}).get("usage"), dict)
    ]
    assert usages, "没有任何携带 usage 的事件通知"
    last = usages[-1]
    assert last["total"] >= 51_000  # 会话累计量确实很大（旧实现把它当了分子）
    assert 0 < last["contextTokens"] < 51_000  # 修复后：上下文占用（视图估算）
    assert server.agent is not None
    assert last["contextTokens"] == server.agent.agent.context_manager.context_tokens


class DeepseekFlashFakeLLM(FakeLLM):
    """deepseek-flash 替身：config 带真实模型名，用于校验窗口与成本解析。"""

    def __init__(self):
        super().__init__()
        self.config = Config(provider="deepseek", model="deepseek-flash")

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(
            content="ok",
            usage={
                "prompt_tokens": 50_000,
                "completion_tokens": 100,
                "cache_read_tokens": 1700,
                "total_tokens": 51_800,
            },
        )


@pytest.mark.anyio
async def test_footer_context_window_resolves_from_llm_config_model(tmp_path: Path):
    """逐轮 stats 的窗口与成本必须用可回落解析的模型名（启动时 agent.model 为空）。

    回归：曾用 getattr(agent, "model", "") → 空串 → 窗口回落 128k（与 deepseek-flash
    真实的 1M、与已接线到模型的压缩预算自相矛盾），且成本分支全不命中导致 cost 恒为 0。
    """
    in_buf, out_buf, err_buf = io.StringIO(), io.StringIO(), io.StringIO()
    server = RpcServer(stdin=in_buf, stdout=out_buf, stderr=err_buf, llm=DeepseekFlashFakeLLM())
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(tmp_path), "model": "deepseek/deepseek-flash"},
        }
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "hello"}})

    events = [json.loads(line) for line in out_buf.getvalue().splitlines() if line.strip()]
    windows = [
        e["params"]["contextWindow"]
        for e in events
        if e.get("method") == "event" and isinstance(e.get("params", {}).get("contextWindow"), int)
    ]
    assert windows, "没有任何携带 contextWindow 的事件通知"
    assert all(w == 1_000_000 for w in windows)  # deepseek-flash → 1M，而非 128k 兜底

    costs = [
        e["params"]["usage"]["cost"]
        for e in events
        if e.get("method") == "event" and isinstance(e.get("params", {}).get("usage"), dict)
    ]
    assert costs and costs[-1] > 0  # 成本匹配必须命中 deepseek 分支


@pytest.mark.anyio
async def test_rpc_server_login_updates_auth_manager_and_env(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "custom_agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))

    workspace_dir = tmp_path / "user_project"
    workspace_dir.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(workspace_dir)},
        }
    )

    # 执行 login
    login_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "login",
            "params": {"provider": "deepseek", "key": "sk-deepseek-test-999"},
        }
    )
    assert login_resp["result"]["status"] == "ok"

    # 断言 1: 项目工作区保持零污染，绝不向工作区 .env 写入 Key
    env_file = workspace_dir / ".env"
    assert not env_file.exists()

    # 断言 2: 全局 auth.json 凭据中心同步更新
    paths = AgentPaths(home=custom_home)
    assert paths.auth_path.exists()
    auth_mgr = AuthManager(auth_path=paths.auth_path)
    cred = auth_mgr.get_credential("deepseek")
    assert cred is not None
    assert isinstance(cred, ApiKeyCredential)
    assert cred.key == "sk-deepseek-test-999"


@pytest.mark.anyio
async def test_rpc_server_credentials_resolution_from_auth_store(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "custom_agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))

    # 预先在 auth.json 写入 deepseek 凭证
    paths = AgentPaths(home=custom_home)
    paths.ensure_directories()
    auth_mgr = AuthManager(auth_path=paths.auth_path)
    auth_mgr.set_api_key("deepseek", "sk-stored-in-auth-json")

    # 确保环境中无任何相关环境变量
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    workspace_dir = tmp_path / "user_project"
    workspace_dir.mkdir()

    server = RpcServer()  # llm is None, should resolve from auth_mgr
    resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(workspace_dir), "model": "deepseek/deepseek-chat"},
        }
    )
    assert resp["result"]["status"] == "ok"
    assert server.agent is not None
    assert server.agent.agent.llm is not None
    assert server.agent.agent.llm.config.provider == "deepseek"
    assert server.agent.agent.llm.config.api_key == "sk-stored-in-auth-json"


@pytest.mark.anyio
async def test_rpc_server_session_delete(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "custom_agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace_dir = tmp_path / "user_project"
    workspace_dir.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(workspace_dir)},
        }
    )

    paths = AgentPaths(home=custom_home)
    s_dir = paths.project_session_dir(workspace_dir)

    # 创建一个额外的非活跃历史会话文件
    other_session_file = s_dir / "old-session-123.jsonl"
    other_session_file.write_text('{"type": "session_info", "id": "old-session-123"}\n', encoding="utf-8")
    assert other_session_file.exists()

    # 1. 尝试删除当前活跃会话 -> 必须被拒绝 (对标 Pi 规范)
    assert server.agent is not None
    active_id = server.agent.session.id
    err_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session_delete",
            "params": {"session_id": active_id},
        }
    )
    assert "error" in err_resp
    assert err_resp["error"]["code"] == -32005

    # 2. 删除非活跃会话 -> 成功删除
    del_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session_delete",
            "params": {"session_id": "old-session-123"},
        }
    )
    assert del_resp["result"]["status"] == "ok"
    assert not other_session_file.exists()


@pytest.mark.anyio
async def test_rpc_server_debug_mode_and_dump(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "custom_agent_home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace_dir = tmp_path / "user_project"
    workspace_dir.mkdir()

    server = RpcServer(llm=FakeLLM())
    init_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(workspace_dir), "debug": True},
        }
    )
    assert init_resp["result"]["status"] == "ok"
    assert init_resp["result"]["debug"] is True
    assert server.debug_mode is True
    assert server.tracer is not None

    # 产生一次交互
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "prompt",
            "params": {"text": "hello debug"},
        }
    )

    # 验证分会话日志与事件流文件生成
    session_id = init_resp["result"]["session_id"]
    paths = AgentPaths(home=custom_home)
    session_log = paths.session_log_path(workspace_dir, session_id)
    session_events = paths.session_events_path(workspace_dir, session_id)
    assert session_log.is_file()
    assert session_events.is_file()
    content = session_log.read_text(encoding="utf-8")
    assert "[AGENT_START]" in content

    # 导出 debug_dump
    dump_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "debug_dump",
            "params": {},
        }
    )
    assert dump_resp["result"]["status"] == "ok"
    dump_file = Path(dump_resp["result"]["dump_file"])
    assert dump_file.is_file()
    assert dump_resp["result"]["log_file"] == str(session_log)
    assert dump_resp["result"]["events_file"] == str(session_events)
    snapshot = dump_resp["result"]["snapshot"]
    assert "messages" in snapshot
    assert "system_prompt" in snapshot

    # 关闭服务端
    await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": {}})
    assert server.tracer is None


@pytest.mark.anyio
async def test_rpc_server_steer_accepts_flexible_keys(tmp_path: Path):
    """验证 steer 方法支持 message, prompt, text 三种参数命名。"""
    server = RpcServer()
    server.agent = CodingAgent(workspace=tmp_path, llm=FakeLLM(), session=tmp_path / "s.jsonl")

    # 1. params: { message: "msg1" }
    r1 = await server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "steer", "params": {"message": "msg1"}})
    assert r1["result"]["status"] == "ok"
    assert server.agent.agent.message_queue.get_steering_messages()[0].content == "msg1"

    # 2. params: { prompt: "msg2" }
    r2 = await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "steer", "params": {"prompt": "msg2"}})
    assert r2["result"]["status"] == "ok"
    assert server.agent.agent.message_queue.get_steering_messages()[0].content == "msg2"

    # 3. params: { text: "msg3" }
    r3 = await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "steer", "params": {"text": "msg3"}})
    assert r3["result"]["status"] == "ok"
    assert server.agent.agent.message_queue.get_steering_messages()[0].content == "msg3"


@pytest.mark.anyio
async def test_rpc_server_concurrent_prompt_routes_to_steer(tmp_path: Path):
    """当已有 prompt 在执行时，携带 streamingBehavior='steer' 的 prompt 自动转为 steer。"""

    class LongRunningLLM:
        def __init__(self):
            self.model = "long-model"

        async def achat_stream(self, *a, **kw):
            for _ in range(5):
                await asyncio.sleep(0.04)
                yield StreamChunk(content="chunk")

    server = RpcServer(llm=LongRunningLLM())
    await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(tmp_path)},
        }
    )

    # 启动第一个 Prompt
    task1 = asyncio.create_task(
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "prompt",
                "params": {"text": "first prompt"},
            }
        )
    )

    # 等待第一任务启动
    await asyncio.sleep(0.02)
    assert server.is_prompt_running is True

    # 发送第二个带有 streamingBehavior='steer' 的 Prompt
    resp2 = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "prompt",
            "params": {"text": "steer prompt", "streamingBehavior": "steer"},
        }
    )
    assert resp2["result"]["status"] == "ok"
    assert resp2["result"].get("action") == "steered"

    # 验证 steer 消息已进入队列
    assert server.agent is not None
    assert server.agent.agent.message_queue.has_steering()

    await task1
    assert server.is_prompt_running is False
