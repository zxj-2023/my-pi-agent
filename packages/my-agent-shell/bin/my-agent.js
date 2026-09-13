#!/usr/bin/env node

import { AgentApp } from "../dist/app.js";

function parseArgs() {
  const args = process.argv.slice(2);
  const options = {
    workspace: process.cwd(),
    model: undefined,
    mode: "review",
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "-w" || arg === "--workspace") {
      options.workspace = args[++i];
    } else if (arg === "-m" || arg === "--model") {
      options.model = args[++i];
    } else if (arg === "--mode") {
      options.mode = args[++i];
    } else if (arg === "-h" || arg === "--help") {
      console.log(`
my-agent-shell: High-fidelity Pi-TUI terminal shell for my-pi-agent

Usage:
  my-agent [options]

Options:
  -w, --workspace <dir>   Working directory (default: current directory)
  -m, --model <model>     Target LLM model (e.g. antigravity/gemini-3.8-flash)
  --mode <mode>           Permission mode: review | yolo | strict (default: review)
  -h, --help              Show this help message
`);
      process.exit(0);
    }
  }

  return options;
}

async function main() {
  const options = parseArgs();
  const app = new AgentApp(options);

  process.on("SIGINT", async () => {
    await app.stop();
    process.exit(0);
  });

  process.on("SIGTERM", async () => {
    await app.stop();
    process.exit(0);
  });

  try {
    await app.start();
  } catch (err) {
    console.error("Fatal error starting agent:", err);
    process.exit(1);
  }
}

main();
