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
      if (method === "session_stats") {
        return {
          status: "ok",
          stats: {
            sessionFile: "C:\\test\\session.jsonl",
            sessionId: "s-12345",
            totalMessages: 10,
            userMessages: 4,
            assistantMessages: 4,
            toolCalls: 2,
            toolResults: 2,
            tokens: {
              input: 1000,
              output: 200,
              cacheRead: 500,
              cacheWrite: 0,
              total: 1200,
            },
            cost: 0.05,
          },
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

test("InteractiveMode does not duplicate UserMessageComponent when message_start arrives for normal prompt", async () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  // 用户提交普通 prompt
  await mode.handleUserInput("为什么显示两次");

  // 此时 chatContainer 中应有 1 个 UserMessageComponent
  const userMsgCount1 = mode.chatContainer.children.filter(
    (c) => c.constructor.name === "UserMessageComponent",
  ).length;
  assert.equal(userMsgCount1, 1);

  // 内核发回 message_start(role="user")
  mode.handleAgentEvent({
    type: "message_start",
    message: { role: "user", content: "为什么显示两次" },
  });

  // 绝不能重复追加第二个 UserMessageComponent
  const userMsgCount2 = mode.chatContainer.children.filter(
    (c) => c.constructor.name === "UserMessageComponent",
  ).length;
  assert.equal(userMsgCount2, 1);
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
  assert.ok(calls.some((c) => c.method === "model_switch"));

  await mode.handleSlashCommand("/thinking high");
  assert.equal(mode.currentThinkingLevel, "high");
  assert.ok(calls.some((c) => c.method === "thinking_set"));

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
      content: [{ type: "text", text: "Hello from structured user message" }],
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
  const { bridge, calls } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  mode.isStreaming = true;

  // 运行中普通文本输入自动转为即时转向 (Steering) 并挂载到 Pending 区域
  await mode.handleUserInput("Test input while streaming");
  const rendered = mode.ui.render(80).join("\n");
  assert.ok(rendered.includes("Steering: Test input while streaming"));
  assert.equal(calls.at(-1)?.method, "steer");

  // 运行中管理/破坏性命令被拦截
  await mode.handleUserInput("/new");
  const renderedAfterNew = mode.ui.render(80).join("\n");
  assert.ok(
    renderedAfterNew.includes("当前智能体正在执行中"),
  );
});

test("isEnterKey matches return, enter, carriage returns, and CRLF across platforms", () => {
  assert.equal(isEnterKey("\r"), true);
  assert.equal(isEnterKey("\n"), true);
  assert.equal(isEnterKey("\r\n"), true);
  assert.equal(isEnterKey("a"), false);
  assert.equal(isEnterKey("\t"), false);
  assert.equal(isEnterKey("\x1b"), false);
});

test("InteractiveMode slash commands (/model fuzzy, /thinking validation, /session stats, /copy, /hotkeys, /name)", async () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  // 1. /thinking 有效等级
  await mode.handleSlashCommand("/thinking high");
  assert.equal(mode.currentThinkingLevel, "high");

  // 2. /thinking 无效等级 -> 提示错误，不污染状态
  await mode.handleSlashCommand("/thinking invalid_level");
  assert.equal(mode.currentThinkingLevel, "high");
  const renderedThinkingErr = mode.ui.render(80).join("\n");
  assert.ok(renderedThinkingErr.includes("未知思考等级"));

  // 3. /name 无参查询
  await mode.handleSlashCommand("/name");
  const renderedNameQuery = mode.ui.render(80).join("\n");
  assert.ok(renderedNameQuery.includes("当前会话名称"));

  // 4. /session 无参展示指标看板 (对标 Pi 官方 Session Info)
  await mode.handleSlashCommand("/session");
  const renderedSessionStats = mode.ui.render(80).join("\n");
  assert.ok(renderedSessionStats.includes("Session Info"));
  assert.ok(renderedSessionStats.includes("Messages"));
  assert.ok(renderedSessionStats.includes("Tokens"));

  // 5. /hotkeys 快捷键清单
  await mode.handleSlashCommand("/hotkeys");
  const renderedHotkeys = mode.ui.render(80).join("\n");
  assert.ok(renderedHotkeys.includes("常用键盘快捷键说明清单"));

  // 6. /model 精确匹配
  await mode.handleSlashCommand("/model gpt-4o");
  assert.equal(mode.currentModelName, "gpt-4o");

  // 7. /model 非精确匹配 -> 打开选择器预填搜索词，不直接改名
  await mode.handleSlashCommand("/model deep");
  assert.ok(mode.activeSelectorComponent);
  assert.equal(mode.activeSelectorComponent.searchInput.getValue(), "deep");
  mode.activeSelectorComponent.handleInput("\x1b"); // Esc 取消
  assert.equal(mode.activeSelectorComponent, undefined);

  // 8. /copy 命令 (无消息时报错)
  await mode.handleSlashCommand("/copy");
  const renderedCopy = mode.ui.render(80).join("\n");
  assert.ok(renderedCopy.includes("当前暂无智能体消息可供复制"));
});

