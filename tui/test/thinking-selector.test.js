import test from "node:test";
import assert from "node:assert/strict";
import { ThinkingSelectorComponent } from "../dist/components/thinking-selector.js";

test("ThinkingSelectorComponent initializes and renders reasoning levels", () => {
  let selected = "";
  let cancelled = false;

  const selector = new ThinkingSelectorComponent(
    "medium",
    ["off", "minimal", "low", "medium", "high", "max"],
    (lvl) => {
      selected = lvl;
    },
    () => {
      cancelled = true;
    },
    undefined,
    "off",
  );

  assert.ok(selector);
  const lines = selector.render(80);
  const text = lines.join("\n");

  assert.ok(text.includes("Thinking Level"));
  assert.ok(text.includes("Shift+Tab"));
  assert.ok(text.includes("Enter to select"));
  assert.ok(text.includes("✓ medium"));
});

test("ThinkingSelectorComponent handles Enter confirmation and Esc cancellation", () => {
  let selected = "";
  let cancelled = false;

  const selector = new ThinkingSelectorComponent(
    "low",
    ["off", "minimal", "low", "medium", "high", "max"],
    (lvl) => {
      selected = lvl;
    },
    () => {
      cancelled = true;
    },
  );

  // Press return
  selector.handleInput("\r");
  assert.equal(selected, "low");

  // Press escape
  selector.handleInput("\x1b");
  assert.equal(cancelled, true);
});
