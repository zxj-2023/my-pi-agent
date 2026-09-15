import { ChildProcess, spawn, spawnSync } from "node:child_process";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import * as readline from "node:readline";
import { EventEmitter } from "node:events";
import {
  AgentEvent,
  JsonRpcNotification,
  JsonRpcRequest,
  JsonRpcResponse,
} from "./protocol.js";

export interface SessionMessage {
  role: string;
  content: string;
  metadata?: {
    tool_calls?: Array<{
      id: string;
      name?: string;
      args?: Record<string, unknown>;
      function?: {
        name: string;
        arguments: string | Record<string, unknown>;
      };
      [key: string]: unknown;
    }>;
    tool_call_id?: string;
    is_error?: boolean;
    tool_name?: string;
    thinking?: string;
    reasoning_content?: string;
    [key: string]: unknown;
  };
}

export interface InitializeResult {
  status: string;
  workspace: string;
  model: string;
  session_id?: string;
  session_file?: string;
  session_name?: string;
  messages?: SessionMessage[];
}

export interface PythonKernelClientOptions {
  workspace?: string;
  model?: string;
  mode?: string;
  pythonExecutable?: string;
  continueSession?: boolean;
  resume?: string | boolean;
  sessionName?: string;
  thinking?: string;
  noSession?: boolean;
  newSession?: boolean;
}

export class PythonKernelClient extends EventEmitter {
  private child: ChildProcess | null = null;
  private nextId = 1;
  private pendingRequests = new Map<
    number | string,
    { resolve: (value: unknown) => void; reject: (error: Error) => void }
  >();
  private activeEventCallback: ((event: AgentEvent) => void) | null = null;
  private rl: readline.Interface | null = null;

  constructor(public readonly options: PythonKernelClientOptions = {}) {
    super();
  }

  public async start(): Promise<InitializeResult> {
    if (this.child) {
      return {
        status: "ok",
        workspace: this.options.workspace || process.cwd(),
        model: this.options.model || "default",
      };
    }

    const workspace = this.options.workspace || process.cwd();
    const __dirname = path.dirname(fileURLToPath(import.meta.url));
    const repoRoot = path.resolve(__dirname, "../..");

    const { cmd, args } = this.resolvePythonCommand(workspace);

    this.child = spawn(cmd, args, {
      stdio: ["pipe", "pipe", "inherit"],
      cwd: repoRoot,
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
      },
    });

    if (!this.child.stdout || !this.child.stdin) {
      throw new Error(
        "Failed to initialize stdin/stdout pipes for Python kernel.",
      );
    }

    this.child.stdin.on("error", (err: Error) => {
      this.emit("error", err);
    });

    this.rl = readline.createInterface({
      input: this.child.stdout,
      terminal: false,
    });

    this.rl.on("line", (line: string) => {
      this.handleLine(line);
    });

    this.child.on("exit", (code: number | null, signal: string | null) => {
      this.child = null;
      this.emit("exit", { code, signal });
      for (const { reject } of this.pendingRequests.values()) {
        reject(
          new Error(
            `Python kernel terminated prematurely with code ${code}, signal ${signal}`,
          ),
        );
      }
      this.pendingRequests.clear();
    });

    this.child.on("error", (err: Error) => {
      this.emit("error", err);
      for (const { reject } of this.pendingRequests.values()) {
        reject(
          new Error(
            `无法启动 Python 内核 (${cmd}): ${err.message}。请确保已安装 uv (https://astral.sh/uv) 或 Python 3.11+。`,
          ),
        );
      }
      this.pendingRequests.clear();
    });

