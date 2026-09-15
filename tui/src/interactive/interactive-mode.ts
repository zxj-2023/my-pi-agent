import * as fs from "node:fs";
import * as path from "node:path";
import * as process from "node:process";
import {
  CombinedAutocompleteProvider,
  type Component,
  Container,
  Editor,
  type EditorTheme,
  matchesKey,
  type SlashCommand,
  Spacer,
  Text,
  TuiMainScreen,
} from "@earendil-works/pi-tui";
import { KernelBridge } from "../bridge/kernel-bridge.js";
import { AssistantMessageComponent } from "../components/assistant-message.js";
import { DynamicBorder } from "../components/dynamic-border.js";
import { FooterComponent } from "../components/footer.js";
import { HeaderComponent } from "../components/header.js";
import { LoginSelectorComponent } from "../components/login-selector.js";
import { type LogoutProviderItem, LogoutSelectorComponent } from "../components/logout-selector.js";
import { type ModelItem, ModelSelectorComponent } from "../components/model-selector.js";
import { type SessionItem, SessionSelectorComponent } from "../components/session-selector.js";
import { SettingsSelectorComponent } from "../components/settings-selector.js";
import { ThemeSelectorComponent } from "../components/theme-selector.js";
import { ThinkingSelectorComponent } from "../components/thinking-selector.js";
import { ToolExecutionComponent } from "../components/tool-execution.js";
import { type TreeNode, TreeSelectorComponent } from "../components/tree-selector.js";
import { UserMessageComponent } from "../components/user-message.js";
import { theme } from "../theme/theme.js";
import { createChatViewport } from "./chat-viewport.js";
import { createInteractiveTui, type InteractiveTuiOptions } from "./tui-renderer.js";

export interface InteractiveModeOptions extends InteractiveTuiOptions {
  workspace?: string;
  model?: string;
  sessionName?: string;
  thinking?: string;
  noSession?: boolean;
  continueSession?: boolean;
  resume?: string | boolean;
}

export const BUILTIN_SLASH_COMMANDS: SlashCommand[] = [
  { name: "help", description: "查看所有可用命令与快捷键说明" },
  { name: "clear", description: "清空当前终端屏幕会话" },
  { name: "new", description: "结束当前会话，开启全新的空白会话" },
  { name: "resume", description: "列出、搜索或恢复指定历史会话", argumentHint: "[session_id]" },
  { name: "name", description: "查看或设置当前会话的显示名称", argumentHint: "[title]" },
  { name: "compact", description: "立即对当前上下文执行压缩，释放 Token 空间", argumentHint: "[instructions]" },
  { name: "tree", description: "以可视化 DAG 树状图展现会话分支拓扑" },
  { name: "fork", description: "基于当前节点创建全新分支", argumentHint: "[node_id]" },
  { name: "clone", description: "深度克隆当前分支，开辟全新探索副本" },
  { name: "model", description: "交互式查看与切换当前使用的语言模型", argumentHint: "[model_id]" },
  { name: "thinking", description: "调整模型思考预算深度等级 (off/minimal/low/medium/high/xhigh/max)", argumentHint: "[level]" },
  { name: "login", description: "两阶段交互式绑定 Provider API Key" },
  { name: "logout", description: "清除指定 Provider 的已存 API 密钥凭据", argumentHint: "[provider]" },
  { name: "theme", description: "实时预览并切换终端 TrueColor 主题方案" },
  { name: "settings", description: "交互式管理模型与运行时核心参数" },
  { name: "steer", description: "向运行中的智能体插话或修正方向", argumentHint: "<instruction>" },
  { name: "followup", description: "添加后续任务指令，在当前任务结束后执行", argumentHint: "<instruction>" },
  { name: "reload", description: "重新载入所有动态 Skills 与 Prompt 模板" },
  { name: "trust", description: "查看或更新当前工作区的代码执行信任安全策略", argumentHint: "[true|false]" },
];

