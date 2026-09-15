#!/usr/bin/env node

import { AgentApp } from "../dist/app.js";

function parseArgs() {
  const args = process.argv.slice(2);
  const options = {
    workspace: process.env.INIT_CWD || process.cwd(),
    model: undefined,
    mode: "review",
    continueSession: false,
    resume: undefined,
    sessionName: undefined,
    thinking: undefined,
    noSession: false,
    newSession: false,
    prompt: undefined,
    pythonExecutable: undefined,
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "-w" || arg === "--workspace") {
      options.workspace = args[++i];
    } else if (arg === "--python-executable") {
      options.pythonExecutable = args[++i];
    } else if (arg === "-m" || arg === "--model") {
      options.model = args[++i];
    } else if (arg === "--mode") {
      options.mode = args[++i];
    } else if (arg === "-c" || arg === "--continue") {
      options.continueSession = true;
    } else if (arg === "-r" || arg === "--resume") {
      const next = args[i + 1];
      if (next && !next.startsWith("-")) {
        options.resume = args[++i];
      } else {
        options.resume = true;
      }
    } else if (arg === "-n" || arg === "--name") {
      options.sessionName = args[++i];
    } else if (arg === "--thinking") {
      options.thinking = args[++i];
    } else if (arg === "--no-session") {
      options.noSession = true;
    } else if (arg === "--new-session") {
      options.newSession = true;
    } else if (arg === "-h" || arg === "--help") {
      console.log(`
my-agent: High-fidelity Pi-TUI terminal shell for my-pi-agent

Usage:
  my-agent [options] [prompt]

Options:
  -c, --continue          一键续接当前项目最近一次历史会话
  -r, --resume [id]       启动时直接打开交互式会话选择器或恢复指定会话
  --new-session           强制开启全新会话 (默认)
  -n, --name <title>      启动时直接为该会话命名
  -m, --model <model>     指定生效模型 (如 deepseek-chat, gemini-3.8-flash)
  --thinking <level>      指定思考深度等级 (off/minimal/low/medium/high/max)
  --no-session            内存无痕沙箱模式 (不持久化 session 文件)
  -w, --workspace <dir>   指定工作区目录 (默认: 当前目录)
  --mode <mode>           权限安全模式: review (默认) | yolo | strict
  -h, --help              查看帮助说明
`);
      process.exit(0);
    } else if (!arg.startsWith("-") && !options.prompt) {
      options.prompt = arg;
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
