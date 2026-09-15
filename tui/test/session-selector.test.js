import test from "node:test";
import assert from "node:assert/strict";
import { SessionSelectorComponent } from "../dist/components/session-selector.js";

const TEST_SESSIONS = [
  {
    id: "sess-1",
    name: "重构路径",
    path: "/test/sess-1.jsonl",
    cwd: "/test/workspace",
    modified: Math.floor(Date.now() / 1000) - 120, // 2m ago
    message_count: 5,
  },
  {
    id: "sess-2",
    name: "实现MCP支持",
    path: "/test/sess-2.jsonl",
    cwd: "/test/workspace",
    modified: Math.floor(Date.now() / 1000) - 3600, // 1h ago
    message_count: 12,
  },
];

test("SessionSelectorComponent renders session items and metadata", async () => {
  let selected = null;
  let cancelled = false;

  const selector = new SessionSelectorComponent(
    async () => TEST_SESSIONS,
    (s) => {
      selected = s;
    },
    () => {
      cancelled = true;
    },
    undefined,
    "sess-1",
  );

  // Wait for initial load
  await new Promise((r) => setTimeout(r, 20));

  const lines = selector.render(80);
  const text = lines.join("\n");

  assert.ok(text.includes("Resume Session"));
  assert.ok(text.includes("重构路径"));
  assert.ok(text.includes("实现MCP支持"));
  assert.ok(text.includes("5 msgs"));
});

test("SessionSelectorComponent handles selection and Tab scope toggle", async () => {
  let selected = null;
  let cancelled = false;
  let scopeArg = null;

  const selector = new SessionSelectorComponent(
    async (all) => {
      scopeArg = all;
      return TEST_SESSIONS;
    },
    (s) => {
      selected = s;
    },
    () => {
      cancelled = true;
    },
  );

  await new Promise((r) => setTimeout(r, 20));

  // Press down
  selector.handleInput("\x1b[B");

  // Press return
  selector.handleInput("\r");
  assert.ok(selected);
  assert.equal(selected.id, "sess-2");

  // Press Tab to toggle scope
  selector.handleInput("\t");
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(scopeArg, true);
});
