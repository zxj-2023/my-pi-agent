import test from "node:test";
import assert from "node:assert/strict";
import { HeaderComponent } from "../dist/components/header.js";

test("HeaderComponent renders app logo, version, and keybinding hints", () => {
  const header = new HeaderComponent("0.1.0");
  assert.ok(header);
  const lines = header.render(80);
  assert.ok(lines.length >= 3, "Header must render at least 3 lines");
  const text = lines.join("\n");
  assert.ok(
    text.includes("my-pi-agent"),
    "Header must include app logo 'my-pi-agent'",
  );
  assert.ok(text.includes("v0.1.0"), "Header must include version 'v0.1.0'");
  assert.ok(text.includes("Esc"), "Header must include 'Esc' keybinding hint");
  assert.ok(
    text.includes("Ctrl+C"),
    "Header must include 'Ctrl+C' keybinding hint",
  );
  assert.ok(text.includes("/"), "Header must include '/' keybinding hint");
  assert.ok(text.includes("!"), "Header must include '!' keybinding hint");
  assert.ok(
    text.includes("Ctrl+O"),
    "Header must include 'Ctrl+O' keybinding hint",
  );
});

test("HeaderComponent uses default version if not provided", () => {
  const header = new HeaderComponent();
  const lines = header.render(80);
  assert.ok(lines.length >= 3, "Header must render at least 3 lines");
  const text = lines.join("\n");
  assert.ok(text.includes("my-pi-agent"));
  assert.ok(text.includes("v0.1.0"));
});
