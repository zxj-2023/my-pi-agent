import { test } from "node:test";
import assert from "node:assert/strict";
import { EventTranslator } from "../../dist/bridge/event-translator.js";

test("EventTranslator translates message_update deltas into assistant message blocks", () => {
  const translator = new EventTranslator();

  const startEv = translator.translate({
    type: "message_start",
    message: { role: "assistant", content: "" },
  });
  assert.equal(startEv.type, "message_start");
  assert.equal(startEv.message.role, "assistant");
  assert.deepEqual(startEv.message.content, []);

  // First thinking delta
  const ev1 = translator.translate({
    type: "message_update",
    message: { role: "assistant", content: "" },
    reasoning_delta: "Thinking step 1...",
  });
  assert.equal(ev1.type, "message_update");
  assert.equal(ev1.message.content.length, 1);
  assert.equal(ev1.message.content[0].type, "thinking");
  assert.equal(ev1.message.content[0].thinking, "Thinking step 1...");

  // Additional thinking delta
  const ev1b = translator.translate({
    type: "message_update",
    message: { role: "assistant", content: "" },
    reasoning_delta: " Step 2.",
  });
  assert.equal(ev1b.message.content.length, 1);
  assert.equal(ev1b.message.content[0].thinking, "Thinking step 1... Step 2.");

  // Text delta
  const ev2 = translator.translate({
    type: "message_update",
    message: { role: "assistant", content: "" },
    delta: "Hello world!",
  });
  assert.equal(ev2.message.content.length, 2);
  assert.equal(ev2.message.content[1].type, "text");
  assert.equal(ev2.message.content[1].text, "Hello world!");

  // Additional text delta
  const ev2b = translator.translate({
    type: "message_update",
    message: { role: "assistant", content: "" },
    delta: " How are you?",
  });
  assert.equal(ev2b.message.content.length, 2);
  assert.equal(ev2b.message.content[1].text, "Hello world! How are you?");

  // message_end
  const endEv = translator.translate({
    type: "message_end",
    stop_reason: "stop",
  });
  assert.equal(endEv.type, "message_end");
  assert.equal(endEv.message.stopReason, "stop");
  assert.equal(endEv.message.content.length, 2);
  assert.equal(translator.getCurrentAssistantMessage(), null);
});

test("EventTranslator handles JSON-RPC notification wrapper with method: 'event'", () => {
  const translator = new EventTranslator();

  const ev = translator.translate({
    method: "event",
    params: {
      type: "turn_start",
      iteration: 2,
    },
  });

  assert.equal(ev.type, "turn_start");
  assert.equal(ev.iteration, 2);
});

test("EventTranslator translates agent lifecycle events (agent_start, turn_end, agent_end)", () => {
  const translator = new EventTranslator();

  const startEv = translator.translate({
    type: "agent_start",
    system_prompt: "You are helpful",
    user_input: "Hi",
  });
  assert.equal(startEv.type, "agent_start");
  assert.equal(startEv.systemPrompt, "You are helpful");
  assert.equal(startEv.userInput, "Hi");

  const turnEndEv = translator.translate({ type: "turn_end" });
  assert.equal(turnEndEv.type, "turn_end");

  const endEv = translator.translate({
    type: "agent_end",
    iterations: 3,
    stop_reason: "completed",
  });
  assert.equal(endEv.type, "agent_end");
  assert.equal(endEv.iterations, 3);
  assert.equal(endEv.stopReason, "completed");
});

test("EventTranslator passes usage stats through on turn_end/message_end/agent_end", () => {
  // 回归：Footer 的上下文占用与 ↑↓R/CH%/$ 全部依赖这三个事件里的 usage 与 contextWindow，
  // 翻译层一旦丢弃，状态栏会永远停在初始化时的 0.0%。
  const translator = new EventTranslator();
  const usage = {
    input: 100,
    output: 20,
    cacheRead: 50,
    cacheWrite: 0,
    cacheHitRate: 33.3,
    total: 120,
    contextTokens: 5415,
    cost: 0.04,
  };

  const turnEnd = translator.translate({
    type: "turn_end",
    usage,
    contextWindow: 1048576,
  });
  assert.equal(turnEnd.type, "turn_end");
  assert.deepEqual(turnEnd.usage, usage);
  assert.equal(turnEnd.contextWindow, 1048576);

  translator.translate({
    type: "message_start",
    message: { role: "assistant", content: "" },
  });
  const msgEnd = translator.translate({
    type: "message_end",
    message: { role: "assistant", content: "hi" },
    usage,
    contextWindow: 1048576,
  });
  assert.equal(msgEnd.type, "message_end");
  assert.deepEqual(msgEnd.usage, usage);
  assert.equal(msgEnd.contextWindow, 1048576);

  const agentEnd = translator.translate({
    type: "agent_end",
    iterations: 1,
    stop_reason: "end_turn",
    usage,
    contextWindow: 1048576,
  });
  assert.equal(agentEnd.type, "agent_end");
  assert.deepEqual(agentEnd.usage, usage);
  assert.equal(agentEnd.contextWindow, 1048576);
});

test("EventTranslator omits usage stats when the kernel sends none", () => {
  const translator = new EventTranslator();
  const turnEnd = translator.translate({ type: "turn_end" });
  assert.equal(turnEnd.usage, undefined);
  assert.equal(turnEnd.contextWindow, undefined);
});

test("EventTranslator handles tool execution start, update, and end", () => {
  const translator = new EventTranslator();

  // Start assistant message first
  translator.translate({
    type: "message_start",
    message: { role: "assistant" },
  });

  // Tool execution start
  const toolStart = translator.translate({
    type: "tool_execution_start",
    toolCallId: "call-1",
    toolName: "read",
    args: { path: "package.json" },
  });
  assert.equal(toolStart.type, "tool_execution_start");
  assert.equal(toolStart.toolCallId, "call-1");
  assert.equal(toolStart.toolName, "read");
  assert.deepEqual(toolStart.args, { path: "package.json" });

  // Tool call appended to current assistant message
  const curr = translator.getCurrentAssistantMessage();
  assert.ok(curr);
  assert.equal(curr.content.length, 1);
  assert.equal(curr.content[0].type, "toolCall");
  assert.equal(curr.content[0].id, "call-1");

  // Tool execution update
  const toolUpdate = translator.translate({
    type: "tool_execution_update",
    toolCallId: "call-1",
    toolName: "read",
    partialResult: "Reading...",
  });
  assert.equal(toolUpdate.type, "tool_execution_update");
  assert.equal(toolUpdate.partialResult, "Reading...");

  // Tool execution end
  const toolEnd = translator.translate({
    type: "tool_execution_end",
    toolCallId: "call-1",
    toolName: "read",
    result: { status: "ok" },
    isError: false,
  });
  assert.equal(toolEnd.type, "tool_execution_end");
  assert.deepEqual(toolEnd.result, { status: "ok" });
  assert.equal(toolEnd.isError, false);
});

test("EventTranslator translates context_compacted events", () => {
  const translator = new EventTranslator();

  const ev = translator.translate({
    type: "context_compacted",
    tokensBefore: 5000,
    tokensAfter: 2000,
  });
  assert.equal(ev.type, "context_compacted");
  assert.equal(ev.tokensBefore, 5000);
  assert.equal(ev.tokensAfter, 2000);
});

test("EventTranslator returns null for invalid inputs", () => {
  const translator = new EventTranslator();
  assert.equal(translator.translate(null), null);
  assert.equal(translator.translate(undefined), null);
  assert.equal(translator.translate("not an object"), null);
  assert.equal(translator.translate({}), null);
});
