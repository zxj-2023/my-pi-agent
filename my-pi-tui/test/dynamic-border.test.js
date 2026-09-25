import test from "node:test";
import assert from "node:assert/strict";
import { DynamicBorder } from "../dist/components/dynamic-border.js";

test("DynamicBorder renders horizontal border matching width", () => {
  const border = new DynamicBorder();
  const lines = border.render(60);
  assert.equal(lines.length, 1);
  assert.ok(lines[0].includes("─".repeat(60)));
});

test("DynamicBorder accepts custom color formatter", () => {
  const border = new DynamicBorder((s) => `[CUSTOM]${s}`);
  const lines = border.render(40);
  assert.equal(lines.length, 1);
  assert.ok(lines[0].startsWith("[CUSTOM]"));
});
