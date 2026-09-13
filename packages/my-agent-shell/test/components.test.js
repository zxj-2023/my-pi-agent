import test from "node:test";
import assert from "node:assert/strict";
import { UserMessageComponent } from "../dist/components/user-message.js";
import { AssistantMessageComponent } from "../dist/components/assistant-message.js";
import { ToolExecutionComponent } from "../dist/components/tool-execution.js";
import { FooterComponent } from "../dist/components/footer.js";

test("UserMessageComponent renders message inside styled box", () => {
  const comp = new UserMessageComponent("Hello from user");
  const lines = comp.render(80);
  assert.ok(lines.length > 0);
  assert.ok(lines.some((l) => l.includes("Hello from user")));
});

test("AssistantMessageComponent handles thinking deltas and text deltas", () => {
  const comp = new AssistantMessageComponent();
  comp.appendReasoningDelta("I am thinking deeply.");
  comp.appendTextDelta("Here is the final answer.");
  comp.finalize();

  const lines = comp.render(80);
  assert.ok(lines.length > 0);
  assert.ok(lines.some((l) => l.includes("Here is the final answer.")));
  assert.ok(lines.some((l) => l.includes("思考过程")));
});

test("ToolExecutionComponent renders running state and updates to success", () => {
  const tool = new ToolExecutionComponent("read", "call_1", {
    path: "src/main.ts",
  });
  let lines = tool.render(80);
  assert.ok(lines.some((l) => l.includes("read")));
  assert.ok(lines.some((l) => l.includes("path=src/main.ts")));

  tool.updateResult("const x = 1;", false, 1.2);
  lines = tool.render(80);
  assert.ok(lines.some((l) => l.includes("1.2s")));
  assert.ok(lines.some((l) => l.includes("const x = 1;")));
});

test("FooterComponent formats cwd, branch, and tokens properly", () => {
  const footer = new FooterComponent({
    workspace: "/test/my-project",
    gitBranch: "feat/tui",
    modelName: "gemini-3.8-flash",
    tokensUsed: 14200,
    elapsedSeconds: 2.3,
  });

  const lines = footer.render(120);
  assert.ok(lines.length > 0);
  assert.ok(lines.some((l) => l.includes("feat/tui")));
  assert.ok(lines.some((l) => l.includes("gemini-3.8-flash")));
  assert.ok(lines.some((l) => l.includes("14.2k")));
});
