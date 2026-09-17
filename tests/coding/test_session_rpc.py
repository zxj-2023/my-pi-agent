from pathlib import Path
import pytest
from my_coding_agent.rpc_server import RpcServer
from my_agent_llm.models import Response, StreamChunk


class FakeLLM:
    def __init__(self, model="fake-model"):
        self.model = model

    async def achat(self, *a, **kw):
        return Response(content="Summary: All tasks done.", model=self.model)

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="ok")


@pytest.mark.anyio
async def test_session_lifecycle_rpc(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    init_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    assert init_resp["result"]["status"] == "ok"

    # 1. 初始执行一个 Prompt 生成消息
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "hello"}})

    assert server.agent is not None
    # 获取初始 session_id
    initial_session_id = server.agent.session.id

    # 2. session_name
    name_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "session_name", "params": {"name": "测试会话一"}}
    )
    assert name_resp["result"]["status"] == "ok"
    assert name_resp["result"]["name"] == "测试会话一"

    # 3. session_list
    list_resp = await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "session_list", "params": {}})
    assert list_resp["result"]["status"] == "ok"
    assert len(list_resp["result"]["sessions"]) >= 1
    assert list_resp["result"]["sessions"][0]["name"] == "测试会话一"

    # 4. session_compact
    compact_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "session_compact", "params": {"instructions": "重点关注总结"}}
    )
    assert compact_resp["result"]["status"] == "ok"
    assert "tokens_before" in compact_resp["result"]
    assert "tokens_after" in compact_resp["result"]
    assert "summary" in compact_resp["result"]

    # 模拟旧会话累积使用量
    server.session_usage["input"] = 158000
    server.session_usage["contextTokens"] = 23936

    # 5. session_new
    new_resp = await server.handle_request({"jsonrpc": "2.0", "id": 6, "method": "session_new", "params": {}})
    assert new_resp["result"]["status"] == "ok"
    assert new_resp["result"]["session_id"] != ""
    assert new_resp["result"]["session_id"] != initial_session_id
    assert new_resp["result"]["session_name"] == new_resp["result"]["session_id"]
    assert new_resp["result"]["usage"]["input"] == 0
    assert new_resp["result"]["usage"]["contextTokens"] == 0
    assert server.session_usage["input"] == 0
    assert server.session_usage["contextTokens"] == 0
    assert new_resp["result"]["context_window"] > 0

    # 在新 session 中产生交互并重命名
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 7, "method": "prompt", "params": {"text": "world in new session"}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 8, "method": "session_name", "params": {"name": "测试会话二"}})

    # 再次 session_list，应有 2 个会话
    list_resp2 = await server.handle_request({"jsonrpc": "2.0", "id": 9, "method": "session_list", "params": {}})
    assert list_resp2["result"]["status"] == "ok"
    assert len(list_resp2["result"]["sessions"]) >= 2
    names = [s["name"] for s in list_resp2["result"]["sessions"]]
    assert "测试会话一" in names
    assert "测试会话二" in names

    # 6. session_resume: 恢复到初始会话一
    resume_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 10, "method": "session_resume", "params": {"session_id": initial_session_id}}
    )
    assert resume_resp["result"]["status"] == "ok"
    assert resume_resp["result"]["session_id"] == initial_session_id
    assert len(resume_resp["result"]["messages"]) >= 1
    # 验证恢复后，当前 agent session 即初始 session
    assert server.agent is not None
    assert server.agent.session.id == initial_session_id


@pytest.mark.anyio
async def test_session_resume_not_found(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    resume_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "session_resume", "params": {"session_id": "nonexistent-id"}}
    )
    assert "error" in resume_resp
    assert resume_resp["error"]["code"] == -32004


@pytest.mark.anyio
async def test_session_rpc_uninitialized():
    server = RpcServer(llm=FakeLLM())
    for method in ("session_name", "session_compact", "session_new"):
        resp = await server.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}})
        assert "error" in resp
        assert resp["error"]["code"] == -32001


@pytest.mark.anyio
async def test_session_name_validation(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    resp = await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "session_name", "params": {"name": "   "}})
    assert "error" in resp
    assert resp["error"]["code"] == -32602


