import test from "node:test";
import assert from "node:assert/strict";
import { TreeSelectorComponent } from "../dist/components/tree-selector.js";

const TEST_NODES = [
  {
    id: "n1",
    parent_id: null,
    role: "user",
    type: "message",
    preview: "帮我重构路径解析模块",
    is_leaf: false,
    is_active: true,
    timestamp: 1710000000,
  },
  {
    id: "n2",
    parent_id: "n1",
    role: "assistant",
    type: "message",
    preview: "已定位到 paths.py，开始分析重构方案",
    is_leaf: false,
    is_active: true,
    timestamp: 1710000010,
  },
  {
    id: "n3",
    parent_id: "n2",
    role: "user",
    type: "message",
    preview: "请顺便把测试用例也补齐",
    is_leaf: true,
    is_active: true,
    timestamp: 1710000020,
  },
  {
    id: "n4",
    parent_id: "n2",
    role: "user",
    type: "message",
    preview: "先不要补测试，先改代码",
    is_leaf: true,
    is_active: false,
    timestamp: 1710000025,
  },
];

test("TreeSelectorComponent renders DAG nodes with branch indicators", async () => {
  const selector = new TreeSelectorComponent(
    async () => TEST_NODES,
    () => {},
    () => {},
    "n3",
  );

  await new Promise((r) => setTimeout(r, 20));

  assert.ok(selector);
  const lines = selector.render(80);
  const text = lines.join("\n");

  assert.ok(text.includes("Session Tree"));
  assert.ok(text.includes("重构路径解析模块"));
  assert.ok(text.includes("[user]"));
  assert.ok(text.includes("[assistant]"));
  assert.ok(text.includes("Enter to switch"));
});

test("TreeSelectorComponent handles navigation and switching branch", async () => {
  let selected = null;

  const selector = new TreeSelectorComponent(
    async () => TEST_NODES,
    (node) => {
      selected = node;
    },
    () => {},
    "n3",
  );

  await new Promise((r) => setTimeout(r, 20));

  // Navigate down from n3 (index 2) to n4 (index 3)
  selector.handleInput("\x1b[B"); // down

  // Press return to switch branch
  selector.handleInput("\r");
  assert.ok(selected);
  assert.equal(selected.id, "n4");
});
