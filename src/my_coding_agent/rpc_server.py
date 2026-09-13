from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from dotenv import find_dotenv, load_dotenv

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    ContextCompacted,
    Event,
    MessageEnd,
    MessageStart,
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolsChanged,
    TurnEnd,
    TurnStart,
)
from my_agent_llm import LLM, Config
from my_coding_agent.agent import CodingAgent
from my_coding_agent.permissions import PermissionGate


def serialize_event(event: Event) -> dict[str, Any]:
    """将 Python 内部不可变事实事件序列化为对标 Pi AgentEvent 规范的 JSON 字典。"""
    if isinstance(event, AgentStart):
        return {
            "type": "agent_start",
            "system_prompt": event.system_prompt,
            "user_input": event.user_input,
        }
    elif isinstance(event, AgentEnd):
        return {
            "type": "agent_end",
            "iterations": event.iterations,
            "stop_reason": event.stop_reason,
            "final_text": event.final_text or "",
        }
    elif isinstance(event, TurnStart):
        return {
            "type": "turn_start",
            "iteration": event.iteration,
        }
    elif isinstance(event, TurnEnd):
        return {
            "type": "turn_end",
        }
    elif isinstance(event, MessageStart):
        msg = event.message
        return {
            "type": "message_start",
            "message": {
                "role": msg.role,
                "content": msg.content or "",
            },
        }
    elif isinstance(event, MessageUpdate):
        msg = event.message
        chunk: Any = event.chunk
        delta_text = ""
        delta_thinking = ""
        if chunk is not None:
            delta_text = getattr(chunk, "content", None) or getattr(chunk, "text", "") or ""
            reasoning = getattr(chunk, "reasoning_content", None)
            if not reasoning and getattr(chunk, "metadata", None) and isinstance(chunk.metadata, dict):
                reasoning = chunk.metadata.get("reasoning_content")
            delta_thinking = str(reasoning) if reasoning else ""

        return {
            "type": "message_update",
            "message": {
                "role": msg.role,
                "content": msg.content or "",
            },
            "delta": delta_text,
            "reasoning_delta": delta_thinking,
        }
    elif isinstance(event, MessageEnd):
        msg = event.message
        return {
            "type": "message_end",
            "message": {
                "role": msg.role,
                "content": msg.content or "",
            },
        }
    elif isinstance(event, ToolExecutionStart):
        return {
            "type": "tool_execution_start",
            "toolCallId": event.tool_call_id,
            "toolName": event.tool_name,
            "args": event.args,
        }
    elif isinstance(event, ToolExecutionUpdate):
        return {
            "type": "tool_execution_update",
            "toolCallId": event.tool_call_id,
            "toolName": event.tool_name,
            "partialResult": event.partial_result,
        }
    elif isinstance(event, ToolExecutionEnd):
        return {
            "type": "tool_execution_end",
            "toolCallId": event.tool_call_id,
            "toolName": event.tool_name,
            "result": event.result,
            "isError": event.is_error,
        }
    elif isinstance(event, ContextCompacted):
        return {
            "type": "context_compacted",
            "tokensBefore": event.tokens_before,
            "tokensAfter": event.tokens_after,
            "summarizedCount": event.summarized_count,
        }
    elif isinstance(event, ToolsChanged):
        return {
            "type": "tools_changed",
            "action": event.action,
            "name": event.name,
        }

    return {"type": type(event).__name__.lower()}


