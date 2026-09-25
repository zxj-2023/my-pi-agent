import test from "node:test";
import assert from "node:assert/strict";
import { LogoutSelectorComponent } from "../dist/components/logout-selector.js";

const TEST_PROVIDERS = [
  { id: "deepseek", label: "DeepSeek", description: "Stored API Key" },
  { id: "openai", label: "OpenAI", description: "Stored API Key" },
];

test("LogoutSelectorComponent renders providers list", () => {
  const selector = new LogoutSelectorComponent(
    TEST_PROVIDERS,
    () => {},
    () => {},
  );

  assert.ok(selector);
  const lines = selector.render(80);
  const text = lines.join("\n");

  assert.ok(text.includes("Logout"));
  assert.ok(text.includes("DeepSeek"));
  assert.ok(text.includes("OpenAI"));
  assert.ok(text.includes("Enter to remove"));
});

test("LogoutSelectorComponent handles selection and cancel", () => {
  let selected = null;
  let cancelled = false;

  const selector = new LogoutSelectorComponent(
    TEST_PROVIDERS,
    (id) => {
      selected = id;
    },
    () => {
      cancelled = true;
    },
  );

  // Navigate down to openai
  selector.handleInput("\x1b[B"); // down
  selector.handleInput("\r"); // enter
  assert.equal(selected, "openai");

  // Escape
  selector.handleInput("\x1b");
  assert.equal(cancelled, true);
});
