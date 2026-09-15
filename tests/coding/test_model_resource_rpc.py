# 模型切换、思考深度、凭证注销与资源热重载 RPC 单测集 (Task 4)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from my_agent_core.session.entries import ModelChangeEntry, ThinkingLevelChangeEntry
from my_agent_llm.auth.manager import AuthManager
from my_agent_llm.models import Response, StreamChunk
from my_coding_agent.paths import AgentPaths
from my_coding_agent.rpc_server import RpcServer
from my_coding_agent.settings import load_settings


class FakeLLM:
    def __init__(self, model: str = "fake-model"):
        self.model = model

    async def achat(self, *a, **kw):
        return Response(content="fake response", model=self.model)

    async def achat_stream(self, *a, **kw):
        yield StreamChunk(content="fake chunk")


@pytest.mark.anyio
async def test_model_switch_rpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM(model="initial-model"))
    init_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    assert init_resp["result"]["status"] == "ok"
    assert server.agent is not None

    # 1. 切换模型：不持久化 (persist=False)
    resp = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "model_switch",
            "params": {"model": "deepseek-chat", "provider": "deepseek", "persist": False},
        }
    )
    assert resp["result"]["status"] == "ok"
    assert resp["result"]["model"] == "deepseek-chat"
    assert resp["result"]["provider"] == "deepseek"
    assert server.agent.agent.model == "deepseek-chat"

    # 验证 session 写入了 ModelChangeEntry
    last_entry = list(server.agent.session.tree.entries.values())[-1]
    assert isinstance(last_entry, ModelChangeEntry)
    assert last_entry.model == "deepseek-chat"
    assert last_entry.provider == "deepseek"

    # 验证 settings.json 尚未持久化该模型
    paths = AgentPaths(home=custom_home)
    assert not paths.settings_path.exists()

    # 2. 切换模型带 provider/model 格式并持久化 (persist=True)
    resp2 = await server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "model_switch",
            "params": {"model": "openai/gpt-4o", "persist": True},
        }
    )
    assert resp2["result"]["status"] == "ok"
    assert resp2["result"]["model"] == "gpt-4o"
    assert resp2["result"]["provider"] == "openai"
    assert server.agent.agent.model == "gpt-4o"

    # 验证 settings.json 持久化成功
    assert paths.settings_path.exists()
    settings = load_settings(paths)
    assert settings.default_model == "gpt-4o"
    assert settings.default_provider == "openai"

    # 3. 缺少 model 参数时应报错
    err_resp = await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "model_switch", "params": {}})
    assert "error" in err_resp
    assert err_resp["error"]["code"] == -32602


@pytest.mark.anyio
async def test_thinking_set_rpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    assert server.agent is not None

    # 1. 切换思考深度：不持久化 (persist=False)
    resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "thinking_set", "params": {"level": "high", "persist": False}}
    )
    assert resp["result"]["status"] == "ok"
    assert resp["result"]["level"] == "high"

    # 验证 session 写入了 ThinkingLevelChangeEntry
    last_entry = list(server.agent.session.tree.entries.values())[-1]
    assert isinstance(last_entry, ThinkingLevelChangeEntry)
    assert last_entry.thinking_level == "high"

    # settings.json 不应被创建
    paths = AgentPaths(home=custom_home)
    assert not paths.settings_path.exists()

    # 2. 切换思考深度并持久化 (persist=True)
    resp2 = await server.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "thinking_set", "params": {"level": "low", "persist": True}}
    )
    assert resp2["result"]["status"] == "ok"
    assert resp2["result"]["level"] == "low"

    # 验证 settings.json 持久化成功
    assert paths.settings_path.exists()
    settings = load_settings(paths)
    assert settings.default_thinking_level == "low"

    # 3. 非法思考等级应报错
    err_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "thinking_set", "params": {"level": "invalid_level"}}
    )
    assert "error" in err_resp
    assert err_resp["error"]["code"] == -32602


