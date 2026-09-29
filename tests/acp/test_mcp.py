"""ACP mcpServers → MCPServerConfig 翻译层测试。"""

from __future__ import annotations

from acp.schema import AcpMcpServer, EnvVariable, HttpHeader, HttpMcpServer, McpServerStdio, SseMcpServer

from my_acp_agent.mcp import to_mcp_server_config, to_mcp_server_configs


def test_stdio_server_maps_command_args_env():
    server = McpServerStdio(
        name="local",
        command="npx",
        args=["-y", "some-mcp"],
        env=[EnvVariable(name="TOKEN", value="abc")],
    )
    cfg = to_mcp_server_config(server)
    assert cfg is not None
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "some-mcp"]
    assert cfg.env == {"TOKEN": "abc"}


def test_http_server_maps_url_and_headers():
    server = HttpMcpServer(
        name="eshell",
        type="http",
        url="http://127.0.0.1:9999/mcp",
        headers=[HttpHeader(name="Authorization", value="Bearer xyz")],
    )
    cfg = to_mcp_server_config(server)
    assert cfg is not None
    assert cfg.transport == "http"
    assert cfg.url == "http://127.0.0.1:9999/mcp"
    assert cfg.headers == {"Authorization": "Bearer xyz"}


def test_sse_server_maps_to_sse_transport():
    server = SseMcpServer(name="legacy", type="sse", url="http://host/sse", headers=[])
    cfg = to_mcp_server_config(server)
    assert cfg is not None
    assert cfg.transport == "sse"
    assert cfg.url == "http://host/sse"


def test_acp_self_hosted_server_is_skipped():
    """type=acp 表示由 Agent 自身托管，不是外部 server。"""
    server = AcpMcpServer(name="self", type="acp", server_id="x")
    assert to_mcp_server_config(server) is None


def test_batch_translation_skips_unrecognized():
    servers = [
        McpServerStdio(name="a", command="npx", args=[], env=[]),
        AcpMcpServer(name="b", type="acp", server_id="y"),
        HttpMcpServer(name="c", type="http", url="http://h/mcp", headers=[]),
    ]
    configs = to_mcp_server_configs(servers)
    assert [c.name for c in configs] == ["a", "c"]
    assert [c.transport for c in configs] == ["stdio", "http"]


def test_empty_input_returns_empty_list():
    assert to_mcp_server_configs(None) == []
    assert to_mcp_server_configs([]) == []


def test_headers_accept_plain_dicts():
    """兼容未经过 pydantic 校验的裸 dict（如手写 JSON）。"""
    cfg = to_mcp_server_config(
        {"name": "raw", "type": "http", "url": "http://h/mcp", "headers": {"X-K": "v"}}
    )
    assert cfg is not None
    assert cfg.headers == {"X-K": "v"}


def test_plain_dict_stdio_entry():
    cfg = to_mcp_server_config({"name": "raw", "command": "uvx", "args": ["foo"]})
    assert cfg is not None
    assert cfg.transport == "stdio"
    assert cfg.command == "uvx"
    assert cfg.args == ["foo"]
