import { test } from "node:test";
import assert from "node:assert/strict";
import { InteractiveMode } from "../dist/interactive/interactive-mode.js";
import { KernelBridge } from "../dist/bridge/kernel-bridge.js";
import { isEnterKey } from "../dist/components/keys.js";

function createMockBridge() {
  const listeners = [];
  const calls = [];
  const fakeClient = {
    request: async (method, params) => {
      calls.push({ method, params });
      if (method === "models_list") {
        return {
          models: [
            { id: "gpt-4o", provider: "openai" },
            { id: "deepseek-chat", provider: "deepseek" },
          ],
        };
      }
      if (method === "session_list") {
        return {
          sessions: [
            {
              session_id: "s-1",
              title: "Test Session",
              updated_at: Date.now(),
            },
          ],
        };
      }
      return { status: "ok" };
    },
    on: () => {},
  };
  const bridge = new KernelBridge(fakeClient);
  bridge.subscribe = (fn) => {
    listeners.push(fn);
    return () => {};
  };
  return { bridge, listeners, calls };
}

test("InteractiveMode initializes component hierarchy and viewport", () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge, {
    workspace: "/test/workspace",
    model: "gpt-4o",
    sessionName: "init-test",
  });

  assert.ok(mode.ui);
  assert.ok(mode.chatContainer);
  assert.ok(mode.footer);
  assert.ok(mode.header);
  assert.equal(mode.currentModelName, "gpt-4o");
});

test("InteractiveMode handles agent streaming events without throwing", () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  mode.handleAgentEvent({ type: "agent_start" });
  assert.equal(mode.isStreaming, true);

  mode.handleAgentEvent({
    type: "message_start",
    message: { role: "assistant", content: [] },
  });
  assert.ok(mode.currentStreamingAssistant);

  mode.handleAgentEvent({
    type: "message_update",
    message: {
      role: "assistant",
      content: [
        { type: "thinking", thinking: "Step 1" },
        { type: "text", text: "Hello!" },
      ],
    },
  });

  mode.handleAgentEvent({
    type: "tool_execution_start",
    toolCallId: "call-1",
    toolName: "read",
    args: { path: "test.py" },
  });
  assert.equal(mode.activeToolCalls.size, 1);

  mode.handleAgentEvent({
    type: "tool_execution_end",
    toolCallId: "call-1",
    result: "content",
    isError: false,
  });
  assert.equal(mode.activeToolCalls.get("call-1")?.finished, true);

  mode.handleAgentEvent({
    type: "message_end",
    message: { role: "assistant", content: [] },
  });
  assert.equal(mode.currentStreamingAssistant, undefined);

  mode.handleAgentEvent({ type: "agent_end" });
  assert.equal(mode.isStreaming, false);
  assert.equal(mode.activeToolCalls.size, 0);
});

test("InteractiveMode showSelector lifecycle handles mount and cleanup", () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  let doneCb;
  mode.showSelector((done) => {
    doneCb = done;
    return {
      component: { render: () => ["selector"] },
      focus: {},
    };
  });

  assert.ok(mode.activeSelectorComponent);
  doneCb();
  assert.equal(mode.activeSelectorComponent, undefined);
});

test("InteractiveMode handles slash commands (/clear, /help, /model, /thinking)", async () => {
  const { bridge, calls } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  await mode.handleSlashCommand("/help");
  await mode.handleSlashCommand("/model gpt-4o");
  assert.equal(mode.currentModelName, "gpt-4o");
  assert.equal(calls[0].method, "model_switch");

  await mode.handleSlashCommand("/thinking high");
  assert.equal(mode.currentThinkingLevel, "high");
  assert.equal(calls[1].method, "thinking_set");

  await mode.handleSlashCommand("/clear");
});

test("InteractiveMode streaming prevents quadratic text and thinking duplication", () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  mode.handleAgentEvent({ type: "agent_start" });
  mode.handleAgentEvent({
    type: "message_start",
    message: { role: "assistant", content: [] },
  });

  // 模拟流式第 1 个 chunk (思考过程)
  mode.handleAgentEvent({
    type: "message_update",
    message: {
      role: "assistant",
      content: [{ type: "thinking", thinking: "Step 1" }],
    },
  });

  // 模拟流式第 2 个 chunk (思考累计完成)
  mode.handleAgentEvent({
    type: "message_update",
    message: {
      role: "assistant",
      content: [{ type: "thinking", thinking: "Step 1 & Step 2" }],
    },
  });

  // 模拟流式第 3 个 chunk (正文开始输出，同时带有累计思考)
  mode.handleAgentEvent({
    type: "message_update",
    message: {
      role: "assistant",
      content: [
        { type: "thinking", thinking: "Step 1 & Step 2" },
        { type: "text", text: "Hello" },
      ],
    },
  });

  // 模拟流式第 4 个 chunk (正文累加)
  mode.handleAgentEvent({
    type: "message_update",
    message: {
      role: "assistant",
      content: [
        { type: "thinking", thinking: "Step 1 & Step 2" },
        { type: "text", text: "Hello world" },
      ],
    },
  });

  const assistant = mode.currentStreamingAssistant;
  assert.ok(assistant);
  assert.equal(assistant["contentText"], "Hello world");
  assert.equal(assistant["thinkingText"], "Step 1 & Step 2");
});

test("InteractiveMode renders session history with structured array content safely", () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  // 用户与助手消息均包含结构化块数组
  mode.renderSessionHistory([
    {
      role: "user",
      content: [
        { type: "text", text: "Hello from structured user message" },
      ],
    },
    {
      role: "assistant",
      content: [
        { type: "thinking", thinking: "Thinking about structured response" },
        { type: "text", text: "Structured assistant response text" },
      ],
    },
  ]);

  const rendered = mode.ui.render(80).join("\n");
  assert.ok(rendered.includes("Hello from structured user message"));
  assert.ok(rendered.includes("Structured assistant response text"));
});

test("InteractiveMode guards against concurrent submission and session commands during streaming", async () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  mode.isStreaming = true;

  // 提交输入时被拦截
  await mode.handleUserInput("Test input while streaming");
  const rendered = mode.ui.render(80).join("\n");
  assert.ok(rendered.includes("当前智能体正在执行中"));

  // 破坏性命令被拦截
  await mode.handleSlashCommand("/new");
  const renderedAfterNew = mode.ui.render(80).join("\n");
  assert.ok(renderedAfterNew.includes("当前智能体正在执行中，无法执行 /new 操作"));
});

test("isEnterKey matches return, enter, carriage returns, and CRLF across platforms", () => {
  assert.equal(isEnterKey("\r"), true);
  assert.equal(isEnterKey("\n"), true);
  assert.equal(isEnterKey("\r\n"), true);
  assert.equal(isEnterKey("a"), false);
  assert.equal(isEnterKey("\t"), false);
  assert.equal(isEnterKey("\x1b"), false);
});
