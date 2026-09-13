import test from "node:test";
import assert from "node:assert/strict";
import { AgentApp } from "../dist/app.js";

test("AgentApp initializes component tree properly", () => {
  const app = new AgentApp({ workspace: "." });
  assert.ok(app);
});

test("AgentApp handles agent events without throwing", () => {
  const app = new AgentApp({ workspace: "." });

  // 模拟发送消息
  app.handleAgentEvent({
    type: "message_update",
    message: { role: "assistant", content: "hello world" },
    delta: "hello world",
    reasoning_delta: "deep thinking",
  });

  // 模拟工具开始执行
  app.handleAgentEvent({
    type: "tool_execution_start",
    toolCallId: "call_read_1",
    toolName: "read",
    args: { path: "src/app.ts" },
  });

  // 模拟工具更新
  app.handleAgentEvent({
    type: "tool_execution_update",
    toolCallId: "call_read_1",
    toolName: "read",
    args: { path: "src/app.ts" },
    partialResult: null,
  });

  // 模拟工具完成
  app.handleAgentEvent({
    type: "tool_execution_end",
    toolCallId: "call_read_1",
    toolName: "read",
    result: "export class AgentApp {}",
    isError: false,
  });

  // 模拟 agent 结束
  app.handleAgentEvent({
    type: "agent_end",
    iterations: 1,
    stop_reason: "end_turn",
  });

  assert.ok(true);
});

test("AgentApp mounts autocomplete provider with slash commands and @ file references", async () => {
  const app = new AgentApp({ workspace: "." });
  const provider = app.editor.autocompleteProvider;
  assert.ok(provider);

  // 1. 测试 / 斜杠命令联想补全
  const slashSuggestions = await provider.getSuggestions(["/mod"], 0, 4, {
    signal: new AbortController().signal,
  });
  assert.ok(slashSuggestions);
  assert.ok(slashSuggestions.items.some((i) => i.value === "model" || i.label === "model"));

  // 2. 测试 @ 文件路径模糊匹配联想
  const fileSuggestions = await provider.getSuggestions(["@package"], 0, 8, {
    signal: new AbortController().signal,
  });
  assert.ok(fileSuggestions);
  assert.ok(fileSuggestions.items.some((i) => i.value.includes("package.json")));
});

