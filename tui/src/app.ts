import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as process from "node:process";
import {
  CombinedAutocompleteProvider,
  Container,
  Editor,
  type EditorTheme,
  matchesKey,
  ProcessTerminal,
  type SlashCommand,
  type TUI,
  TuiMainScreen,
} from "@earendil-works/pi-tui";
import { PythonKernelClient } from "./client.js";
import { AssistantMessageComponent } from "./components/assistant-message.js";
import { FooterComponent } from "./components/footer.js";
import { ToolExecutionComponent } from "./components/tool-execution.js";
import { UserMessageComponent } from "./components/user-message.js";
import { AgentEvent } from "./protocol.js";
import { theme } from "./theme/theme.js";

export interface AppOptions {
  workspace?: string;
  model?: string;
  mode?: string;
}

export const BUILTIN_SLASH_COMMANDS: SlashCommand[] = [
  { name: "help", description: "查看所有可用命令与快捷键说明" },
  { name: "clear", description: "清空当前终端屏幕会话" },
  { name: "model", description: "切换生效的大语言模型 (如 deepseek-chat, gemini-3.8-flash)", argumentHint: "<model>" },
  { name: "quota", description: "查询当前用户的模型调用配额与余量" },
  { name: "steer", description: "即时注入转向指令 (在下一个执行节点纠偏)", argumentHint: "<instruction>" },
  { name: "followup", description: "追加排队追问任务", argumentHint: "<task>" },
  { name: "exit", description: "安全退出交互终端并清理子进程" },
];

function findFdPath(): string | undefined {
  const home = os.homedir();
  const candidates = [
    path.join(home, ".pi", "agent", "bin", process.platform === "win32" ? "fd.exe" : "fd"),
    path.join(home, ".local", "bin", "fd"),
  ];

  for (const candidate of candidates) {
    try {
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    } catch {
      // 忽略无法访问的路径
    }
  }
  return undefined;
}

export class AgentApp {
  private tui: TUI;
  private chatContainer: Container;
  private footer: FooterComponent;
  private editor: Editor;
  private client: PythonKernelClient;
  private isBusy = false;
  private currentAssistantComp: AssistantMessageComponent | null = null;
  private activeTools = new Map<string, ToolExecutionComponent>();
  private turnStartTime = 0;

  constructor(public readonly options: AppOptions = {}) {
    const terminal = new ProcessTerminal();
    this.tui = new TuiMainScreen(terminal);

    this.client = new PythonKernelClient({
      workspace: options.workspace,
      model: options.model,
      mode: options.mode,
    });

    this.chatContainer = new Container();

    this.footer = new FooterComponent({
      workspace: options.workspace || process.cwd(),
      modelName: options.model || "default",
    });

    const editorTheme: EditorTheme = {
      borderColor: (str: string) => theme.fg("borderMuted", str),
      selectList: {
        selectedPrefix: (s: string) => theme.fg("accent", s),
        selectedText: (s: string) => theme.bold(theme.fg("accent", s)),
        description: (s: string) => theme.fg("muted", s),
        scrollInfo: (s: string) => theme.dim(s),
        noMatch: (_text: string) => theme.dim("无匹配项"),
      },
    };

    this.editor = new Editor(this.tui, editorTheme);

    // 挂载 @ 文件智能联想与 / 斜杠命令气泡补全器
    const workspace = options.workspace || process.cwd();
    const fdPath = findFdPath();
    const autocompleteProvider = new CombinedAutocompleteProvider(
      BUILTIN_SLASH_COMMANDS,
      workspace,
      fdPath,
    );
    this.editor.setAutocompleteProvider(autocompleteProvider);

    this.tui.addChild(this.chatContainer);
    this.tui.addChild(this.footer);
    this.tui.addChild(this.editor);
    this.tui.setFocus(this.editor);

    this.setupListeners();
  }

  private setupListeners(): void {
    // 1. 提交输入提问
    this.editor.onSubmit = (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) {
        return;
      }
      this.handleUserSubmit(trimmed);
    };

    // 2. 全局键盘热键监听 (Ctrl+C, Esc, Ctrl+O)
    this.tui.addInputListener((data: string) => {
      if (matchesKey(data, "ctrl+c")) {
        this.stop();
        process.exit(0);
      } else if (matchesKey(data, "escape")) {
        if (this.isBusy) {
          this.client.abort();
        }
      } else if (matchesKey(data, "ctrl+o")) {
        // 展开/折叠当前正在交互的助手思考块或工具卡片
        if (this.currentAssistantComp) {
          this.currentAssistantComp.toggleThinking();
        }
        for (const tool of this.activeTools.values()) {
          tool.toggleExpanded();
        }
        this.tui.requestRender();
      }
      return undefined;
    });

    // 3. 监听 Python 退出事件
    this.client.on("exit", () => {
      this.isBusy = false;
      this.footer.update({ isBusy: false });
      this.tui.requestRender();
    });
  }

  private async handleUserSubmit(text: string): Promise<void> {
    if (text === "/exit" || text === "/quit") {
      await this.stop();
      process.exit(0);
    }

    // 挂载用户消息气泡
    this.chatContainer.addChild(new UserMessageComponent(text));
    this.editor.setText("");

    // 实例化新的助手消息卡片
    const assistantComp = new AssistantMessageComponent();
    this.chatContainer.addChild(assistantComp);
    this.currentAssistantComp = assistantComp;
    this.activeTools.clear();

    this.isBusy = true;
    this.turnStartTime = Date.now();
    this.footer.update({ isBusy: true });
    this.tui.requestRender();

    try {
      await this.client.prompt(text, (event: AgentEvent) => {
        this.handleAgentEvent(event);
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      assistantComp.appendTextDelta(`\n\u2717 发生错误: ${msg}`);
    } finally {
      this.isBusy = false;
      if (this.currentAssistantComp) {
        this.currentAssistantComp.finalize();
      }
      const elapsed = (Date.now() - this.turnStartTime) / 1000;
      this.footer.update({ isBusy: false, elapsedSeconds: elapsed });
      this.tui.requestRender();
    }
  }

  private handleAgentEvent(event: AgentEvent): void {
    if (event.type === "message_update") {
      if (this.currentAssistantComp) {
        if (event.reasoning_delta) {
          this.currentAssistantComp.appendReasoningDelta(event.reasoning_delta);
        }
        if (event.delta) {
          this.currentAssistantComp.appendTextDelta(event.delta);
        }
      }
    } else if (event.type === "tool_execution_start") {
      const toolComp = new ToolExecutionComponent(
        event.toolName,
        event.toolCallId,
        event.args,
      );
      this.activeTools.set(event.toolCallId, toolComp);
      this.chatContainer.addChild(toolComp);
    } else if (event.type === "tool_execution_update") {
      const toolComp = this.activeTools.get(event.toolCallId);
      if (toolComp && event.args) {
        toolComp.updateArgs(event.args);
      }
    } else if (event.type === "tool_execution_end") {
      const toolComp = this.activeTools.get(event.toolCallId);
      if (toolComp) {
        const elapsed = (Date.now() - this.turnStartTime) / 1000;
        toolComp.updateResult(event.result, event.isError, elapsed);
      }
    } else if (event.type === "agent_end") {
      if (this.currentAssistantComp) {
        this.currentAssistantComp.finalize();
      }
    }

    this.tui.requestRender();
  }

  public async start(): Promise<void> {
    await this.client.start();
    this.tui.start();
    this.tui.requestRender();
  }

  public async stop(): Promise<void> {
    this.tui.stop();
    await this.client.shutdown();
  }
}
