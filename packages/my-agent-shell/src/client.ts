import { ChildProcess, spawn } from "node:child_process";
import * as readline from "node:readline";
import { EventEmitter } from "node:events";
import { AgentEvent, JsonRpcNotification, JsonRpcRequest, JsonRpcResponse } from "./protocol.js";

export interface PythonKernelClientOptions {
  workspace?: string;
  model?: string;
  mode?: string;
  pythonExecutable?: string;
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

  public async start(): Promise<void> {
    if (this.child) {
      return;
    }

    const workspace = this.options.workspace || process.cwd();
    const args = ["run", "python", "-m", "my_coding_agent.rpc_server", "-w", workspace];
    if (this.options.model) {
      args.push("-m", this.options.model);
    }

    const cmd = this.options.pythonExecutable || "uv";

    this.child = spawn(cmd, args, {
      stdio: ["pipe", "pipe", "inherit"],
      cwd: workspace,
      windowsHide: true,
    });

    if (!this.child.stdout || !this.child.stdin) {
      throw new Error("Failed to initialize stdin/stdout pipes for Python kernel.");
    }

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
        reject(new Error(`Python kernel terminated prematurely with code ${code}, signal ${signal}`));
      }
      this.pendingRequests.clear();
    });

    this.child.on("error", (err: Error) => {
      this.emit("error", err);
    });

    // 初始化内核
    await this.sendRequest("initialize", {
      workspace,
      model: this.options.model,
      mode: this.options.mode || "review",
    });
  }

  private handleLine(line: string): void {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }

    try {
      const msg = JSON.parse(trimmed);
      if ("id" in msg && (msg.result !== undefined || msg.error !== undefined)) {
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

  public async sendRequest<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
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

  public async prompt(text: string, onEvent?: (event: AgentEvent) => void): Promise<void> {
    this.activeEventCallback = onEvent || null;
    try {
      await this.sendRequest("prompt", { text });
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
