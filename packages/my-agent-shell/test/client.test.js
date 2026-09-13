import test from "node:test";
import assert from "node:assert/strict";
import { PythonKernelClient } from "../dist/client.js";

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
  client.handleLine(JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    result: { status: "ok" }
  }));

  const res = await promise;
  assert.deepEqual(res, { status: "ok" });

  // 3. Test event notification dispatch
  const receivedEvents = [];
  client.on("event", (ev) => {
    receivedEvents.push(ev);
  });

  client.handleLine(JSON.stringify({
    jsonrpc: "2.0",
    method: "event",
    params: {
      type: "message_update",
      delta: "chunk text",
      message: { role: "assistant", content: "chunk text" }
    }
  }));

  assert.equal(receivedEvents.length, 1);
  assert.equal(receivedEvents[0].type, "message_update");
  assert.equal(receivedEvents[0].delta, "chunk text");
});