class RpcServer:
    """标准 stdio JSON-RPC 2.0 服务端，将 Python 无头 CodingAgent 连接至 Node 前端。"""

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        agent: CodingAgent | None = None,
        llm: Any | None = None,
    ):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.agent = agent
        self.llm = llm
        self.is_shutting_down = False

    def emit_json(self, payload: dict[str, Any]) -> None:
        """向 stdout 写入单行 JSON 并强制 flush。"""
        line = json.dumps(payload, ensure_ascii=False)
        self.stdout.write(line + "\n")
        self.stdout.flush()

    def send_notification(self, method: str, params: dict[str, Any]) -> None:
        """向客户端发送单向通知 (如 event)。"""
        self.emit_json(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def send_response(
        self,
        req_id: int | str,
        result: Any = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造并发送 RPC 响应，同时返回字典便于单元测试断言。"""
        resp: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
        }
        if error is not None:
            resp["error"] = error
        else:
            resp["result"] = result or {}

        self.emit_json(resp)
        return resp

    async def handle_request(self, req: dict[str, Any]) -> dict[str, Any]:
        """分发并处理单个 RPC 请求。"""
        req_id = req.get("id", 0)
        method = req.get("method", "")
        params = req.get("params", {})

        try:
            if method == "initialize":
                workspace_path = Path(params.get("workspace", ".")).resolve()
                model_name = params.get("model")
                mode = params.get("mode", "review")

                llm = self.llm
                if llm is None:
                    provider = None
                    if model_name and "/" in model_name:
                        provider, model_name = model_name.split("/", 1)
                    elif model_name and (model_name.startswith("gemini-") or "flash" in model_name or "pro" in model_name):
                        provider = "antigravity"
                    elif model_name and "deepseek" in model_name:
                        provider = "deepseek"
                    elif model_name and ("gpt-" in model_name or "o1" in model_name or "o3" in model_name):
                        provider = "openai"

                    if not provider:
                        from my_agent_llm.auth.antigravity import AntigravityAuthResolver

                        if AntigravityAuthResolver().resolve_credentials() is not None:
                            provider = "antigravity"
                            model_name = model_name or "gemini-3.8-flash"
                        elif os.environ.get("DEEPSEEK_API_KEY"):
                            provider = "deepseek"
                            model_name = model_name or "deepseek-chat"
                        else:
                            provider = "openai"
                            model_name = model_name or "gpt-4o"

                    api_key = os.environ.get(f"{provider.upper()}_API_KEY") or os.environ.get("OPENAI_API_KEY")
                    base_url = os.environ.get(f"{provider.upper()}_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
                    try:
                        llm = LLM(config=Config(provider=provider, model=model_name, api_key=api_key, base_url=base_url))
                    except Exception:
                        llm = None

                session_file = workspace_path / ".my_agent_core" / "sessions" / "default.jsonl"
                session_file.parent.mkdir(parents=True, exist_ok=True)

                gate = PermissionGate(mode=mode) if mode else None
                self.agent = CodingAgent(
                    workspace=workspace_path,
                    llm=llm,
                    session=session_file,
                    permission_gate=gate,
                )

                actual_model = getattr(getattr(self.agent.agent.llm, "config", None), "model", "default")
                return self.send_response(
                    req_id,
                    result={
                        "status": "ok",
                        "workspace": str(workspace_path),
                        "model": actual_model,
                    },
                )

            elif method == "prompt":
                if not self.agent:
                    return self.send_response(
                        req_id,
                        error={"code": -32001, "message": "Agent not initialized"},
                    )

                text = params.get("text", "")
                async for event in self.agent.run_stream(text):
                    serialized = serialize_event(event)
                    self.send_notification("event", serialized)

                return self.send_response(req_id, result={"status": "completed"})

            elif method == "steer":
                if not self.agent:
                    return self.send_response(
                        req_id,
                        error={"code": -32001, "message": "Agent not initialized"},
                    )
                msg = params.get("message", "")
                self.agent.steer(msg)
                return self.send_response(req_id, result={"status": "ok"})

            elif method == "followup":
                if not self.agent:
                    return self.send_response(
                        req_id,
                        error={"code": -32001, "message": "Agent not initialized"},
                    )
                msg = params.get("message", "")
                self.agent.follow_up(msg)
                return self.send_response(req_id, result={"status": "ok"})

            elif method == "abort":
                if self.agent:
                    self.agent.abort()
                return self.send_response(req_id, result={"status": "ok"})

            elif method == "shutdown":
                self.is_shutting_down = True
                if self.agent and hasattr(self.agent, "close_mcp"):
                    res = self.agent.close_mcp()
                    if inspect.isawaitable(res):
                        await res
                return self.send_response(req_id, result={"status": "ok"})

            else:
                return self.send_response(
                    req_id,
                    error={"code": -32601, "message": f"Method '{method}' not found"},
                )

        except Exception as e:
            return self.send_response(
                req_id,
                error={"code": -32000, "message": str(e)},
            )

    async def run_forever(self) -> None:
        """主服务循环，以异步方式按行消费 stdin 并处理请求。"""
        while not self.is_shutting_down:
            try:
                line = await asyncio.to_thread(self.stdin.readline)
            except Exception:
                break

            if not line:
                # 管道关闭 (EOF)
                break

            line_str = line.strip()
            if not line_str:
                continue

            try:
                req = json.loads(line_str)
            except json.JSONDecodeError:
                self.send_response(
                    0,
                    error={"code": -32700, "message": "Parse error (invalid JSON)"},
                )
                continue

            await self.handle_request(req)


async def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(description="my-coding-agent stdio JSON-RPC server")
    parser.add_argument("-w", "--workspace", default=".", help="工作区路径")
    parser.add_argument("-m", "--model", default=None, help="LLM 模型标识符")
    args = parser.parse_args()

    server = RpcServer()
    # 如果指定了启动工作区或模型，先行执行预初始化
    if args.workspace != "." or args.model is not None:
        await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {"workspace": args.workspace, "model": args.model},
            }
        )

    await server.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
