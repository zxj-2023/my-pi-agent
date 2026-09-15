from pathlib import Path
import pytest
from my_coding_agent.paths import AgentPaths
from my_coding_agent.rpc_server import RpcServer
from my_agent_llm.models import Response, StreamChunk


class FakeLLM:
    def __init__(self, model="fake-model"):
        self.model = model

    async def achat(self, messages, *a, **kw):
        last_msg = messages[-1].content if messages else ""
        if "abandoned conversation branch" in last_msg or "summarize" in last_msg.lower():
            return Response(content="Summary: Abandoned exploration of alternative branch.", model=self.model)
        return Response(content="Fake response for prompt", model=self.model)

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="Fake chunk")


@pytest.mark.anyio
async def test_session_tree_nodes(tmp_path: Path, monkeypatch):
    """测试 session_tree 返回拓扑节点列表及其 parent_id、role/type、preview、is_leaf、is_active。"""
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    # 发起首个提问
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "hello world prompt"}}
    )

    # 调用 session_tree
    tree_resp = await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "session_tree", "params": {}})
    assert tree_resp["result"]["status"] == "ok"
    nodes = tree_resp["result"]["nodes"]
    assert len(nodes) == 2  # user message + assistant message

    user_node = nodes[0]
    assistant_node = nodes[1]

    # 验证 user 节点属性
    assert user_node["role"] == "user"
    assert user_node["type"] == "message"
    assert user_node["parent_id"] is None
    assert "hello world prompt" in user_node["preview"]
    assert user_node["is_leaf"] is False
    assert user_node["is_active"] is True

    # 验证 assistant 节点属性
    assert assistant_node["role"] == "assistant"
    assert assistant_node["type"] == "message"
    assert assistant_node["parent_id"] == user_node["id"]
    assert assistant_node["is_leaf"] is True
    assert assistant_node["is_active"] is True

    # 验证 active_leaf_id 与 root_id
    assert tree_resp["result"]["active_leaf_id"] == assistant_node["id"]
    assert tree_resp["result"]["root_id"] == user_node["id"]


@pytest.mark.anyio
async def test_session_branch_user_message(tmp_path: Path, monkeypatch):
    """测试跳转到 user 消息：leaf 重置为该 user 节点的 parent_id，并回填 editor_text。"""
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "prompt one"}})
    await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "prompt", "params": {"text": "prompt two"}})

    tree_resp = await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "session_tree", "params": {}})
    nodes = tree_resp["result"]["nodes"]
    user_nodes = [n for n in nodes if n["role"] == "user"]
    assert len(user_nodes) == 2
    u1, u2 = user_nodes[0], user_nodes[1]
    assistant_nodes = [n for n in nodes if n["role"] == "assistant"]
    a1 = assistant_nodes[0]

    # 跳转到第二个提问 u2：应该将其父节点 a1 设为新的 leaf，并回填 prompt two
    branch_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "session_branch", "params": {"target_id": u2["id"]}}
    )
    assert branch_resp["result"]["status"] == "ok"
    assert branch_resp["result"]["leaf_id"] == a1["id"]
    assert branch_resp["result"]["editor_text"] == "prompt two"
    assert server.agent is not None
    assert server.agent.session.tree.current_id == a1["id"]

    # 再次查询树，a1 此时应当成为当前分支 active leaf，而 u2 变为非活跃
    tree_resp2 = await server.handle_request({"jsonrpc": "2.0", "id": 6, "method": "session_tree", "params": {}})
    assert tree_resp2["result"]["active_leaf_id"] == a1["id"]
    node_map = {n["id"]: n for n in tree_resp2["result"]["nodes"]}
    assert node_map[u2["id"]]["is_active"] is False
    assert node_map[a1["id"]]["is_active"] is True

    # 跳转到首个提问 u1（根节点）：父节点为 None，editor_text 回填 prompt one
    branch_root_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 7, "method": "session_branch", "params": {"target_id": u1["id"]}}
    )
    assert branch_root_resp["result"]["status"] == "ok"
    assert branch_root_resp["result"]["leaf_id"] is None
    assert branch_root_resp["result"]["editor_text"] == "prompt one"
    assert server.agent is not None
    assert server.agent.session.tree.current_id is None


@pytest.mark.anyio
async def test_session_branch_assistant_message(tmp_path: Path, monkeypatch):
    """测试跳转到 assistant 消息：leaf 直接设为 target_id，editor_text 为空。"""
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "first prompt"}})
    await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "prompt", "params": {"text": "second prompt"}})

    tree_resp = await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "session_tree", "params": {}})
    assistant_nodes = [n for n in tree_resp["result"]["nodes"] if n["role"] == "assistant"]
    a1 = assistant_nodes[0]

    branch_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "session_branch", "params": {"target_id": a1["id"]}}
    )
    assert branch_resp["result"]["status"] == "ok"
    assert branch_resp["result"]["leaf_id"] == a1["id"]
    assert branch_resp["result"]["editor_text"] == ""
    assert server.agent is not None
    assert server.agent.session.tree.current_id == a1["id"]


