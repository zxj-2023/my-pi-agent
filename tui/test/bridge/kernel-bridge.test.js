import { test } from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { KernelBridge } from "../../dist/bridge/kernel-bridge.js";

test("KernelBridge proxies prompt and abort requests to PythonKernelClient", async () => {
  const mockCalls = [];
  const fakeClient = {
    request: async (method, params) => {
      mockCalls.push({ method, params });
      return { status: "ok" };
    },
    on: () => {},
  };
  const bridge = new KernelBridge(fakeClient);

  await bridge.prompt("hello test");
  assert.equal(mockCalls[0].method, "prompt");
  assert.deepEqual(mockCalls[0].params, { text: "hello test" });

  await bridge.prompt("with options", { streamingBehavior: "steer" });
  assert.equal(mockCalls[1].method, "prompt");
  assert.deepEqual(mockCalls[1].params, {
    text: "with options",
    streamingBehavior: "steer",
  });

  await bridge.abort();
  assert.equal(mockCalls[2].method, "abort");
  assert.deepEqual(mockCalls[2].params, {});
});

test("KernelBridge proxies steer and followUp commands", async () => {
  const mockCalls = [];
  const fakeClient = {
    request: async (method, params) => {
      mockCalls.push({ method, params });
      return { status: "ok" };
    },
  };
  const bridge = new KernelBridge(fakeClient);

  await bridge.steer("stop and do this");
  assert.equal(mockCalls[0].method, "steer");
  assert.deepEqual(mockCalls[0].params, { prompt: "stop and do this" });

  await bridge.followUp("next task");
  assert.equal(mockCalls[1].method, "followup");
  assert.deepEqual(mockCalls[1].params, { prompt: "next task" });
});

test("KernelBridge proxies model, session, and tree operations", async () => {
  const mockCalls = [];
  const fakeClient = {
    request: async (method, params) => {
      mockCalls.push({ method, params });
      return { status: "ok" };
    },
  };
  const bridge = new KernelBridge(fakeClient);

  await bridge.listModels();
  assert.equal(mockCalls[0].method, "models_list");
  assert.deepEqual(mockCalls[0].params, {});

  await bridge.switchModel("deepseek-chat", "deepseek");
  assert.equal(mockCalls[1].method, "model_switch");
  assert.deepEqual(mockCalls[1].params, {
    model: "deepseek-chat",
    provider: "deepseek",
  });

  await bridge.listSessions();
  assert.equal(mockCalls[2].method, "session_list");
  assert.deepEqual(mockCalls[2].params, {});

  await bridge.resumeSession("sess_abc");
  assert.equal(mockCalls[3].method, "session_resume");
  assert.deepEqual(mockCalls[3].params, { session_id: "sess_abc" });

  await bridge.getSessionHistory();
  assert.equal(mockCalls[4].method, "session_history");
  assert.deepEqual(mockCalls[4].params, {});

  await bridge.newSession({ title: "fresh" });
  assert.equal(mockCalls[5].method, "session_new");
  assert.deepEqual(mockCalls[5].params, { title: "fresh" });

  await bridge.getTree();
  assert.equal(mockCalls[6].method, "session_tree");
  assert.deepEqual(mockCalls[6].params, {});

  await bridge.branchSession("node_xyz");
  assert.equal(mockCalls[7].method, "session_branch");
  assert.deepEqual(mockCalls[7].params, { node_id: "node_xyz" });
});

test("KernelBridge proxies thinking, auth, and settings operations", async () => {
  const mockCalls = [];
  const fakeClient = {
    request: async (method, params) => {
      mockCalls.push({ method, params });
      return { status: "ok" };
    },
  };
  const bridge = new KernelBridge(fakeClient);

  await bridge.setThinking("high");
  assert.equal(mockCalls[0].method, "thinking_set");
  assert.deepEqual(mockCalls[0].params, { level: "high" });

  await bridge.login("openai", "sk-1234");
  assert.equal(mockCalls[1].method, "login");
  assert.deepEqual(mockCalls[1].params, { provider: "openai", key: "sk-1234" });

  await bridge.logout("openai");
  assert.equal(mockCalls[2].method, "auth_logout");
  assert.deepEqual(mockCalls[2].params, { provider: "openai" });

  await bridge.getSettings();
  assert.equal(mockCalls[3].method, "settings_get");
  assert.deepEqual(mockCalls[3].params, {});

  await bridge.setSetting("autoCompact", true);
  assert.equal(mockCalls[4].method, "settings_set");
  assert.deepEqual(mockCalls[4].params, { key: "autoCompact", value: true });
});

test("KernelBridge supports client with sendRequest instead of request", async () => {
  const mockCalls = [];
  const fakeClient = {
    sendRequest: async (method, params) => {
      mockCalls.push({ method, params });
      return { status: "ok" };
    },
  };
  const bridge = new KernelBridge(fakeClient);

  await bridge.prompt("test sendRequest");
  assert.equal(mockCalls[0].method, "prompt");
  assert.deepEqual(mockCalls[0].params, { text: "test sendRequest" });
});

test("KernelBridge subscribes to client notifications and translates events", () => {
  const emitter = new EventEmitter();
  const receivedEvents = [];

  const fakeTranslator = {
    translate: (ev) => {
      if (ev.type === "raw") {
        return { type: "translated", payload: ev.data };
      }
      return null;
    },
  };

  const bridge = new KernelBridge(emitter, fakeTranslator);
  const unsubscribe = bridge.subscribe((event) => {
    receivedEvents.push(event);
  });

  emitter.emit("event", { type: "raw", data: "first" });
  emitter.emit("notification", { type: "raw", data: "second" });
  emitter.emit("event", { type: "ignored" });

  assert.equal(receivedEvents.length, 2);
  assert.deepEqual(receivedEvents[0], { type: "translated", payload: "first" });
  assert.deepEqual(receivedEvents[1], {
    type: "translated",
    payload: "second",
  });

  unsubscribe();
  emitter.emit("event", { type: "raw", data: "third" });
  assert.equal(receivedEvents.length, 2);
});
