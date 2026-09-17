import test from "node:test";
import assert from "node:assert/strict";
import { UserMessageComponent } from "../dist/components/user-message.js";
import { AssistantMessageComponent } from "../dist/components/assistant-message.js";
import { ToolExecutionComponent } from "../dist/components/tool-execution.js";
import { FooterComponent } from "../dist/components/footer.js";
import { CustomEditor } from "../dist/components/custom-editor.js";
import {
  WorkingStatusIndicator,
  CompactionStatusIndicator,
} from "../dist/components/status-indicator.js";

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

  // 验证运行中流式增量输出展示且未提前终止
  tool.updatePartialResult("Step 1: processing...\nStep 2: analyzing...");
  assert.strictEqual(tool.finished, false);
  lines = tool.render(80);
  assert.ok(lines.some((l) => l.includes("Step 2: analyzing...")));

  tool.updateResult("const x = 1;", false, 1.2);
  assert.strictEqual(tool.finished, true);
  lines = tool.render(80);
  assert.ok(lines.some((l) => l.includes("1.2s")));
  assert.ok(lines.some((l) => l.includes("const x = 1;")));
  tool.dispose();
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
  assert.ok(lines.some((l) => l.includes("14k")));
});

test("CustomEditor renders embedded WorkingStatusIndicator and CompactionStatusIndicator in top border", () => {
  const fakeTui = { requestRender: () => {} };
  const editor = new CustomEditor(fakeTui, {
    borderColor: (s) => s,
  });

  // 1. 无 indicator 时渲染普通边框
  const normalBorder = editor.renderTopBorder(80, 0);
  assert.ok(normalBorder.includes("─"));
  assert.ok(!normalBorder.includes("Working"));

  // 2. 嵌入 WorkingStatusIndicator
  const working = new WorkingStatusIndicator(fakeTui, "Working");
  editor.setWorkingStatusIndicator(working);
  const workingBorder = editor.renderTopBorder(80, 0);
  assert.ok(workingBorder.includes("Working"));
  working.dispose();

  // 3. 嵌入 CompactionStatusIndicator (验证不会报 renderInBorder is not a function)
  const compacting = new CompactionStatusIndicator(fakeTui, "manual");
  editor.setWorkingStatusIndicator(compacting);
  const compactBorder = editor.renderTopBorder(80, 0);
  assert.ok(compactBorder.includes("Compacting"));
  compacting.dispose();

  // 4. 清除后恢复普通边框
  editor.setWorkingStatusIndicator(undefined);
  const clearedBorder = editor.renderTopBorder(80, 0);
  assert.ok(!clearedBorder.includes("Compacting"));
});
