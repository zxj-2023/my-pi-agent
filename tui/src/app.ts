import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as process from "node:process";
import {
  CombinedAutocompleteProvider,
  type Component,
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
import { HeaderComponent } from "./components/header.js";
import { LoginSelectorComponent } from "./components/login-selector.js";
import {
  type ModelItem,
  ModelSelectorComponent,
} from "./components/model-selector.js";
import {
  type SessionItem,
  SessionSelectorComponent,
} from "./components/session-selector.js";
import { ThinkingSelectorComponent } from "./components/thinking-selector.js";
import { ToolExecutionComponent } from "./components/tool-execution.js";
import { UserMessageComponent } from "./components/user-message.js";
import { AgentEvent } from "./protocol.js";
import { theme } from "./theme/theme.js";

export interface AppOptions {
  workspace?: string;
  model?: string;
  mode?: string;
  continueSession?: boolean;
  resume?: string | boolean;
  sessionName?: string;
  thinking?: string;
  noSession?: boolean;
  newSession?: boolean;
  prompt?: string;
  pythonExecutable?: string;
}

export const BUILTIN_SLASH_COMMANDS: SlashCommand[] = [
  { name: "help", description: "查看所有可用命令与快捷键说明" },
  { name: "clear", description: "清空当前终端屏幕会话" },
  { name: "new", description: "结束当前会话，开启全新的空白会话" },
  {
    name: "resume",
    description: "列出、搜索或恢复指定历史会话",
    argumentHint: "[session_id]",
  },
  {
    name: "name",
    description: "查看或设置当前会话的显示名称",
    argumentHint: "[title]",
  },
  {
    name: "compact",
    description: "触发上下文 L4 级 LLM 摘要压缩",
    argumentHint: "[instructions]",
  },
  { name: "tree", description: "展示当前会话 DAG 树，支持分支漫游与回退" },
  {
    name: "fork",
    description: "从指定历史提问分叉派生为独立新会话",
    argumentHint: "[entry_id]",
  },
  { name: "clone", description: "将当前活跃分支完整克隆为新会话" },
  {
    name: "model",
    description: "切换生效的大语言模型 (如 deepseek-chat, gemini-3.8-flash)",
    argumentHint: "[model]",
  },
  {
    name: "thinking",
    description: "调节思考预算等级 (off/minimal/low/medium/high/max)",
    argumentHint: "[level]",
  },
  {
    name: "login",
    description: "查看凭据配置指南或快速绑定 API Key",
    argumentHint: "[provider] [key]",
  },
  {
    name: "logout",
    description: "注销或清除指定 Provider 的已存凭据",
    argumentHint: "<provider>",
  },
  { name: "quota", description: "查询当前用户的模型调用配额与余量" },
  {
    name: "session",
    description: "查看当前会话信息与全局集中存储路径",
  },
  {
    name: "settings",
    description: "查看当前生效的全局与项目级配置",
    argumentHint: "[key] [value]",
  },
  {
    name: "reload",
    description: "热重载 Skills、Prompts、Extensions 与 AGENTS.md",
  },
  {
    name: "trust",
    description: "查看或设置当前项目的信任状态",
    argumentHint: "[status]",
  },
  {
    name: "steer",
    description: "即时注入转向指令 (在下一个执行节点纠偏)",
    argumentHint: "<instruction>",
  },
  { name: "followup", description: "追加排队追问任务", argumentHint: "<task>" },
  { name: "exit", description: "安全退出交互终端并清理子进程" },
];

export function isBuiltinSlashCommand(cmd: string): boolean {
  const c = cmd.startsWith("/")
    ? cmd.slice(1).toLowerCase()
    : cmd.toLowerCase();
  return (
    c === "quit" ||
    BUILTIN_SLASH_COMMANDS.some((item) => item.name.toLowerCase() === c)
  );
}

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
  private header: HeaderComponent;
  private chatContainer: Container;
  private editorContainer: Container;
  private footer: FooterComponent;
  private editor: Editor;
  private client: PythonKernelClient;
  private isBusy = false;
  private currentAssistantComp: AssistantMessageComponent | null = null;
  private activeTools = new Map<string, ToolExecutionComponent>();
  private toolStartTimes = new Map<string, number>();
  private turnStartTime = 0;
  private activeSelectorToken?: object;
  private activeSelectorDispose?: () => void;
  private activeSelectorComponent?: { handleInput: (data: string) => void };

  constructor(public readonly options: AppOptions = {}) {
    const terminal = new ProcessTerminal();
    this.tui = new TuiMainScreen(terminal);

    this.client = new PythonKernelClient({
      workspace: options.workspace,
      model: options.model,
      mode: options.mode,
      continueSession: options.continueSession,
      resume: options.resume,
      sessionName: options.sessionName,
      thinking: options.thinking,
      noSession: options.noSession,
      newSession: options.newSession,
      pythonExecutable: options.pythonExecutable,
    });

    this.chatContainer = new Container();

    this.footer = new FooterComponent({
      workspace: options.workspace || process.cwd(),
      modelName: options.model || "default",
      sessionName: options.sessionName,
      thinkingLevel: options.thinking || "off",
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

    this.editorContainer = new Container();
    this.editorContainer.addChild(this.editor);

    this.header = new HeaderComponent();

    this.tui.addChild(this.header);
    this.tui.addChild(this.chatContainer);
    this.tui.addChild(this.editorContainer);
    this.tui.addChild(this.footer);
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
      void this.handleUserSubmit(trimmed).catch(() => {
        // 异常已在 handleUserSubmit 内部统一捕获并在 UI 气泡渲染
      });
    };

    // 监听输入框文本变化 (检测以 ! 开头切换为 Bash Mode 变色)
    this.editor.onChange = (text: string) => {
      if (text.startsWith("!")) {
        this.editor.borderColor = (str: string) => theme.fg("warning", str);
      } else {
        this.editor.borderColor = (str: string) => theme.fg("borderMuted", str);
      }
      this.tui.requestRender();
    };

    // 2. 全局键盘热键监听 (Ctrl+C, Esc, Ctrl+O, Ctrl+L)
    this.tui.addInputListener((data: string) => {
      // 若当前挂载了活动的 Selector，直接委托给 Selector 处理键盘事件
      if (this.activeSelectorComponent) {
        this.activeSelectorComponent.handleInput(data);
        this.tui.requestRender();
        return undefined;
      }

      if (matchesKey(data, "ctrl+c")) {
        void this.stop().finally(() => process.exit(0));
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
      } else if (matchesKey(data, "ctrl+l")) {
        this.showModelSelector();
        return undefined;
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

  private resetEditorBorder(): void {
    this.editor.borderColor = (str: string) => theme.fg("borderMuted", str);
  }

  private finalizeActiveTools(reason = "执行中断"): void {
    for (const [id, toolComp] of this.activeTools.entries()) {
      if (!toolComp.finished) {
        const startTime = this.toolStartTimes.get(id) || Date.now();
        const elapsed = (Date.now() - startTime) / 1000;
        toolComp.updateResult(reason, true, elapsed);
      }
    }
    this.toolStartTimes.clear();
  }

  private async handleSlashCommand(text: string): Promise<boolean> {
    const [rawCmd, ...argParts] = text.split(/\s+/);
    const cmd = rawCmd.toLowerCase();
    const argsText = argParts.join(" ").trim();

    if (cmd === "/exit" || cmd === "/quit") {
      await this.stop();
      process.exit(0);
    }

    if (cmd === "/clear") {
      if (this.isBusy) {
        this.chatContainer.addChild(new UserMessageComponent(text));
        this.editor.setText("");
        this.resetEditorBorder();
        const infoComp = new AssistantMessageComponent();
        this.chatContainer.addChild(infoComp);
        infoComp.appendTextDelta(
          "⚠ 当前任务正在执行中，请先按 Esc 打断当前执行后再清空会话。",
        );
        infoComp.finalize();
        this.tui.requestRender();
        return true;
      }
      this.chatContainer.clear();
      this.activeTools.clear();
      this.toolStartTimes.clear();
      this.currentAssistantComp = null;
      this.editor.setText("");
      this.resetEditorBorder();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/help") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const helpComp = new AssistantMessageComponent();
      this.chatContainer.addChild(helpComp);
      const helpText = [
        "**会话生命周期与分支命令**：",
        "- `/new`：开启全新的空白会话 (延期落盘)",
        "- `/resume [id]`：列出历史会话或恢复指定会话",
        "- `/name [title]`：查看或重命名当前会话",
        "- `/compact [prompt]`：触发上下文 L4 级 LLM 摘要压缩",
        "- `/tree`：展示当前会话 DAG 树拓扑与活跃分支",
        "- `/fork [entry_id]`：从历史提问分叉派生为独立新会话",
        "- `/clone`：将当前活跃分支完整克隆为新会话",
        "",
        "**模型与凭据控制**：",
        "- `/model [name]`：查看或切换大语言模型",
        "- `/thinking [level]`：调节思考深度 (off/minimal/low/medium/high/max)",
        "- `/login [provider] [key]`：绑定 Provider API Key 凭证",
        "- `/logout <provider>`：注销指定 Provider 的凭据",
        "- `/quota`：查询模型调用配额与余量",
        "",
        "**系统环境与安全**：",
        "- `/session`：查看当前会话信息与全局集中存储路径",
        "- `/settings`：查看全局与项目级配置项",
        "- `/reload`：热重载 Skills、Prompts、Extensions 与 AGENTS.md",
        "- `/trust [status]`：设置或查看当前项目信任状态",
        "",
        "**任务控制与交互**：",
        "- `/steer <instruction>`：即时注入转向指令 (在下一个节点纠偏)",
        "- `/followup <task>`：追加排队追问任务",
        "- `/clear`：清空当前终端屏幕会话",
        "- `/help`：查看所有可用命令与快捷键说明",
        "- `/exit` 或 `/quit`：安全退出交互终端",
        "",
        "**输入行即时宏扩展**：",
        "- `!command`：执行本地 Shell 命令，输出送入大模型上下文",
        "- `!!command`：执行本地 Shell 命令，仅屏幕渲染，不入模型上下文",
        "- `/skill:<name> [args]`：展开指定 Skill 的模板正文",
        "- `/<template> [args]`：展开 prompts/ 目录下的模板并替换参数",
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

    if (cmd === "/new") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const res = await this.client.sendRequest<{
          status: string;
          session_id: string;
          session_file: string;
        }>("session_new");
        this.chatContainer.clear();
        this.activeTools.clear();
        this.toolStartTimes.clear();
        this.currentAssistantComp = null;
        this.isBusy = false;
        this.footer.update({ isBusy: false });
        const newComp = new AssistantMessageComponent();
        this.chatContainer.addChild(newComp);
        newComp.appendTextDelta(
          `✓ 已开启全新空白会话 (ID: \`${res.session_id}\`)`,
        );
        newComp.finalize();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 开启新会话失败: ${msg}`);
        infoComp.finalize();
      }
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/resume") {
      if (!argsText) {
        this.showSessionSelector();
        return true;
      }
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const res = await this.client.sendRequest<{
          status: string;
          session_id: string;
          message_count?: number;
        }>("session_resume", { session_id: argsText });
        infoComp.appendTextDelta(`✓ 已成功恢复会话: \`${res.session_id}\``);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 恢复会话失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/name") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      if (argsText) {
        try {
          const res = await this.client.sendRequest<{
            status: string;
            name: string;
          }>("session_name", { name: argsText });
          infoComp.appendTextDelta(`✓ 会话已重命名为: *${res.name}*`);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          infoComp.appendTextDelta(`✗ 重命名会话失败: ${msg}`);
        }
      } else {
        infoComp.appendTextDelta(
          "⚠ 请输入会话名称，例如：`/name 优化登录逻辑`",
        );
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/compact") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const params = argsText ? { instructions: argsText } : {};
        const res = await this.client.sendRequest<{
          status: string;
          tokens_before: number;
          tokens_after: number;
          summary?: string;
        }>("session_compact", params);
        const summaryText = res.summary
          ? `\n\n**压缩摘要**:\n${res.summary}`
          : "";
        infoComp.appendTextDelta(
          `✓ 上下文压缩完成 (Tokens: ${res.tokens_before} → ${res.tokens_after})${summaryText}`,
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 上下文压缩失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/tree") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const res = await this.client.sendRequest<{
          status: string;
          nodes: Array<{
            id: string;
            parent_id: string | null;
            role: string;
            preview: string;
            is_leaf: boolean;
            is_active_path: boolean;
          }>;
          active_leaf_id: string | null;
          root_id: string | null;
        }>("session_tree");
        if (!res.nodes || res.nodes.length === 0) {
          infoComp.appendTextDelta("ℹ 当前会话树为空。");
        } else {
          const lines = ["**会话 DAG 树** (星号标记当前活跃路径):"];
          for (const node of res.nodes) {
            const marker = node.is_active_path ? "*" : " ";
            const leafMarker =
              node.id === res.active_leaf_id ? " [ACTIVE LEAF]" : "";
            const preview = (node.preview || "")
              .replace(/\n/g, " ")
              .slice(0, 60);
            lines.push(
              `${marker} [${node.role}] \`${node.id.slice(0, 8)}\` ${preview}${leafMarker}`,
            );
          }
          infoComp.appendTextDelta(lines.join("\n"));
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 获取会话树失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/fork") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        let targetEntryId = argsText;
        if (!targetEntryId) {
          const treeRes = await this.client.sendRequest<{
            status: string;
            nodes: Array<{ id: string; role: string; is_active_path: boolean }>;
          }>("session_tree");
          const userNodes = (treeRes.nodes || []).filter(
            (n) => n.is_active_path && n.role === "user",
          );
          if (userNodes.length > 0) {
            targetEntryId = userNodes[userNodes.length - 1].id;
          }
        }

        if (targetEntryId) {
          const res = await this.client.sendRequest<{
            status: string;
            new_session_id: string;
            session_file: string;
            prompt_text: string;
          }>("session_fork", { entry_id: targetEntryId });
          infoComp.appendTextDelta(
            `✓ 已成功从节点 \`${targetEntryId.slice(0, 8)}\` 分叉开辟新会话: \`${res.new_session_id}\``,
          );
          if (res.prompt_text) {
            this.editor.setText(res.prompt_text);
          }
        } else {
          infoComp.appendTextDelta(
            "⚠ 请指定要分叉的 entry_id (例如 `/fork <entry_id>`)，可使用 `/tree` 查看节点列表。",
          );
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 分叉会话失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/clone") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const res = await this.client.sendRequest<{
          status: string;
          new_session_id: string;
          session_file: string;
        }>("session_clone");
        infoComp.appendTextDelta(
          `✓ 已将当前活跃分支完整克隆为新会话: \`${res.new_session_id}\``,
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 克隆会话失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/thinking") {
      if (!argsText) {
        this.showThinkingSelector();
        return true;
      }
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const res = await this.client.sendRequest<{
          status: string;
          level: string;
        }>("thinking_set", { level: argsText.toLowerCase() });
        this.options.thinking = res.level;
        this.footer.update({ thinkingLevel: res.level });
        infoComp.appendTextDelta(`✓ 思考预算等级已调整为: \`${res.level}\``);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 设置思考深度失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/logout") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      if (argsText) {
        try {
          const res = await this.client.sendRequest<{
            status: string;
            provider: string;
            removed: boolean;
          }>("auth_logout", { provider: argsText });
          if (res.removed) {
            infoComp.appendTextDelta(
              `✓ 已成功清除 \`${res.provider}\` 的认证凭据。`,
            );
          } else {
            infoComp.appendTextDelta(
              `ℹ 未找到 \`${res.provider}\` 的已存凭据。`,
            );
          }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          infoComp.appendTextDelta(`✗ 注销凭据失败: ${msg}`);
        }
      } else {
        infoComp.appendTextDelta(
          "⚠ 请指定要注销凭据的 Provider，例如：`/logout deepseek` 或 `/logout openai`",
        );
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/reload") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const res = await this.client.sendRequest<{
          status: string;
          summary: string;
          skills_count?: number;
          templates_count?: number;
        }>("resource_reload");
        infoComp.appendTextDelta(`✓ ${res.summary || "资源热重载完成"}`);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 热重载失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/trust") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      if (argsText) {
        const lower = argsText.toLowerCase();
        const trusted =
          !lower.includes("false") &&
          !lower.includes("untrust") &&
          !lower.includes("no") &&
          !lower.includes("off");
        try {
          const res = await this.client.sendRequest<{
            status: string;
            path: string;
            trusted: boolean;
            decision: string;
          }>("trust_set", { trusted });
          infoComp.appendTextDelta(
            `✓ 项目信任状态已设置为: **${res.decision}** (\`${res.path}\`)`,
          );
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          infoComp.appendTextDelta(`✗ 设置信任状态失败: ${msg}`);
        }
      } else {
        infoComp.appendTextDelta(
          "**项目信任设置**：\n- 使用 `/trust true` 信任当前工作区\n- 使用 `/trust false` 取消信任\n信任决策记录于 `~/.my-pi-agent/trust.json`。",
        );
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/steer") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      if (argsText) {
        try {
          await this.client.steer(argsText);
          infoComp.appendTextDelta(`✓ 已成功注入转向指令: *${argsText}*`);
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

    if (cmd === "/followup") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      if (argsText) {
        try {
          await this.client.followup(argsText);
          infoComp.appendTextDelta(`✓ 已成功追加追问任务: *${argsText}*`);
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

    if (cmd === "/model") {
      if (!argsText) {
        this.showModelSelector();
        return true;
      }
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const res = await this.client.sendRequest<{
          status: string;
          model: string;
          provider?: string;
        }>("model_switch", { model: argsText });
        this.options.model = res.model;
        this.footer.update({
          modelName: res.model,
          providerName: res.provider,
        });
        infoComp.appendTextDelta(
          `✓ 已切换生效模型为 \`${res.model}\`${res.provider ? ` (${res.provider})` : ""}`,
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 切换模型失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/quota") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      infoComp.appendTextDelta(
        "✓ 当前模型配额可用。可在项目 .env 文件中维护各 Provider 的 API Key 凭证。",
      );
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/login") {
      const [provider, ...keyParts] = argParts;
      const key = keyParts.join(" ").trim();

      if (!provider || !key) {
        this.showLoginSelector();
        return true;
      }

      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      try {
        const res = (await this.client.sendRequest("login", {
          provider,
          key,
        })) as { status: string; message: string };
        infoComp.appendTextDelta(`✓ ${res.message || "凭据已保存"}`);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        infoComp.appendTextDelta(`✗ 保存凭据失败: ${msg}`);
      }
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/session") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      const ws = this.options.workspace || process.cwd();
      const model = this.options.model || "default";
      infoComp.appendTextDelta(
        [
          "**当前会话状态信息**：",
          `- **工作区目录 (Workspace)**: \`${ws}\``,
          `- **当前模型 (Model)**: \`${model}\``,
          "- **集中式存储位置**: `~/.my-pi-agent/sessions/<project-slug>-<hash>/`",
          "- **工作区零污染**: 当前项目目录下绝不写入任何 `.jsonl` 临时会话文件。",
        ].join("\n"),
      );
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd === "/settings") {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      infoComp.appendTextDelta(
        [
          "**配置系统说明 (Settings)**：",
          "- **全局配置**: `~/.my-pi-agent/settings.json`",
          "- **项目配置**: `<workspace>/.my-pi-agent/settings.json` (自动与全局深合并)",
          "- **特权安全**: `httpProxy` 与 `projectTrust` 仅限在全局配置中设定，防止恶意仓库越权。",
        ].join("\n"),
      );
      infoComp.finalize();
      this.tui.requestRender();
      return true;
    }

    if (cmd.startsWith("/")) {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
      const infoComp = new AssistantMessageComponent();
      this.chatContainer.addChild(infoComp);
      infoComp.appendTextDelta(
        `⚠ 命令 \`${cmd}\` 暂未在当前内核模式下启用，输入 \`/help\` 查看所有可用命令。`,
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

    // 1. Shell 宏即时执行 (!cmd 或 !!cmd)
    if (trimmed.startsWith("!")) {
      if (this.isBusy) {
        this.chatContainer.addChild(new UserMessageComponent(text));
        this.editor.setText("");
        this.resetEditorBorder();
        const infoComp = new AssistantMessageComponent();
        this.chatContainer.addChild(infoComp);
        infoComp.appendTextDelta(
          "⚠ 当前任务正在执行中。若需纠偏请使用 `/steer <指令>`，追加排队任务请使用 `/followup <任务>`，或按 `Esc` 打断当前执行。",
        );
        infoComp.finalize();
        this.tui.requestRender();
        return;
      }

      const isSilent = trimmed.startsWith("!!");
      const cmdToRun = isSilent
        ? trimmed.slice(2).trim()
        : trimmed.slice(1).trim();

      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();

      if (!cmdToRun) {
        const infoComp = new AssistantMessageComponent();
        this.chatContainer.addChild(infoComp);
        infoComp.appendTextDelta(
          "⚠ 请输入要执行的本地 Shell 命令，例如：`!git status` 或 `!!ls -la`",
        );
        infoComp.finalize();
        this.tui.requestRender();
        return;
      }

      const outComp = new AssistantMessageComponent();
      this.chatContainer.addChild(outComp);
      this.tui.requestRender();

      try {
        const res = await this.client.sendRequest<{
          status: string;
          output: string;
          exit_code: number;
        }>("shell_exec", {
          command: cmdToRun,
          exclude_from_context: isSilent,
        });
        const output = res.output
          ? `\`\`\`text\n${res.output}\n\`\`\``
          : "_无输出_";
        const tag = isSilent ? "(静默执行，未加入上下文)" : "(已加入上下文)";
        outComp.appendTextDelta(
          `**$ ${cmdToRun}** ${tag} (Exit: ${res.exit_code ?? 0})\n${output}`,
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        outComp.appendTextDelta(`✗ 执行 Shell 命令失败: ${msg}`);
      }
      outComp.finalize();
      this.tui.requestRender();
      return;
    }

    // 2. 内置 Slash 命令优先分发
    const [firstWord] = trimmed.split(/\s+/);
    if (trimmed.startsWith("/") && isBuiltinSlashCommand(firstWord)) {
      await this.handleSlashCommand(trimmed);
      return;
    }

    // 3. 宏展开 (/skill:<name> 或 /<template>)
    let promptText = text;
    if (trimmed.startsWith("/")) {
      if (this.isBusy) {
        this.chatContainer.addChild(new UserMessageComponent(text));
        this.editor.setText("");
        this.resetEditorBorder();
        const infoComp = new AssistantMessageComponent();
        this.chatContainer.addChild(infoComp);
        infoComp.appendTextDelta(
          "⚠ 当前任务正在执行中。若需纠偏请使用 `/steer <指令>`，追加排队任务请使用 `/followup <任务>`，或按 `Esc` 打断当前执行。",
        );
        infoComp.finalize();
        this.tui.requestRender();
        return;
      }

      try {
        const expandRes = await this.client.sendRequest<{
          status: string;
          text: string;
          expanded: boolean;
        }>("macro_expand", { text: trimmed });

        if (expandRes && expandRes.expanded) {
          promptText = expandRes.text;
        } else {
          // 既非内置命令，也未匹配到任何 Skill 或 Prompt 模板
          await this.handleSlashCommand(trimmed);
          return;
        }
      } catch {
        await this.handleSlashCommand(trimmed);
        return;
      }
    }

    // 4. 普通 Prompt 任务执行
    if (this.isBusy) {
      this.chatContainer.addChild(new UserMessageComponent(text));
      this.editor.setText("");
      this.resetEditorBorder();
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
    this.resetEditorBorder();

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
      await this.client.prompt(promptText, (event: AgentEvent) => {
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
      this.finalizeActiveTools();
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
      this.finalizeActiveTools();
    }

    this.tui.requestRender();
  }

  public showSelector(
    create: (done: () => void) => {
      component: Container & { handleInput: (data: string) => void };
      focus?: Component;
      dispose?: () => void;
    },
  ): void {
    const token = {};
    let dispose: (() => void) | undefined;

    const done = () => {
      dispose?.();
      if (this.activeSelectorToken !== token) return;
      this.activeSelectorToken = undefined;
      this.activeSelectorDispose = undefined;
      this.activeSelectorComponent = undefined;

      this.editorContainer.clear();
      this.editorContainer.addChild(this.editor);
      this.tui.setFocus(this.editor);
      this.tui.requestRender();
    };

    const created = create(done);
    dispose = created.dispose;

    this.disposeActiveSelector();
    this.activeSelectorToken = token;
    this.activeSelectorDispose = dispose;
    this.activeSelectorComponent = created.component;

    this.editorContainer.clear();
    this.editorContainer.addChild(created.component);
    if (created.focus) {
      this.tui.setFocus(created.focus);
    }
    this.tui.requestRender();
  }

  private disposeActiveSelector(): void {
    const dispose = this.activeSelectorDispose;
    this.activeSelectorToken = undefined;
    this.activeSelectorDispose = undefined;
    this.activeSelectorComponent = undefined;
    dispose?.();
  }

  public showLoginSelector(): void {
    this.showSelector((done) => {
      const selector = new LoginSelectorComponent(
        async (provider, key) => {
          done();
          try {
            const res = (await this.client.sendRequest("login", {
              provider,
              key,
            })) as { status: string; message: string };
            const infoComp = new AssistantMessageComponent();
            infoComp.appendTextDelta(
              `✓ ${res.message || "已成功绑定凭据至全局凭据中心 (~/.my-pi-agent/auth.json)"}`,
            );
            infoComp.finalize();
            this.chatContainer.addChild(infoComp);
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            const errComp = new AssistantMessageComponent();
            errComp.appendTextDelta(`✗ 保存凭据失败: ${msg}`);
            errComp.finalize();
            this.chatContainer.addChild(errComp);
          }
          this.tui.requestRender();
        },
        () => done(),
      );
      return { component: selector, focus: selector.searchInput };
    });
  }

  public showSessionSelector(): void {
    this.showSelector((done) => {
      const selector = new SessionSelectorComponent(
        async (allProjects) => {
          const res = await this.client.sendRequest<{
            status: string;
            sessions: SessionItem[];
          }>("session_list", { all_projects: allProjects });
          return res.sessions || [];
        },
        async (session) => {
          done();
          try {
            const res = await this.client.sendRequest<{
              status: string;
              session_id: string;
            }>("session_resume", { session_id: session.id });
            this.footer.update({ sessionName: session.name || session.id });
            const infoComp = new AssistantMessageComponent();
            infoComp.appendTextDelta(`✓ 已成功恢复会话: \`${res.session_id}\``);
            infoComp.finalize();
            this.chatContainer.addChild(infoComp);
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            const errComp = new AssistantMessageComponent();
            errComp.appendTextDelta(`✗ 恢复会话失败: ${msg}`);
            errComp.finalize();
            this.chatContainer.addChild(errComp);
          }
          this.tui.requestRender();
        },
        () => done(),
        () => this.tui.requestRender(),
      );
      return { component: selector, focus: selector.searchInput };
    });
  }

  public showModelSelector(initialQuery?: string): void {
    const availableModels: ModelItem[] = [
      {
        id: "deepseek-chat",
        provider: "deepseek",
        name: "DeepSeek V3",
        contextWindow: 64000,
      },
      {
        id: "deepseek-reasoner",
        provider: "deepseek",
        name: "DeepSeek R1",
        contextWindow: 64000,
      },
      {
        id: "gpt-4o",
        provider: "openai",
        name: "GPT-4o",
        contextWindow: 128000,
      },
      {
        id: "gpt-4o-mini",
        provider: "openai",
        name: "GPT-4o Mini",
        contextWindow: 128000,
      },
      {
        id: "claude-3-5-sonnet-20241022",
        provider: "anthropic",
        name: "Claude 3.5 Sonnet",
        contextWindow: 200000,
      },
      {
        id: "claude-3-5-haiku-20241022",
        provider: "anthropic",
        name: "Claude 3.5 Haiku",
        contextWindow: 200000,
      },
      {
        id: "gemini-2.5-flash",
        provider: "antigravity",
        name: "Gemini 2.5 Flash",
        contextWindow: 1000000,
      },
      {
        id: "gemini-2.5-pro",
        provider: "antigravity",
        name: "Gemini 2.5 Pro",
        contextWindow: 1000000,
      },
    ];

    this.showSelector((done) => {
      const selector = new ModelSelectorComponent(
        this.options.model || "default",
        availableModels,
        async (model) => {
          done();
          try {
            const res = await this.client.sendRequest<{
              status: string;
              model: string;
              provider?: string;
            }>("model_switch", { model: `${model.provider}/${model.id}` });
            this.options.model = res.model;
            this.footer.update({
              modelName: res.model,
              providerName: res.provider,
            });
            const info = new AssistantMessageComponent();
            info.appendTextDelta(
              `✓ 已切换生效模型为 \`${res.model}\`${res.provider ? ` (${res.provider})` : ""}`,
            );
            info.finalize();
            this.chatContainer.addChild(info);
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            const errComp = new AssistantMessageComponent();
            errComp.appendTextDelta(`✗ 切换模型失败: ${msg}`);
            errComp.finalize();
            this.chatContainer.addChild(errComp);
          }
          this.tui.requestRender();
        },
        () => done(),
        initialQuery,
        (model) => {
          done();
          this.options.model = `${model.provider}/${model.id}`;
          this.footer.update({ modelName: this.options.model });
          const info = new AssistantMessageComponent();
          info.appendTextDelta(
            `✓ 已将 \`${this.options.model}\` 设为全局默认模型`,
          );
          info.finalize();
          this.chatContainer.addChild(info);
          this.tui.requestRender();
        },
        this.options.model,
      );
      return { component: selector, focus: selector.searchInput };
    });
  }

  public showThinkingSelector(): void {
    const available = [
      "off",
      "minimal",
      "low",
      "medium",
      "high",
      "xhigh",
      "max",
    ];
    const current = this.options.thinking || "off";

    this.showSelector((done) => {
      const selector = new ThinkingSelectorComponent(
        current,
        available,
        async (lvl) => {
          done();
          try {
            const res = await this.client.sendRequest<{
              status: string;
              level: string;
            }>("thinking_set", { level: lvl.toLowerCase() });
            this.options.thinking = res.level;
            this.footer.update({ thinkingLevel: res.level });
            const info = new AssistantMessageComponent();
            info.appendTextDelta(`✓ 思考预算等级已调整为: \`${res.level}\``);
            info.finalize();
            this.chatContainer.addChild(info);
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            const errComp = new AssistantMessageComponent();
            errComp.appendTextDelta(`✗ 设置思考深度失败: ${msg}`);
            errComp.finalize();
            this.chatContainer.addChild(errComp);
          }
          this.tui.requestRender();
        },
        () => done(),
        (lvl) => {
          done();
          this.options.thinking = lvl;
          this.footer.update({ thinkingLevel: lvl });
          const info = new AssistantMessageComponent();
          info.appendTextDelta(`✓ 默认思考深度已设置为: \`${lvl}\``);
          info.finalize();
          this.chatContainer.addChild(info);
          this.tui.requestRender();
        },
        this.options.thinking,
      );
      return { component: selector, focus: selector.searchInput };
    });
  }

  public async start(): Promise<void> {
    await this.client.start();
    this.tui.start();
    if (this.options.resume === true) {
      await this.handleSlashCommand("/resume");
    } else if (typeof this.options.resume === "string" && this.options.resume) {
      await this.handleSlashCommand(`/resume ${this.options.resume}`);
    } else if (this.options.prompt) {
      void this.handleUserSubmit(this.options.prompt);
    }
    this.tui.requestRender();
  }

  public async stop(): Promise<void> {
    this.tui.stop();
    await this.client.shutdown();
  }
}