@pytest.mark.anyio
async def test_auth_logout_rpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    paths = AgentPaths(home=custom_home)
    auth_mgr = AuthManager(auth_path=paths.auth_path)
    auth_mgr.set_api_key("deepseek", "sk-deepseek-test")
    auth_mgr.set_api_key("openai", "sk-openai-test")

    # 确认凭据已写入
    assert auth_mgr.get_credential("deepseek") is not None
    assert auth_mgr.get_credential("openai") is not None

    server = RpcServer(llm=FakeLLM(), paths=paths)
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    # 1. 注销 deepseek
    logout_resp = await server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "auth_logout", "params": {"provider": "deepseek"}}
    )
    assert logout_resp["result"]["status"] == "ok"
    assert logout_resp["result"]["provider"] == "deepseek"

    # 重新加载凭证库，验证 deepseek 已被抹除，而 openai 依然保留
    reloaded_auth = AuthManager(auth_path=paths.auth_path)
    assert reloaded_auth.get_credential("deepseek") is None
    assert reloaded_auth.get_credential("openai") is not None

    # 2. 缺少 provider 参数报错
    err_resp = await server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "auth_logout", "params": {}})
    assert "error" in err_resp
    assert err_resp["error"]["code"] == -32602


@pytest.mark.anyio
async def test_resource_reload_rpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    workspace = tmp_path / "work"
    workspace.mkdir()

    # 初始化工作区指令文件
    agents_md = workspace / "AGENTS.md"
    agents_md.write_text("# Initial Guidelines\nPrinciple 1", encoding="utf-8")

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )
    assert server.agent is not None
    assert "Principle 1" in server.agent.agent.messages[0].content

    # 修改 AGENTS.md
    agents_md.write_text("# Updated Guidelines\nPrinciple 2: Verified", encoding="utf-8")

    # 触发 resource_reload
    reload_resp = await server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "resource_reload", "params": {}})
    assert reload_resp["result"]["status"] == "ok"
    assert "summary" in reload_resp["result"]

    # 验证上下文已被热重载刷新
    assert "Principle 2: Verified" in server.agent.agent.messages[0].content


@pytest.mark.anyio
async def test_trust_set_rpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "home"
    monkeypatch.setenv("MY_AGENT_HOME", str(custom_home))
    parent_dir = tmp_path / "parent"
    workspace = parent_dir / "project"
    workspace.mkdir(parents=True)

    server = RpcServer(llm=FakeLLM())
    await server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspace": str(workspace)}}
    )

    trust_file = custom_home / "trust.json"
    assert not trust_file.exists()

    # 1. 信任当前工作区 cwd
    resp1 = await server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "trust_set", "params": {"trusted": True, "parent": False}}
    )
    assert resp1["result"]["status"] == "ok"
    assert resp1["result"]["decision"] == "trusted"
    assert trust_file.exists()

    data = json.loads(trust_file.read_text(encoding="utf-8"))
    assert data.get(str(workspace.resolve())) is True

    # 2. 信任父目录 (parent=True)
    resp2 = await server.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "trust_set", "params": {"trusted": True, "parent": True}}
    )
    assert resp2["result"]["status"] == "ok"
    assert resp2["result"]["decision"] == "trusted"

    data2 = json.loads(trust_file.read_text(encoding="utf-8"))
    assert data2.get(str(parent_dir.resolve())) is True
    assert data2.get(str(workspace.resolve())) is True

    # 3. 撤销当前工作区信任 (trusted=False)
    resp3 = await server.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "trust_set", "params": {"trusted": False, "parent": False}}
    )
    assert resp3["result"]["status"] == "ok"
    assert resp3["result"]["decision"] == "untrusted"

    data3 = json.loads(trust_file.read_text(encoding="utf-8"))
    assert data3.get(str(workspace.resolve())) is False


def test_auth_manager_remove_credential(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    mgr = AuthManager(auth_path=auth_file)
    mgr.set_api_key("deepseek", "key1", profile="default")
    mgr.set_api_key("deepseek", "key2", profile="work")
    mgr.set_api_key("openai", "key3", profile="default")

    # 1. 删除指定 profile
    assert mgr.remove_credential("deepseek", profile="work") is True
    assert mgr.get_credential("deepseek", profile="work") is None
    assert mgr.get_credential("deepseek", profile="default") is not None

    # 2. 删除整个 provider
    assert mgr.remove_credential("deepseek") is True
    assert mgr.get_credential("deepseek") is None
    assert mgr.get_credential("openai") is not None

    # 3. 删除不存在的 provider
    assert mgr.remove_credential("nonexistent") is False
