import test from "node:test";
import assert from "node:assert/strict";
import { PythonKernelClient } from "../dist/client.js";
import { KernelBridge } from "../dist/bridge/kernel-bridge.js";

test("PythonKernelClient initializes and receives event notifications", async () => {
  const client = new PythonKernelClient();

  // Mock child process and stdout/stdin
  let written = "";
  const mockChild = {
    stdin: {
      write(data) {
        written += data;
      },
    },
    stdout: null,
    kill() {},
    on() {},
  };

  client.child = mockChild;

  // 1. Test request sending
  const promise = client.sendRequest("initialize", { workspace: "." });
  assert.ok(written.includes('"method":"initialize"'));
  const parsed = JSON.parse(written.trim());
  assert.equal(parsed.id, 1);

  // 2. Simulate response
  client.handleLine(
    JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      result: { status: "ok" },
    }),
  );

  const res = await promise;
  assert.deepEqual(res, { status: "ok" });

  // 3. Test event notification dispatch
  const receivedEvents = [];
  client.on("event", (ev) => {
    receivedEvents.push(ev);
  });

  client.handleLine(
    JSON.stringify({
      jsonrpc: "2.0",
      method: "event",
      params: {
        type: "message_update",
        delta: "chunk text",
        message: { role: "assistant", content: "chunk text" },
      },
    }),
  );

  assert.equal(receivedEvents.length, 1);
  assert.equal(receivedEvents[0].type, "message_update");
  assert.equal(receivedEvents[0].delta, "chunk text");
});

test("KernelBridge preserves image content in client JSON-RPC requests", async () => {
  const client = new PythonKernelClient();
  const requests = [];
  client.child = {
    stdin: {
      write(data) {
        const request = JSON.parse(data);
        requests.push(request);
        queueMicrotask(() => client.handleLine(JSON.stringify({
          jsonrpc: "2.0", id: request.id, result: { status: "ok" },
        })));
      },
    },
  };
  const bridge = new KernelBridge(client);
  const content = [
    { type: "text", text: "before" },
    { type: "image", data: "aGVsbG8=", mime_type: "image/png" },
    { type: "text", text: "after" },
  ];
  await bridge.prompt("before[image]after", { content });
  await bridge.steer(content);
  await bridge.followUp(content);
  assert.deepEqual(requests.map(({ method, params }) => ({ method, params })), [
    { method: "prompt", params: { text: "before[image]after", content } },
    { method: "steer", params: { message: content } },
    { method: "followup", params: { message: content } },
  ]);
});