@pytest.mark.anyio
async def test_session_resume_by_prefix(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "first session"}})
    assert server.agent is not None
    orig_id = server.agent.session.id

    # 创建新会话
    await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "session_new", "params": {}})
    assert server.agent.session.id != orig_id

    # 通过前缀恢复原会话
    prefix = orig_id[:8]
    resume_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "session_resume", "params": {"session_id": prefix}}
    )
    assert resume_resp["result"]["status"] == "ok"
    assert resume_resp["result"]["session_id"] == orig_id
    assert server.agent.session.id == orig_id


@pytest.mark.anyio
async def test_session_list_all_projects(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))

    ws1 = tmp_path / "project_a"
    ws1.mkdir()
    ws2 = tmp_path / "project_b"
    ws2.mkdir()

    # Project A
    server1 = RpcServer(llm=FakeLLM())
    await server1.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(ws1)}})
    await server1.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "hello in A"}})
    await server1.handle_request({"jsonrpc": "2.0", "id": 3, "method": "session_name", "params": {"name": "Session A"}})

    # Project B
    server2 = RpcServer(llm=FakeLLM())
    await server2.handle_request({"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {"workspace": str(ws2)}})
    await server2.handle_request({"jsonrpc": "2.0", "id": 5, "method": "prompt", "params": {"text": "hello in B"}})
    await server2.handle_request({"jsonrpc": "2.0", "id": 6, "method": "session_name", "params": {"name": "Session B"}})

    # List in project B without all_projects: only Project B session
    list_local = await server2.handle_request(
        {"jsonrpc": "2.0", "id": 7, "method": "session_list", "params": {"all_projects": False}}
    )
    assert list_local["result"]["status"] == "ok"
    local_names = [s["name"] for s in list_local["result"]["sessions"]]
    assert "Session B" in local_names
    assert "Session A" not in local_names

    # List with all_projects: both Project A and B sessions
    list_all = await server2.handle_request(
        {"jsonrpc": "2.0", "id": 8, "method": "session_list", "params": {"all_projects": True}}
    )
    assert list_all["result"]["status"] == "ok"
    all_names = [s["name"] for s in list_all["result"]["sessions"]]
    assert "Session A" in all_names
    assert "Session B" in all_names


@pytest.mark.anyio
async def test_session_resume_missing_param(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    resp = await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "session_resume", "params": {}})
    assert "error" in resp
    assert resp["error"]["code"] == -32602


@pytest.mark.anyio
async def test_session_resume_ambiguous(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    # 制造两个以相同前缀开头的 session
    s_dir = server.paths.project_session_dir(workspace) if server.paths else (custom_home / "sessions" / "test")
    s_dir.mkdir(parents=True, exist_ok=True)
    f1 = s_dir / "abc111.jsonl"
    f2 = s_dir / "abc222.jsonl"
    f1.write_text(
        '{"type": "session_info", "id": "abc111", "cwd": "' + str(workspace).replace("\\", "\\\\") + '"}\n',
        encoding="utf-8",
    )
    f2.write_text(
        '{"type": "session_info", "id": "abc222", "cwd": "' + str(workspace).replace("\\", "\\\\") + '"}\n',
        encoding="utf-8",
    )

    resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "session_resume", "params": {"session_id": "abc"}}
    )
    assert "error" in resp
    assert resp["error"]["code"] == -32003


@pytest.mark.anyio
async def test_session_deferred_disk_write(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    # 检查尚未生成任何 .jsonl 物理文件
    paths = server.paths
    assert paths is not None
    s_dir = paths.project_session_dir(workspace)
    assert list(s_dir.glob("*.jsonl")) == []

    # 执行 session_new，也应当延期落盘，绝不生成空文件
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "session_new", "params": {}})
    assert list(s_dir.glob("*.jsonl")) == []

    # 工作区根目录下也绝对零污染
    assert list(workspace.glob("*.jsonl")) == []