function findFdPath(): string | undefined {
  const envPath = process.env.PATH || "";
  const paths = envPath.split(path.delimiter);
  const isWindows = process.platform === "win32";
  const names = isWindows ? ["fd.exe", "fdfind.exe"] : ["fd", "fdfind"];

  for (const dir of paths) {
    for (const name of names) {
      const fullPath = path.join(dir, name);
      try {
        if (fs.existsSync(fullPath)) {
          return fullPath;
        }
      } catch {
        // ignore
      }
    }
  }
  return undefined;
}

export class InteractiveMode {
  public readonly ui: TuiMainScreen;
  public readonly chatContainer: Container;
  public readonly documentContainer: Container;
  public readonly pendingMessagesContainer: Container;
  public readonly statusContainer: Container;
  public readonly editorContainer: Container;
  public readonly defaultEditor: Editor;
  public readonly footer: FooterComponent;
  public readonly header: HeaderComponent;
  public readonly dynamicBorder: DynamicBorder;

  private activeSelectorToken?: object;
  private activeSelectorDispose?: () => void;
  public activeSelectorComponent?: any;

  public currentStreamingAssistant?: AssistantMessageComponent;
  public activeToolCalls = new Map<string, ToolExecutionComponent>();
  public isStreaming = false;
  public isWorking = false;
  public currentThinkingLevel = "off";
  public currentModelName = "default";
  public workspace: string;
  private unsubscribeBridge?: () => void;

  constructor(
    public readonly bridge: KernelBridge,
    public readonly options: InteractiveModeOptions = {},
  ) {
    this.workspace = options.workspace || process.cwd();
    this.currentModelName = options.model || "default";
    this.currentThinkingLevel = options.thinking || "off";

    // 1. 初始化终端 UI 宿主
    this.ui = createInteractiveTui({
      tuiMode: options.tuiMode || "regular",
      showHardwareCursor: options.showHardwareCursor ?? false,
      logDirectory: options.logDirectory || "",
    }) as TuiMainScreen;

    // 2. 初始化核心布局容器
    this.documentContainer = new Container();
    this.chatContainer = new Container();
    this.header = new HeaderComponent("0.1.0");
    this.dynamicBorder = new DynamicBorder();

    this.documentContainer.addChild(this.header);
    this.documentContainer.addChild(new Spacer(1));
    this.documentContainer.addChild(this.chatContainer);

    this.pendingMessagesContainer = new Container();
    this.statusContainer = new Container();
    this.editorContainer = new Container();

    // 3. 初始化 Footer
    this.footer = new FooterComponent({
      workspace: this.workspace,
      modelName: this.currentModelName,
      thinkingLevel: this.currentThinkingLevel,
      sessionName: options.sessionName,
    });

    // 4. 初始化 Editor 与 Autocomplete
    this.defaultEditor = this.createEditor();
    this.editorContainer.addChild(this.defaultEditor);

    // 5. 挂载 ChatViewport 视口
    const viewport = createChatViewport({
      document: this.documentContainer,
      pendingMessages: this.pendingMessagesContainer,
      status: this.statusContainer,
      editor: this.editorContainer,
      footer: this.footer,
    });
    this.ui.addChild(viewport.root);
    this.ui.setFocus(this.defaultEditor);
  }

  public async init(): Promise<void> {
    // 1. 订阅 KernelBridge 事件
    this.subscribeToBridge();

    // 2. 注册终端按键拦截
    this.setupKeybindings();

    // 3. 欢迎提示
    this.appendSystemNotice("欢迎使用 my-pi-agent！输入需求或按 / 开启命令菜单。");

    // 4. 首次启动刷新
    this.ui.requestRender();
  }

  public stop(): void {
    if (this.unsubscribeBridge) {
      this.unsubscribeBridge();
      this.unsubscribeBridge = undefined;
    }
    this.ui.stop();
  }

  // --------------------------------------------------------------------------
  // 事件处理与流式分发
  // --------------------------------------------------------------------------

