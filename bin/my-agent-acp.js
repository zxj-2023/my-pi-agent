#!/usr/bin/env node

/**
 * my-pi-agent ACP 启动器。
 *
 * 供 Zed / Neovim 等支持 Agent Client Protocol 的编辑器以子进程方式拉起。
 * 与 TUI 启动器不同，本进程**不代理协议**：它只负责定位 Python 运行时，
 * 然后以 stdio 透传（inherit）方式把 stdin/stdout 直接交给 Python 内核，
 * 保证 ACP 的 JSON-RPC 帧不被 Node 层缓冲或改写。
 */

import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");

const PYTHON_MODULE = "my_acp_agent.server";

function printHelp() {
  console.log(`
my-pi-agent-acp: 以 ACP (Agent Client Protocol) Agent 身份运行 my-pi-agent

Usage:
  my-pi-agent-acp [options]

Options:
  -w, --workspace <dir>   指定工作区目录 (默认: 编辑器传入的 cwd)
  -m, --model <model>     指定生效模型 (如 deepseek-chat, gemini-3.8-flash)
  --mode <mode>           权限安全模式: review (默认) | autonomous | strict | yolo
  --debug                 输出调试日志到 stderr
  -h, --help              查看帮助说明

说明:
  本命令通过 stdio 与编辑器进行 JSON-RPC 2.0 通信，通常由编辑器自动拉起，
  不需要在终端中手动运行。Zed 配置示例见 README 的 ACP 章节。
`);
}

/**
 * 定位可用的 Python 运行时，与 TUI 启动器保持同一套探测顺序：
 * 显式传入 > uv > python3 > python > uv 兜底。
 */
function resolvePythonCommand() {
  const moduleArgs = ["-m", PYTHON_MODULE];

  // 1. 优先使用外部显式传入的解释器（编辑器配置里可用 MY_PI_AGENT_PYTHON 指定）
  const explicit = process.env.MY_PI_AGENT_PYTHON;
  if (explicit) {
    return { cmd: explicit, args: moduleArgs };
  }

  // 2. 探测 uv（--project 锚定包根目录，支持全局任意路径启动）
  try {
    if (spawnSync("uv", ["--version"], { stdio: "ignore" }).status === 0) {
      return {
        cmd: "uv",
        args: ["run", "--project", repoRoot, "python", ...moduleArgs],
      };
    }
  } catch {
    // uv 未安装，继续探测
  }

  // 3. 探测 python3
  try {
    if (spawnSync("python3", ["--version"], { stdio: "ignore" }).status === 0) {
      return { cmd: "python3", args: moduleArgs };
    }
  } catch {
    // python3 未安装，继续探测
  }

  // 4. 探测 python
  try {
    if (spawnSync("python", ["--version"], { stdio: "ignore" }).status === 0) {
      return { cmd: "python", args: moduleArgs };
    }
  } catch {
    // python 未安装
  }

  // 5. 兜底回退为 uv，启动失败时给出友好报错
  return {
    cmd: "uv",
    args: ["run", "--project", repoRoot, "python", ...moduleArgs],
  };
}

function main() {
  const argv = process.argv.slice(2);

  if (argv.includes("-h") || argv.includes("--help")) {
    printHelp();
    process.exit(0);
  }

  const { cmd, args } = resolvePythonCommand();

  const pythonPath =
    path.join(repoRoot, "src") +
    (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : "");

  const child = spawn(cmd, [...args, ...argv], {
    // 关键：stdio 全透传，ACP 的 JSON-RPC 帧直连编辑器，Node 层不做任何缓冲
    stdio: "inherit",
    cwd: process.cwd(),
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONPATH: pythonPath,
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
    },
  });

  child.on("error", (err) => {
    process.stderr.write(
      `\n[my-pi-agent-acp] 无法启动 Python 内核 (${cmd}): ${err.message}\n` +
        `请确认已安装 uv 或 Python 3.11+：\n` +
        `  uv:     curl -LsSf https://astral.sh/uv/install.sh | sh\n` +
        `  或设置环境变量 MY_PI_AGENT_PYTHON 指向可用的 Python 解释器。\n\n`,
    );
    process.exit(1);
  });

  // 编辑器关闭会话时转发终止信号，避免残留子进程
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(signal, () => {
      if (!child.killed) child.kill(signal);
    });
  }

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 0);
  });
}

main();