@pytest.mark.anyio
async def test_session_branch_with_summary(tmp_path: Path, monkeypatch):
    """测试带 summarize=True 的分支跳转：生成 branch_summary entry 并将其设为新 leaf。"""
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "turn 1"}})
    await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "prompt", "params": {"text": "turn 2"}})

    tree_resp = await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "session_tree", "params": {}})
    assistant_nodes = [n for n in tree_resp["result"]["nodes"] if n["role"] == "assistant"]
    a1 = assistant_nodes[0]

    # 从 turn 2 跳转回 a1 并请求分支摘要
    branch_resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "session_branch",
            "params": {"target_id": a1["id"], "summarize": True},
        }
    )
    assert branch_resp["result"]["status"] == "ok"
    assert branch_resp["result"]["branch_summary"] != ""
    summary_leaf_id = branch_resp["result"]["leaf_id"]
    assert summary_leaf_id != a1["id"]
    assert server.agent is not None
    assert server.agent.session.tree.current_id == summary_leaf_id

    # 验证 tree 中存在 branch_summary 节点
    tree_resp2 = await server.handle_request({"jsonrpc": "2.0", "id": 6, "method": "session_tree", "params": {}})
    summary_nodes = [n for n in tree_resp2["result"]["nodes"] if n.get("type") == "branch_summary"]
    assert len(summary_nodes) == 1
    assert summary_nodes[0]["id"] == summary_leaf_id
    assert summary_nodes[0]["parent_id"] == a1["id"]
    assert summary_nodes[0]["is_active"] is True


@pytest.mark.anyio
async def test_session_fork_rpc(tmp_path: Path, monkeypatch):
    """测试 session_fork：从历史提问分叉开辟新会话文件，绑定 agent，回填 prompt_text。"""
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "first prompt"}})
    await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "prompt", "params": {"text": "second prompt"}})

    assert server.agent is not None
    original_session_id = server.agent.session.id
    tree_resp = await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "session_tree", "params": {}})
    user_nodes = [n for n in tree_resp["result"]["nodes"] if n["role"] == "user"]
    u2 = user_nodes[1]

    # 对第二个 user prompt 进行 fork
    fork_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "session_fork", "params": {"entry_id": u2["id"]}}
    )
    assert fork_resp["result"]["status"] == "ok"
    new_session_id = fork_resp["result"]["new_session_id"]
    assert new_session_id != original_session_id
    assert fork_resp["result"]["prompt_text"] == "second prompt"
    assert "session_file" in fork_resp["result"]

    # 验证 agent 绑定到新 session
    assert server.agent is not None
    assert server.agent.session.id == new_session_id
    paths = AgentPaths()
    proj_dir = paths.project_session_dir(workspace)
    assert (proj_dir / f"{new_session_id}.jsonl").is_file()

    # 验证新 session 包含 u2 之前的历史（即 u1 与 a1），不包含 u2 及之后
    tree_fork = await server.handle_request({"jsonrpc": "2.0", "id": 6, "method": "session_tree", "params": {}})
    fork_nodes = tree_fork["result"]["nodes"]
    assert len(fork_nodes) == 2
    fork_roles = [n["role"] for n in fork_nodes]
    assert fork_roles == ["user", "assistant"]
    assert fork_nodes[0]["preview"] == "first prompt"


@pytest.mark.anyio
async def test_session_clone_rpc(tmp_path: Path, monkeypatch):
    """测试 session_clone：将当前活跃分支完整复制到新会话文件，并绑定 agent。"""
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompt", "params": {"text": "first prompt"}})

    assert server.agent is not None
    original_session_id = server.agent.session.id

    clone_resp = await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "session_clone", "params": {}})
    assert clone_resp["result"]["status"] == "ok"
    new_session_id = clone_resp["result"]["new_session_id"]
    assert new_session_id != original_session_id
    assert "session_file" in clone_resp["result"]

    # 验证 agent 绑定到克隆的 session
    assert server.agent is not None
    assert server.agent.session.id == new_session_id
    paths = AgentPaths()
    proj_dir = paths.project_session_dir(workspace)
    assert (proj_dir / f"{new_session_id}.jsonl").is_file()

    # 验证新 session 完整保留了当前活跃路径
    tree_clone = await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "session_tree", "params": {}})
    clone_nodes = tree_clone["result"]["nodes"]
    assert len(clone_nodes) == 2
    assert clone_nodes[0]["role"] == "user"
    assert clone_nodes[1]["role"] == "assistant"


@pytest.mark.anyio
async def test_session_tree_error_handling(tmp_path: Path, monkeypatch):
    """测试未初始化与非法入参错误处理。"""
    server = RpcServer(llm=FakeLLM())

    # 未初始化调用
    for method in ("session_tree", "session_branch", "session_fork", "session_clone"):
        resp = await server.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}})
        assert "error" in resp
        assert resp["error"]["code"] == -32001

    # 初始化后非法 entry_id
    workspace = tmp_path / "work"
    workspace.mkdir()
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    branch_err = await server.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "session_branch", "params": {"target_id": "nonexistent"}}
    )
    assert "error" in branch_err
    assert branch_err["error"]["code"] == -32004

    fork_err = await server.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "session_fork", "params": {"entry_id": "nonexistent"}}
    )
    assert "error" in fork_err
    assert fork_err["error"]["code"] == -32004
