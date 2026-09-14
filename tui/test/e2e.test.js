import test from "node:test";
import assert from "node:assert/strict";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { PythonKernelClient } from "../dist/client.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

test("End-to-End: PythonKernelClient launches real Python rpc_server and runs turn", async (t) => {
  const client = new PythonKernelClient({
    workspace: repoRoot,
  });

  t.after(async () => {
    await client.shutdown();
  });

  // 1. Start client & spawn real Python rpc_server
  await client.start();

  // 2. Send steer
  await client.steer("test steering message");

  // 3. Send followup
  await client.followup("test followup task");

  // 4. Send abort
  await client.abort();

  assert.ok(
    true,
    "Client successfully communicated with Python kernel over stdio JSON-RPC",
  );
});