test("InteractiveMode handles Shift+Tab (\\x1b[Z) and Ctrl+T to cycle thinking level", async () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge, { model: "claude-3-7-sonnet" });
  await mode.init();
  assert.equal(mode.currentThinkingLevel, "off");

  // 1. claude-3-7-sonnet: off -> minimal
  mode.ui.handleTerminalInput("\x1b[Z");
  assert.equal(mode.currentThinkingLevel, "minimal");

  // 2. minimal -> low
  mode.ui.handleTerminalInput("\x1b[Z");
  assert.equal(mode.currentThinkingLevel, "low");

  // 3. low -> medium
  mode.ui.handleTerminalInput("\x1b[Z");
  assert.equal(mode.currentThinkingLevel, "medium");

  // 4. medium -> high
  mode.ui.handleTerminalInput("\x1b[Z");
  assert.equal(mode.currentThinkingLevel, "high");

  // 5. high -> max
  mode.ui.handleTerminalInput("\x14"); // Ctrl+T
  assert.equal(mode.currentThinkingLevel, "max");

  // 6. max -> off
  mode.ui.handleTerminalInput("\x1b[Z");
  assert.equal(mode.currentThinkingLevel, "off");

  // 7. Non-reasoning model (gpt-4o): cannot cycle, stays off
  mode.currentModelName = "gpt-4o";
  mode.ui.handleTerminalInput("\x1b[Z");
  assert.equal(mode.currentThinkingLevel, "off");
});

test("InteractiveMode renders error notice on message_end and agent_end when model errors", () => {
  const { bridge } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  mode.handleAgentEvent({ type: "agent_start" });
  mode.handleAgentEvent({ type: "turn_start", iteration: 1 });
  mode.handleAgentEvent({
    type: "message_start",
    message: { role: "assistant", content: "" },
  });

  // 模拟模型抛出 401 认证异常结束消息
  const authErrMsg =
    "Error code: 401 - Authentication Fails, Your api key is invalid";
  mode.handleAgentEvent({
    type: "message_end",
    message: {
      role: "assistant",
      content: authErrMsg,
      metadata: { stop_reason: "error" },
    },
  });

  mode.handleAgentEvent({
    type: "agent_end",
    stop_reason: "error",
    final_text: authErrMsg,
  });

  // 验证错误信息已成功加入聊天气泡容器并对用户可见
  const renderedText = mode.chatContainer.children
    .map((c) => (c.render ? c.render(120).join("\n") : ""))
    .join("\n");
  assert.ok(
    renderedText.includes("Authentication Fails"),
    "Chat container must contain the 401 error message",
  );
  assert.ok(
    renderedText.includes("⚠"),
    "Chat container must contain the warning/error icon",
  );
});

