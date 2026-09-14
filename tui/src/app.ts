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
  {
    name: "model",
    description: "切换生效的大语言模型 (如 deepseek-chat, gemini-3.8-flash)",
    argumentHint: "<model>",
  },
  { name: "quota", description: "查询当前用户的模型调用配额与余量" },
  {
    name: "steer",
    description: "即时注入转向指令 (在下一个执行节点纠偏)",
    argumentHint: "<instruction>",
  },
  { name: "followup", description: "追加排队追问任务", argumentHint: "<task>" },
  { name: "exit", description: "安全退出交互终端并清理子进程" },
];

function findFdPath(): string | undefined {
  const home = os.homedir();
  const candidates = [
    path.join(
      home,
      ".pi",
      "agent",
      "bin",
      process.platform === "win32" ? "fd.exe" : "fd",
    ),
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
  private toolStartTimes = new Map<string, number>();
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

  private async handleSlashCommand(text: string): Promise<boolean> {
    if (text === "/exit" || text === "/quit") {
      await this.stop();
      process.exit(0);
    }

    if (text === "/clear") {
      this.chatContainer.clear();
      this.activeTools.clear();
      this.toolStartTimes.clear();
      this.currentAssistantComp = null;
      this.editor.setText("");
      this.tui.requestRender();
      return true;
    }

    if (text === "/help") {
      this.chatContainer.addChild(new UserMessageComponent("/help"));
      this.editor.setText("");
      const helpComp = new AssistantMessageComponent();
      this.chatContainer.addChild(helpComp);
      const helpText = [
        "**可用斜杠命令与快捷键说明**：",
        "- `/clear`：清空当前终端屏幕会话",
        "- `/help`：查看命令与快捷键帮助",
        "- `/steer <instruction>`：即时注入转向指令 (在下一个执行节点纠偏)",
        "- `/followup <task>`：追加排队追问任务",
        "- `/exit` 或 `/quit`：安全退出交互终端",
        "",
        "**常用快捷键**：",
        "- `Esc`：打断当前正在执行或生成的轮次 (Abort)",
        "- `Ctrl+O`：展开/折叠助手思考块与工具卡片",
        "- `@`：在输入框中触发文件路径模糊匹配与气泡联想",
        "- `/`：在输入框中触发斜杠命令气泡联想",
      ].join("\n");
      helpComp.appendTextDelta(helpText);
      helpComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (text.startsWith("/steer")) {
      const instruction = text.slice(6).trim();
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      if (instruction) {
        try {
          await this.client.steer(instruction);
          infoComp.appendTextDelta(`✓ 已成功注入转向指令: *${instruction}*`);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          infoComp.appendTextDelta(`✗ 注入转向指令失败: ${msg}`);
        }
      } else {
        infoComp.appendTextDelta(
          "⚠ 请输入转向指令内容，例如：`/steer 请优先编写测试用例`",
        );
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (text.startsWith("/followup")) {
      const followTask = text.slice(9).trim();
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      if (followTask) {
        try {
          await this.client.followup(followTask);
          infoComp.appendTextDelta(`✓ 已成功追加追问任务: *${followTask}*`);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          infoComp.appendTextDelta(`✗ 追加追问任务失败: ${msg}`);
        }
      } else {
        infoComp.appendTextDelta(
          "⚠ 请输入追问任务内容，例如：`/followup 顺便检查一下性能隐患`",
        );
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (text.startsWith("/")) {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      infoComp.appendTextDelta(
        `⚠ 命令 \`${text.split(" ")[0]}\` 暂未在当前内核模式下启用，输入 \`/help\` 查看所有可用命令。`,
      );
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    return false;
  }

  private async handleUserSubmit(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }

    if (trimmed.startsWith("/")) {
      await this.handleSlashCommand(trimmed);
      return;
    }

    if (this.isBusy) {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      infoComp.appendTextDelta(
        "⚠ 当前任务正在执行中。若需纠偏请使用 `/steer <指令>`，追加排队任务请使用 `/followup <任务>`，或按 `Esc` 打断当前执行。",
      );
      infoComp.finalize();
      this.tui.requestRender();
      return;
    }

    // 挂载用户消息气泡
    this.chatContainer.addChild(new UserMessageComponent(text));
    this.editor.setText("");

    // 实例化新的助手消息卡片
    const assistantComp = new AssistantMessageComponent();
    this.chatContainer.addChild(assistantComp);
    this.currentAssistantComp = assistantComp;
    this.activeTools.clear();
    this.toolStartTimes.clear();

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
      this.toolStartTimes.set(event.toolCallId, Date.now());
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
        const startTime =
          this.toolStartTimes.get(event.toolCallId) || Date.now();
        const elapsed = (Date.now() - startTime) / 1000;
        toolComp.updateResult(event.result, event.isError, elapsed);
        this.toolStartTimes.delete(event.toolCallId);
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
