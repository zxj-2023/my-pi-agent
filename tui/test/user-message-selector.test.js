import test from "node:test";
import assert from "node:assert/strict";
import { UserMessageSelectorComponent } from "../dist/components/user-message-selector.js";

const TEST_MESSAGES = [
  { id: "msg-1", text: "第一步：重构路径解析" },
  { id: "msg-2", text: "第二步：编写自动化单元测试" },
  { id: "msg-3", text: "第三步：补齐边界条件校验" },
];

test("UserMessageSelectorComponent renders user message options", () => {
  const selector = new UserMessageSelectorComponent(
    TEST_MESSAGES,
    () => {},
    () => {},
  );

  assert.ok(selector);
  const lines = selector.render(80);
  const text = lines.join("\n");

  assert.ok(text.includes("Fork Session"));
  assert.ok(text.includes("第一步：重构路径解析"));
  assert.ok(text.includes("第三步：补齐边界条件校验"));
  assert.ok(text.includes("Message 1 of 3"));
});

test("UserMessageSelectorComponent handles selection and cancel", () => {
  let selected = null;
  let cancelled = false;

  const selector = new UserMessageSelectorComponent(
    TEST_MESSAGES,
    (msg) => {
      selected = msg;
    },
    () => {
      cancelled = true;
    },
  );

  // Navigate down to msg-2
  selector.handleInput("\x1b[B"); // down
  selector.handleInput("\r"); // enter
  assert.ok(selected);
  assert.equal(selected.id, "msg-2");

  // Escape
  selector.handleInput("\x1b");
  assert.equal(cancelled, true);
});