@pytest.mark.anyio
async def test_session_resume_cross_project(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    ws_a = tmp_path / "project_a"
    ws_a.mkdir()
    ws_b = tmp_path / "project_b"
    ws_b.mkdir()

    # Project A 中生成一条 session
    server_a = RpcServer(llm=FakeLLM())
    await server_a.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(ws_a)}}
    )
    await server_a.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "session in project a"}}
    )
    assert server_a.agent is not None
    sid_a = server_a.agent.session.id

    # 在 Project B 中通过 Project A 的 session_id 跨项目 resume
    server_b = RpcServer(llm=FakeLLM())
    await server_b.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {"workspace": str(ws_b)}}
    )
    resume_resp = await server_b.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "session_resume", "params": {"session_id": sid_a}}
    )
    assert resume_resp["result"]["status"] == "ok"
    assert resume_resp["result"]["session_id"] == sid_a
    assert resume_resp["result"]["cwd"] == str(ws_a)
    assert "messages" in resume_resp["result"]
    assert len(resume_resp["result"]["messages"]) >= 1


@pytest.mark.anyio
async def test_session_history_and_metadata_serialization(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "hello test"}})

    hist_resp = await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "session_history", "params": {}})
    assert hist_resp["result"]["status"] == "ok"
    assert server.agent is not None
    assert server.agent is not None
    assert hist_resp["result"]["session_id"] == server.agent.session.id
    msgs = hist_resp["result"]["messages"]
    assert len(msgs) >= 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello test"
    assert msgs[1]["role"] == "assistant"
    assert "metadata" in msgs[1]


@pytest.mark.anyio
async def test_initialize_loads_existing_session_history(tmp_path: Path, monkeypatch):
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    # 1. 启动会话并产生交互
    server1 = RpcServer(llm=FakeLLM())
    await server1.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server1.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "initial message"}})

    # 2. 显式续接（模拟 pi -c / continue_session=True）
    server2 = RpcServer(llm=FakeLLM())
    init_resp = await server2.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "initialize",
            "params": {"workspace": str(workspace), "continue_session": True},
        }
    )
    assert init_resp["result"]["status"] == "ok"
    assert "messages" in init_resp["result"]
    assert len(init_resp["result"]["messages"]) >= 2
    assert init_resp["result"]["messages"][0]["content"] == "initial message"


@pytest.mark.anyio
async def test_session_stats_rpc(tmp_path: Path, monkeypatch):
    """测试 session_stats RPC 对齐 Pi 原厂数据结构 (Message/Token/Cost 统计)。"""
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "hello stats"}})

    stats_resp = await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "session_stats", "params": {}})
    assert stats_resp["result"]["status"] == "ok"
    assert server.agent is not None
    assert server.agent.session is not None
    stats = stats_resp["result"]["stats"]
    assert stats["sessionId"] == server.agent.session.id
    assert stats["totalMessages"] >= 2
    assert stats["userMessages"] >= 1
    assert stats["assistantMessages"] >= 1
    assert "tokens" in stats
    assert "input" in stats["tokens"]
    assert "output" in stats["tokens"]
    assert "cacheRead" in stats["tokens"]
    assert "cost" in stats
    assert "usageBreakdown" in stats


@pytest.mark.anyio
async def test_initialize_default_new_session_vs_continue(tmp_path: Path, monkeypatch):
    """验证严格对标 Pi 原厂：默认启动为全新会话，仅当显式传 continue_session=True 时才续接历史。"""
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    # 1. Server 1 默认启动并交互
    server1 = RpcServer(llm=FakeLLM())
    init1 = await server1.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    assert init1["result"]["status"] == "ok"
    assert len(init1["result"]["messages"]) == 0
    sid1 = init1["result"]["session_id"]
    await server1.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "session 1 msg"}})

    # 2. Server 2 再次默认启动（未指定 continue）：必须开启全新的空白会话，绝不复用 Server 1
    server2 = RpcServer(llm=FakeLLM())
    init2 = await server2.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    assert init2["result"]["status"] == "ok"
    assert len(init2["result"]["messages"]) == 0
    sid2 = init2["result"]["session_id"]
    assert sid2 != sid1

    # 3. Server 3 显式指定 continue_session=True：成功续接 Server 1
    server3 = RpcServer(llm=FakeLLM())
    init3 = await server3.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"workspace": str(workspace), "continue_session": True},
        }
    )
    assert init3["result"]["status"] == "ok"
    assert init3["result"]["session_id"] == sid1
    assert len(init3["result"]["messages"]) >= 2