  private subscribeToBridge(): void {
    this.unsubscribeBridge = this.bridge.subscribe((event: any) => {
      this.handleAgentEvent(event);
    });
  }

  public handleAgentEvent(event: any): void {
    if (!event || !event.type) return;

    switch (event.type) {
      case "agent_start": {
        this.isStreaming = true;
        this.isWorking = true;
        this.activeToolCalls.clear();
        this.currentStreamingAssistant = undefined;
        this.updateStatusDisplay("思考与规划中...");
        break;
      }

      case "turn_start": {
        this.isWorking = true;
        this.updateStatusDisplay(`执行迭代轮次: ${event.iteration ?? 1}`);
        break;
      }

      case "message_start": {
        if (event.message?.role === "assistant") {
          this.currentStreamingAssistant = new AssistantMessageComponent();
          this.chatContainer.addChild(this.currentStreamingAssistant);
          this.chatContainer.addChild(new Spacer(1));
        }
        break;
      }

      case "message_update": {
        if (!this.currentStreamingAssistant) {
          this.currentStreamingAssistant = new AssistantMessageComponent();
          this.chatContainer.addChild(this.currentStreamingAssistant);
          this.chatContainer.addChild(new Spacer(1));
        }

        // 解析 message.content 中的 thinking 与 text 块
        if (Array.isArray(event.message?.content)) {
          for (const block of event.message.content) {
            if (block.type === "thinking" && block.thinking) {
              this.currentStreamingAssistant.appendReasoningDelta(block.thinking);
            } else if (block.type === "text" && block.text) {
              this.currentStreamingAssistant.appendTextDelta(block.text);
            }
          }
        }
        break;
      }

      case "message_end": {
        if (this.currentStreamingAssistant) {
          this.currentStreamingAssistant.finalize();
          this.currentStreamingAssistant = undefined;
        }
        break;
      }

      case "tool_execution_start": {
        const id = event.toolCallId || `tc-${Date.now()}`;
        const name = event.toolName || "tool";
        const args = event.args || {};
        const toolComponent = new ToolExecutionComponent(name, id, args);
        this.activeToolCalls.set(id, toolComponent);
        this.chatContainer.addChild(toolComponent);
        this.chatContainer.addChild(new Spacer(1));
        this.updateStatusDisplay(`正在执行工具: ${name}...`);
        break;
      }

      case "tool_execution_update": {
        const id = event.toolCallId;
        const toolComponent = this.activeToolCalls.get(id);
        if (toolComponent && event.partialResult) {
          toolComponent.updateResult(event.partialResult, false);
        }
        break;
      }

      case "tool_execution_end": {
        const id = event.toolCallId;
        const toolComponent = this.activeToolCalls.get(id);
        if (toolComponent) {
          toolComponent.updateResult(event.result, !!event.isError);
          this.activeToolCalls.delete(id);
        }
        this.clearStatusDisplay();
        break;
      }

      case "turn_end": {
        this.isWorking = false;
        this.clearStatusDisplay();
        break;
      }

      case "agent_end": {
        this.isStreaming = false;
        this.isWorking = false;
        if (this.currentStreamingAssistant) {
          this.currentStreamingAssistant.finalize();
          this.currentStreamingAssistant = undefined;
        }
        this.clearStatusDisplay();
        this.footer.update({ isBusy: false });
        break;
      }

      case "context_compacted": {
        this.appendSystemNotice(
          `✓ 上下文已压缩: ${event.tokensBefore ?? 0} -> ${event.tokensAfter ?? 0} tokens`,
        );
        break;
      }
    }

    this.ui.requestRender();
  }

  // --------------------------------------------------------------------------
  // 编辑器与输入提交
  // --------------------------------------------------------------------------

  private createEditor(): Editor {
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

    const editor = new Editor(this.ui, editorTheme);

    const fdPath = findFdPath();
    const autocompleteProvider = new CombinedAutocompleteProvider(
      BUILTIN_SLASH_COMMANDS,
      this.workspace,
      fdPath,
    );
    editor.setAutocompleteProvider(autocompleteProvider);

    editor.onSubmit = async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      editor.setText("");
      await this.handleUserInput(trimmed);
    };