test("InteractiveMode /new command resets footer metrics and updates sessionName", async () => {
  const { bridge } = createMockBridge();
  bridge.client = {
    sendRequest: async (method) => {
      if (method === "session_new") {
        return {
          status: "ok",
          session_id: "sid-brand-new-999",
          session_name: "sid-brand-new-999",
          context_window: 1000000,
          usage: {
            input: 0,
            output: 0,
            cacheRead: 0,
            cacheWrite: 0,
            total: 0,
            contextTokens: 0,
            cost: 0,
          },
        };
      }
      return { status: "ok" };
    },
  };

  const mode = new InteractiveMode(bridge);
  // 先设置旧会话的累积指标
  mode.footer.update({
    sessionName: "old-session-2026",
    inputTokens: 158000,
    outputTokens: 4400,
    contextTokens: 23936,
    contextWindow: 128000,
    costUsd: 0.028,
  });

  assert.equal(mode.footer.getSessionName(), "old-session-2026");

  // 执行 /new 命令
  await mode.handleUserInput("/new");

  // 验证 footer 的 sessionName 和各项 token 指标已被彻底重置
  assert.equal(mode.footer.getSessionName(), "sid-brand-new-999");
  assert.equal(mode.footer.getContextWindow(), 1000000);
  const footerLines = mode.footer.render(120).join("\n");
  assert.ok(footerLines.includes("sid-brand-new-999"));
  assert.ok(
    footerLines.includes("0.0%/1.0M") || footerLines.includes("0.0%/1000k"),
  );
  assert.ok(!footerLines.includes("158k"));
  assert.ok(!footerLines.includes("18.7%"));
});

test("InteractiveMode handles Ctrl+Q followup during streaming and idle", async () => {
  const { bridge, calls } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  // 1. 空闲态下触发 handleFollowUp：等同于普通 Prompt 提交
  mode.defaultEditor.setText("Run this now");
  await mode.handleFollowUp();
  assert.equal(mode.defaultEditor.getText(), "");
  assert.equal(calls.at(-1)?.method, "prompt");
  assert.equal(calls.at(-1)?.params?.text, "Run this now");
  assert.equal(mode.pendingFollowupList.length, 0);

  // 2. 运行态下触发 handleFollowUp：进入待发队列并调用 bridge.followUp
  mode.isStreaming = true;
  mode.defaultEditor.setText("Run this next");
  await mode.handleFollowUp();
  assert.equal(mode.defaultEditor.getText(), "");
  assert.equal(calls.at(-1)?.method, "followup");
  assert.equal(calls.at(-1)?.params?.message, "Run this next");
  assert.deepEqual(mode.pendingFollowupList, ["Run this next"]);

  const rendered = mode.ui.render(80).join("\n");
  assert.ok(rendered.includes("Follow-up: Run this next"));
  assert.ok(rendered.includes("Alt+Q to edit all queued messages"));
});

test("InteractiveMode restores all queued messages on restoreQueuedMessagesToEditor and calls clearQueue", async () => {
  const { bridge, calls } = createMockBridge();
  const mode = new InteractiveMode(bridge);

  mode.pendingSteeringList.push("steer message 1");
  mode.pendingFollowupList.push("follow-up message 2");
  mode.updatePendingMessagesDisplay();

  const renderedBefore = mode.ui.render(80).join("\n");
  assert.ok(renderedBefore.includes("Steering: steer message 1"));
  assert.ok(renderedBefore.includes("Follow-up: follow-up message 2"));

  await mode.restoreQueuedMessagesToEditor();

  assert.equal(mode.defaultEditor.getText(), "steer message 1\n\nfollow-up message 2");
  assert.equal(mode.pendingSteeringList.length, 0);
  assert.equal(mode.pendingFollowupList.length, 0);
  assert.ok(calls.some((c) => c.method === "clear_queue"));

  const renderedAfter = mode.ui.render(80).join("\n");
  assert.ok(!renderedAfter.includes("Steering: steer message 1"));
  assert.ok(!renderedAfter.includes("Follow-up: follow-up message 2"));
});

test("InteractiveMode restores queued messages on Escape when streaming", async () => {
  const { bridge, calls } = createMockBridge();
  const mode = new InteractiveMode(bridge);
  await mode.init();

  mode.isStreaming = true;
  mode.pendingSteeringList.push("interrupted steering");
  mode.updatePendingMessagesDisplay();

  // 模拟按下 escape 键中断
  mode.ui.handleTerminalInput("\x1b"); // escape

  assert.equal(mode.isStreaming, false);
  assert.equal(mode.defaultEditor.getText(), "interrupted steering");
  assert.equal(mode.pendingSteeringList.length, 0);
  assert.ok(calls.some((c) => c.method === "abort"));
  assert.ok(calls.some((c) => c.method === "clear_queue"));
});