    // 初始化内核
    const res = (await this.sendRequest("initialize", {
      workspace,
      model: this.options.model,
      mode: this.options.mode || "review",
      continue_session: this.options.continueSession,
      resume: this.options.resume,
      name: this.options.sessionName,
      thinking: this.options.thinking,
      no_session: this.options.noSession,
      new_session: this.options.newSession,
    })) as InitializeResult;
    return res;
  }

  private resolvePythonCommand(workspace: string): {
    cmd: string;
    args: string[];
  } {
    const rpcArgs = ["-m", "my_coding_agent.rpc_server", "-w", workspace];
    if (this.options.model) {
      rpcArgs.push("-m", this.options.model);
    }

    // 1. 优先使用外部显式传入的 Python 解释器
    if (this.options.pythonExecutable) {
      return { cmd: this.options.pythonExecutable, args: rpcArgs };
    }

    // 2. 探测系统 uv 极速包管理器
    try {
      const probeUv = spawnSync("uv", ["--version"], { stdio: "ignore" });
      if (probeUv.status === 0) {
        return { cmd: "uv", args: ["run", "python", ...rpcArgs] };
      }
    } catch {
      // uv 未安装
    }

    // 3. 探测系统 python3
    try {
      const probePy3 = spawnSync("python3", ["--version"], { stdio: "ignore" });
      if (probePy3.status === 0) {
        return { cmd: "python3", args: rpcArgs };
      }
    } catch {
      // python3 未安装
    }

    // 4. 探测系统 python
    try {
      const probePy = spawnSync("python", ["--version"], { stdio: "ignore" });
      if (probePy.status === 0) {
        return { cmd: "python", args: rpcArgs };
      }
    } catch {
      // python 未安装
    }

    // 5. 兜底回退为 uv，并将在子进程启动失败时触发友好报错
    return { cmd: "uv", args: ["run", "python", ...rpcArgs] };
  }

  private handleLine(line: string): void {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }

    try {
      const msg = JSON.parse(trimmed);
      if (
        "id" in msg &&
        (msg.result !== undefined || msg.error !== undefined)
      ) {
        // RPC Response
        const res = msg as JsonRpcResponse;
        const pending = this.pendingRequests.get(res.id);
        if (pending) {
          this.pendingRequests.delete(res.id);
          if (res.error) {
            pending.reject(new Error(res.error.message));
          } else {
            pending.resolve(res.result);
          }
        }
      } else if (msg.method === "event") {
        // RPC Event Notification
        const notif = msg as JsonRpcNotification;
        // SAFETY: notif.params is serialized by Python rpc_server.serialize_event to conform to AgentEvent schema
        const event = notif.params as unknown as AgentEvent;
        this.emit("event", event);
        if (this.activeEventCallback) {
          this.activeEventCallback(event);
        }
      }
    } catch {
      // 忽略无法解析的格式
    }
  }

  public async sendRequest<T = unknown>(
    method: string,
    params?: Record<string, unknown>,
  ): Promise<T> {
    if (!this.child || !this.child.stdin) {
      throw new Error("Python kernel is not running.");
    }

    const id = this.nextId++;
    const req: JsonRpcRequest = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };

    return new Promise<T>((resolve, reject) => {
      this.pendingRequests.set(id, {
        resolve: (val) => resolve(val as T),
        reject,
      });

      this.child!.stdin!.write(JSON.stringify(req) + "\n");
    });
  }

  public async prompt(
    text: string,
    onEventOrOptions?: ((event: AgentEvent) => void) | Record<string, unknown>,
  ): Promise<void> {
    if (typeof onEventOrOptions === "function") {
      this.activeEventCallback = onEventOrOptions;
    } else {
      this.activeEventCallback = null;
    }
    const params: Record<string, unknown> = { text };
    if (
      onEventOrOptions &&
      typeof onEventOrOptions === "object" &&
      typeof onEventOrOptions !== "function"
    ) {
      Object.assign(params, onEventOrOptions);
    }
    try {
      await this.sendRequest("prompt", params);
    } finally {
      this.activeEventCallback = null;
    }
  }

  public async steer(message: string): Promise<void> {
    await this.sendRequest("steer", { message });
  }

  public async followup(message: string): Promise<void> {
    await this.sendRequest("followup", { message });
  }

  public async abort(): Promise<void> {
    await this.sendRequest("abort");
  }

  public async shutdown(): Promise<void> {
    try {
      if (this.child && this.child.stdin) {
        await this.sendRequest("shutdown");
      }
    } catch {
      // 忽略关闭时的异常
    } finally {
      if (this.child) {
        this.child.kill();
        this.child = null;
      }
      if (this.rl) {
        this.rl.close();
        this.rl = null;
      }
    }
  }
}