    return editor;
  }

  public async handleUserInput(input: string): Promise<void> {
    // 1. 处理斜杠命令
    if (input.startsWith("/")) {
      await this.handleSlashCommand(input);
      return;
    }

    // 2. 处理 Shell 快捷命令 !cmd 或 !!cmd
    if (input.startsWith("!")) {
      await this.handleShellMacro(input);
      return;
    }

    // 3. 普通文本输入：渲染用户气泡并提交给 Python
    const userMsg = new UserMessageComponent(input);
    this.chatContainer.addChild(userMsg);
    this.chatContainer.addChild(new Spacer(1));
    this.ui.requestRender();

    try {
      this.footer.update({ isBusy: true });
      await this.bridge.prompt(input);
    } catch (err: any) {
      this.appendErrorMessage(`请求失败: ${err.message || String(err)}`);
    }
  }

  // --------------------------------------------------------------------------
  // 快捷键拦截与生命周期
  // --------------------------------------------------------------------------

  private setupKeybindings(): void {
    this.ui.addInputListener((data: string) => {
      // 若当前挂载了活动的 Selector，直接委托给 Selector 处理键盘事件
      if (this.activeSelectorComponent) {
        this.activeSelectorComponent.handleInput?.(data);
        this.ui.requestRender();
        return undefined;
      }

      if (matchesKey(data, "ctrl+c")) {
        if (this.isStreaming) {
          void this.bridge.abort();
          this.appendSystemNotice("执行已中断。");
          this.ui.requestRender();
        } else {
          void this.stop();
          process.exit(0);
        }
      } else if (matchesKey(data, "escape")) {
        if (this.isStreaming) {
          void this.bridge.abort();
          this.appendSystemNotice("执行已中断。");
          this.ui.requestRender();
        }
      } else if (matchesKey(data, "ctrl+o")) {
        if (this.currentStreamingAssistant) {
          this.currentStreamingAssistant.toggleThinking();
        }
        for (const tool of this.activeToolCalls.values()) {
          tool.toggleExpanded();
        }
        this.ui.requestRender();
      } else if (matchesKey(data, "ctrl+m")) {
        this.showModelSelector();
        return undefined;
      } else if (matchesKey(data, "ctrl+r")) {
        this.showSessionSelector();
        return undefined;
      }
      return undefined;
    });
  }

  // --------------------------------------------------------------------------
  // 动态选择器与视口抽换 (showSelector)
  // --------------------------------------------------------------------------

  public showSelector(
    create: (done: () => void) => {
      component: Component;
      focus: Component;
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
      this.editorContainer.addChild(this.defaultEditor);
      this.ui.setFocus(this.defaultEditor);
      this.ui.requestRender();
    };

    const created = create(done);
    dispose = created.dispose;

    this.disposeActiveSelector();
    this.activeSelectorToken = token;
    this.activeSelectorDispose = dispose;
    this.activeSelectorComponent = created.component;

    this.editorContainer.clear();
    this.editorContainer.addChild(created.component);
    this.ui.setFocus(created.focus);
    this.ui.requestRender();
  }

  private disposeActiveSelector(): void {
    if (this.activeSelectorDispose) {
      this.activeSelectorDispose();
      this.activeSelectorDispose = undefined;
      this.activeSelectorToken = undefined;
      this.activeSelectorComponent = undefined;
    }
  }

  // --------------------------------------------------------------------------
  // 常用选择器封装
  // --------------------------------------------------------------------------

  public showModelSelector(): void {
    this.showSelector((done) => {
      const selector = new ModelSelectorComponent(
        this.currentModelName,
        async (_all: boolean) => {
          const res = await this.bridge.listModels();
          return ((res as any)?.models || []).map((m: any) => ({
            id: m.id || m.name,
            name: m.name || m.id,
            provider: m.provider || "default",
            contextWindow: m.context_window || 128000,
            is_configured: m.is_configured ?? true,
          }));
        },
        async (selected: ModelItem) => {
          done();
          if (selected) {
            this.currentModelName = selected.id;
            this.footer.update({ modelName: selected.id, providerName: selected.provider });
            await this.bridge.switchModel(selected.id, selected.provider);
            this.appendSystemNotice(`✓ 已成功切换至模型: ${selected.id} (${selected.provider})`);
          }
        },
        () => done(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showSessionSelector(): void {
    this.showSelector((done) => {
      const selector = new SessionSelectorComponent(
        async (_allProjects: boolean) => {
          const res = await this.bridge.listSessions();
          return ((res as any)?.sessions || []).map((s: any) => ({
            id: s.session_id || s.id,
            name: s.title || s.name || s.session_id,
            modified: s.updated_at ? Math.floor(s.updated_at / 1000) : Math.floor(Date.now() / 1000),
            cwd: s.workspace || this.workspace,
            message_count: s.message_count || 0,
          }));
        },
        async (session: SessionItem) => {
          done();
          if (session) {
            await this.bridge.resumeSession(session.id);
            this.appendSystemNotice(`✓ 已成功恢复会话: ${session.id}`);
          }
        },
        () => done(),
        () => this.ui.requestRender(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showThinkingSelector(): void {
    const levels = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
    this.showSelector((done) => {
      const selector = new ThinkingSelectorComponent(
        this.currentThinkingLevel,
        levels,
        async (level: string) => {
          done();
          if (level) {
            this.currentThinkingLevel = level;
            this.footer.update({ thinkingLevel: level });
            await this.bridge.setThinking(level);
            this.appendSystemNotice(`✓ 思考预算等级已调整为: ${level}`);
          }
        },
        () => done(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showLoginSelector(): void {
    this.showSelector((done) => {
      const selector = new LoginSelectorComponent(
        async (provider: string, key: string) => {
          done();
          await this.bridge.login(provider, key);
          this.appendSystemNotice(`✓ 已成功为 ${provider} 绑定 API 密钥。`);
        },
        () => done(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showLogoutSelector(): void {
    this.showSelector((done) => {
      const defaultProviders: LogoutProviderItem[] = [
        { id: "deepseek", label: "DeepSeek", description: "deepseek API key" },
        { id: "openai", label: "OpenAI", description: "openai API key" },
        { id: "anthropic", label: "Anthropic", description: "anthropic API key" },
        { id: "antigravity", label: "Antigravity", description: "oauth credential" },
      ];
      const selector = new LogoutSelectorComponent(
        defaultProviders,
        async (providerId: string) => {
          done();
          await this.bridge.logout(providerId);
          this.appendSystemNotice(`✓ 已成功注销 ${providerId} 的凭据。`);
        },
        () => done(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showThemeSelector(): void {
    this.showSelector((done) => {
      const selector = new ThemeSelectorComponent(
        "dark",
        ["dark", "light"],
        (themeName: string) => {
          done();
          this.appendSystemNotice(`✓ 主题已切换至: ${themeName}`);
        },
        () => done(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showTreeSelector(): void {
    this.showSelector((done) => {
      const selector = new TreeSelectorComponent(
        async () => {
          const res = await this.bridge.getTree();
          return ((res as any)?.tree || []) as TreeNode[];
        },
        async (node: TreeNode) => {
          done();
          await this.bridge.branchSession(node.id);
          this.appendSystemNotice(`✓ 已切换至分支节点: ${node.id}`);
        },
        () => done(),
        undefined,
        () => this.ui.requestRender(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showSettingsSelector(): void {
    this.showSelector((done) => {
      const selector = new SettingsSelectorComponent(
        {},
        async (key: string, value: unknown) => {
          await this.bridge.setSetting(key, value);
        },
        () => done(),
      );
      return { component: selector, focus: selector };
    });
  }

  // --------------------------------------------------------------------------
  // 斜杠命令分发
  // --------------------------------------------------------------------------

  public async handleSlashCommand(input: string): Promise<void> {
    const parts = input.slice(1).split(" ");
    const cmd = (parts[0] || "").toLowerCase();
    const args = parts.slice(1).join(" ").trim();

    switch (cmd) {
      case "clear": {
        this.chatContainer.clear();
        this.ui.requestRender();
        break;
      }
      case "help": {
        this.appendSystemNotice("可用命令列表：\n" +
          BUILTIN_SLASH_COMMANDS.map((c) => `  /${c.name.padEnd(12)} - ${c.description}`).join("\n"));
        break;
      }
      case "model": {
        if (args) {
          this.currentModelName = args;
          this.footer.update({ modelName: args });
          await this.bridge.switchModel(args);
          this.appendSystemNotice(`✓ 已切换至模型: ${args}`);
        } else {
          this.showModelSelector();
        }
        break;
      }
      case "resume":
      case "session": {
        if (args) {
          await this.bridge.resumeSession(args);
          this.appendSystemNotice(`✓ 已恢复会话: ${args}`);
        } else {
          this.showSessionSelector();
        }
        break;
      }
      case "thinking": {
        if (args) {
          this.currentThinkingLevel = args;
          this.footer.update({ thinkingLevel: args });
          await this.bridge.setThinking(args);
          this.appendSystemNotice(`✓ 思考预算已更新为: ${args}`);
        } else {
          this.showThinkingSelector();
        }
        break;
      }
      case "login": {
        this.showLoginSelector();
        break;
      }
      case "logout": {
        this.showLogoutSelector();
        break;
      }
      case "theme": {
        this.showThemeSelector();
        break;
      }
      case "tree": {
        this.showTreeSelector();
        break;
      }
      case "settings": {
        this.showSettingsSelector();
        break;
      }
      case "new": {
        await this.bridge.newSession();
        this.chatContainer.clear();
        this.appendSystemNotice("✓ 已开启全新的空白会话。");
        break;
      }
      case "steer": {
        if (args) {
          await this.bridge.steer(args);
          this.appendSystemNotice(`[Steer 提示已注入]: ${args}`);
        }
        break;
      }
      case "followup": {
        if (args) {
          await this.bridge.followUp(args);
          this.appendSystemNotice(`[Followup 任务已排队]: ${args}`);
        }
        break;
      }
      default: {
        this.appendErrorMessage(`未知命令 /${cmd}，输入 /help 查看可用命令。`);
      }
    }
  }

  private async handleShellMacro(input: string): Promise<void> {
    const isSilent = input.startsWith("!!");
    const rawCmd = input.replace(/^!!?/, "").trim();
    if (!rawCmd) {
      this.appendErrorMessage("请输入有效的 Shell 命令，例如: !git status");
      return;
    }
    this.appendSystemNotice(`$ ${rawCmd} (${isSilent ? "静默执行" : "加入上下文"})`);
    // 交给 bridge 或本地执行
  }

  // --------------------------------------------------------------------------
  // 辅助渲染方法
  // --------------------------------------------------------------------------

  public appendSystemNotice(text: string): void {
    const notice = new Text(theme.fg("accent", text), 1, 0);
    this.chatContainer.addChild(notice);
    this.chatContainer.addChild(new Spacer(1));
    this.ui.requestRender();
  }

  public appendErrorMessage(text: string): void {
    const errorNotice = new Text(theme.fg("error", `⚠ ${text}`), 1, 0);
    this.chatContainer.addChild(errorNotice);
    this.chatContainer.addChild(new Spacer(1));
    this.ui.requestRender();
  }

  private updateStatusDisplay(text: string): void {
    this.statusContainer.clear();
    const statusText = new Text(theme.fg("dim", `◈ ${text}`), 1, 0);
    this.statusContainer.addChild(statusText);
    this.ui.requestRender();
  }

  private clearStatusDisplay(): void {
    this.statusContainer.clear();
    this.ui.requestRender();
  }
}
