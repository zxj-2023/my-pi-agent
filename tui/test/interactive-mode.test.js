import { test } from "node:test";
import assert from "node:assert/strict";
import { InteractiveMode } from "../dist/interactive/interactive-mode.js";
import { KernelBridge } from "../dist/bridge/kernel-bridge.js";

function createMockBridge() {
  const listeners = [];
  const calls = [];
  const fakeClient = {
    request: async (method, params) => {
      calls.push({ method, params });
      if (method === "models_list") {
        return { models: [{ id: "gpt-4o", provider: "openai" }, { id: "deepseek-chat", provider: "deepseek" }] };
      }
      if (method === "session_list") {
        return { sessions: [{ session_id: "s-1", title: "Test Session", updated_at: Date.now() }] };
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
  assert.equal(mode.activeToolCalls.size, 0);

  mode.handleAgentEvent({
    type: "message_end",
    message: { role: "assistant", content: [] },
  });
  assert.equal(mode.currentStreamingAssistant, undefined);

  mode.handleAgentEvent({ type: "agent_end" });
  assert.equal(mode.isStreaming, false);
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
