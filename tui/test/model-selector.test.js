import test from "node:test";
import assert from "node:assert/strict";
import { ModelSelectorComponent } from "../dist/components/model-selector.js";

const TEST_MODELS = [
  {
    id: "deepseek-chat",
    provider: "deepseek",
    name: "DeepSeek V3",
    contextWindow: 64000,
  },
  {
    id: "deepseek-reasoner",
    provider: "deepseek",
    name: "DeepSeek R1",
    contextWindow: 64000,
  },
  { id: "gpt-4o", provider: "openai", name: "GPT-4o", contextWindow: 128000 },
  {
    id: "gpt-4o-mini",
    provider: "openai",
    name: "GPT-4o Mini",
    contextWindow: 128000,
  },
];

test("ModelSelectorComponent renders models list with provider badges", () => {
  const selector = new ModelSelectorComponent(
    "deepseek-chat",
    TEST_MODELS,
    () => {},
    () => {},
    undefined,
    undefined,
    "gpt-4o",
  );

  assert.ok(selector);
  const lines = selector.render(80);
  const text = lines.join("\n");

  assert.ok(text.includes("deepseek-chat"));
  assert.ok(text.includes("[deepseek]"));
  assert.ok(text.includes("Enter to select"));
  assert.ok(
    text.includes(
      "Only showing models from configured providers. Use /login to add providers.",
    ),
  );
  assert.ok(!text.includes("Model Catalog"));
  assert.ok(!text.includes("Configured | ○ All"));
  assert.ok(!text.includes("· 64k"));
  assert.ok(text.includes("✓"));
});

test("ModelSelectorComponent handles navigation, selection and cancellation", () => {
  let selected = null;
  let cancelled = false;

  const selector = new ModelSelectorComponent(
    "deepseek-chat",
    TEST_MODELS,
    (m) => {
      selected = m;
    },
    () => {
      cancelled = true;
    },
  );

  // Press down
  selector.handleInput("\x1b[B");

  // Press return
  selector.handleInput("\r");
  assert.ok(selected);
  assert.equal(selected.id, "deepseek-reasoner");

  // Press escape
  selector.handleInput("\x1b");
  assert.equal(cancelled, true);
});

test("ModelSelectorComponent supports scopedModels and Tab scope toggle", async () => {
  let loaded = false;
  const scoped = [TEST_MODELS[0]];

  const selector = new ModelSelectorComponent(
    "deepseek-chat",
    async () => {
      loaded = true;
      return TEST_MODELS;
    },
    () => {},
    () => {},
    undefined,
    undefined,
    undefined,
    undefined,
    scoped,
  );

  await new Promise((r) => setTimeout(r, 20));
  assert.equal(loaded, true);

  const linesScoped = selector.render(80).join("\n");
  assert.ok(linesScoped.includes("Scope:"));
  assert.ok(linesScoped.includes("scoped"));
  assert.ok(linesScoped.includes("deepseek-chat"));
  assert.ok(!linesScoped.includes("gpt-4o"));

  // Press Tab to switch scope to All
  selector.handleInput("\t");
  const linesAll = selector.render(80).join("\n");
  assert.ok(linesAll.includes("deepseek-chat"));
  assert.ok(linesAll.includes("gpt-4o"));
});
