import test from "node:test";
import assert from "node:assert/strict";
import { SettingsSelectorComponent } from "../dist/components/settings-selector.js";

test("SettingsSelectorComponent renders setting options", () => {
  const selector = new SettingsSelectorComponent(
    {
      auto_compact: true,
      default_model: "deepseek-chat",
      default_thinking_level: "medium",
      default_permission_mode: "review",
      theme: "dark",
    },
    () => {},
    () => {},
  );

  assert.ok(selector);
  const lines = selector.render(80);
  const text = lines.join("\n");

  assert.ok(text.includes("Settings"));
  assert.ok(text.includes("Auto Compaction"));
  assert.ok(text.includes("[x]")); // enabled
  assert.ok(text.includes("deepseek-chat"));
  assert.ok(text.includes("medium"));
  assert.ok(text.includes("review"));
});

test("SettingsSelectorComponent handles toggling boolean and cycling options", () => {
  let updatedKey = null;
  let updatedVal = null;
  let closed = false;

  const customDefs = [
    {
      key: "auto_compact",
      label: "Auto Compaction",
      type: "boolean",
      description: "auto compact",
    },
    {
      key: "default_permission_mode",
      label: "Permission Mode",
      type: "cycle",
      options: ["review", "yolo", "strict"],
      description: "mode",
    },
  ];

  const selector = new SettingsSelectorComponent(
    {
      auto_compact: true,
      default_permission_mode: "review",
    },
    (key, val) => {
      updatedKey = key;
      updatedVal = val;
    },
    () => {
      closed = true;
    },
    customDefs,
  );

  // 1. Enter on first item (auto_compact) -> toggles to false
  selector.handleInput("\r");
  assert.equal(updatedKey, "auto_compact");
  assert.equal(updatedVal, false);

  // 2. Press Down to go to default_permission_mode, and Enter to cycle
  selector.handleInput("\x1b[B"); // down
  selector.handleInput("\r"); // cycle review -> yolo
  assert.equal(updatedKey, "default_permission_mode");
  assert.equal(updatedVal, "yolo");

  // 3. Press Escape to close
  selector.handleInput("\x1b");
  assert.equal(closed, true);
});
