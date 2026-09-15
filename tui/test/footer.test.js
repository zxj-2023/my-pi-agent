import test from "node:test";
import assert from "node:assert/strict";
import { FooterComponent } from "../dist/components/footer.js";

test("FooterComponent renders dual lines without emoji clutter", () => {
  const footer = new FooterComponent({
    workspace: "D:/code/my-project",
    gitBranch: "main",
    sessionName: "refactor-auth",
    modelName: "deepseek-flash",
    providerName: "openai",
    thinkingLevel: "off",
    totalTokens: 12500,
    contextWindow: 128000,
  });

  const lines = footer.render(100);
  assert.equal(lines.length, 2, "Footer must render exactly 2 lines");

  // Line 1: 路径与分支
  assert.ok(lines[0].includes("my-project"));
  assert.ok(lines[0].includes("(main)"));
  assert.ok(lines[0].includes("refactor-auth"));
  // 严禁包含破损 emoji
  assert.ok(!lines[0].includes("\u{1f4c1}"));
  assert.ok(!lines[0].includes("\u{1f33f}"));

  // Line 2: 左侧统计 + 右侧模型右对齐
  assert.ok(lines[1].includes("128k"));
  assert.ok(lines[1].includes("deepseek-flash"));
  assert.ok(!lines[1].includes("\u{1f916}"));
  assert.ok(!lines[1].includes("\u{1f4ca}"));
});

test("FooterComponent renders input/output token metrics and cost", () => {
  const footer = new FooterComponent({
    workspace: "D:/code/my-project",
    inputTokens: 3200,
    outputTokens: 450,
    costUsd: 0.006,
    contextWindow: 128000,
    modelName: "deepseek-flash",
  });

  const lines = footer.render(100);
  assert.equal(lines.length, 2);
  assert.ok(lines[1].includes("↑3.2k"));
  assert.ok(lines[1].includes("↓450"));
  assert.ok(lines[1].includes("$0.006"));
});

test("FooterComponent formats thinking level and right-aligns model info", () => {
  const footer = new FooterComponent({
    workspace: "D:/code/my-project",
    providerName: "anthropic",
    modelName: "claude-3-5-sonnet",
    thinkingLevel: "high",
    totalTokens: 1000,
    contextWindow: 200000,
  });

  const lines = footer.render(100);
  assert.equal(lines.length, 2);
  assert.ok(lines[1].includes("(anthropic) claude-3-5-sonnet • high"));
});

test("FooterComponent colorizes context usage percentage according to thresholds", () => {
  const lowFooter = new FooterComponent({
    totalTokens: 10000,
    contextWindow: 100000, // 10% -> dim
  });
  const medFooter = new FooterComponent({
    totalTokens: 75000,
    contextWindow: 100000, // 75% -> warning
  });
  const highFooter = new FooterComponent({
    totalTokens: 95000,
    contextWindow: 100000, // 95% -> error
  });

  const lowLines = lowFooter.render(100);
  const medLines = medFooter.render(100);
  const highLines = highFooter.render(100);

  assert.ok(lowLines[1].includes("10.0%/100k"));
  assert.ok(medLines[1].includes("75.0%/100k"));
  assert.ok(highLines[1].includes("95.0%/100k"));
});

test("FooterComponent updates state dynamically via update()", () => {
  const footer = new FooterComponent({
    workspace: "D:/code/my-project",
    modelName: "initial-model",
  });

  let lines = footer.render(100);
  assert.ok(lines[1].includes("initial-model"));

  footer.update({
    modelName: "updated-model",
    gitBranch: "feature-branch",
    sessionName: "session-42",
    isBusy: true,
    elapsedSeconds: 3.5,
  });

  lines = footer.render(100);
  assert.ok(lines[0].includes("(feature-branch)"));
  assert.ok(lines[0].includes("• session-42"));
  assert.ok(lines[1].includes("updated-model"));
  assert.ok(lines[1].includes("3.5s"));
  assert.ok(lines[1].includes("⠋"));
});

test("FooterComponent truncates gracefully on narrow terminal width", () => {
  const footer = new FooterComponent({
    workspace: "D:/code/very/long/path/to/a/deeply/nested/workspace/directory",
    gitBranch: "feature/super-long-branch-name-that-takes-space",
    sessionName: "extremely-long-session-name-for-testing",
    providerName: "really-long-provider-name",
    modelName: "super-long-model-version-name-extra",
    totalTokens: 50000,
    contextWindow: 128000,
  });

  const lines = footer.render(40);
  assert.equal(lines.length, 2);
  assert.ok(lines[0].length > 0);
  assert.ok(lines[1].length > 0);
});
