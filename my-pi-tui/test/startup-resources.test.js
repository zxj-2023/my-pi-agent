import test from "node:test";
import assert from "node:assert/strict";
import { StartupResourcesComponent } from "../dist/components/startup-resources.js";

test("StartupResourcesComponent renders [Context], [Skills], [Prompts], [Extensions] sections", () => {
  const sampleData = {
    context: ["~\\.pi\\agent\\AGENTS.md", "AGENTS.md"],
    skills: ["brainstorming", "systematic-debugging", "test-driven-development"],
    prompts: ["/council", "/review-loop"],
    extensions: ["@juicesharp/rpiv-todo", "pi-lens:dist"],
  };

  const comp = new StartupResourcesComponent(sampleData);
  assert.ok(comp);

  const lines = comp.render(120);
  const text = lines.join("\n");

  assert.ok(text.includes("[Context]"), "Must include [Context] header");
  assert.ok(text.includes("~\\.pi\\agent\\AGENTS.md"), "Must include global AGENTS.md");
  assert.ok(text.includes("AGENTS.md"), "Must include workspace AGENTS.md");

  assert.ok(text.includes("[Skills]"), "Must include [Skills] header");
  assert.ok(text.includes("brainstorming"), "Must include skills");
  assert.ok(text.includes("systematic-debugging"), "Must include skills");

  assert.ok(text.includes("[Prompts]"), "Must include [Prompts] header");
  assert.ok(text.includes("/council"), "Must include prompts");
  assert.ok(text.includes("/review-loop"), "Must include prompts");

  assert.ok(text.includes("[Extensions]"), "Must include [Extensions] header");
  assert.ok(text.includes("@juicesharp/rpiv-todo"), "Must include extensions");
  assert.ok(text.includes("pi-lens:dist"), "Must include extensions");
});

test("StartupResourcesComponent toggleExpanded toggles between compact and expanded view", () => {
  const sampleData = {
    skills: ["skill-a", "skill-b", "skill-c"],
  };

  const comp = new StartupResourcesComponent(sampleData);
  assert.equal(comp.getExpanded(), false);

  // Compact view: joined with comma
  const compactText = comp.render(120).join("\n");
  assert.ok(compactText.includes("skill-a, skill-b, skill-c"));

  // Toggle expanded (Ctrl+O)
  comp.toggleExpanded();
  assert.equal(comp.getExpanded(), true);

  // Expanded view: individual lines
  const expandedLines = comp.render(120);
  assert.ok(expandedLines.some((l) => l.trim() === "skill-a"));
  assert.ok(expandedLines.some((l) => l.trim() === "skill-b"));

  // Toggle back
  comp.toggleExpanded();
  assert.equal(comp.getExpanded(), false);
});
