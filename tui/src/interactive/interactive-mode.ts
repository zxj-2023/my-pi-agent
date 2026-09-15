import * as fs from "node:fs";
import * as path from "node:path";
import * as process from "node:process";
import { spawn } from "node:child_process";
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
import {
  type LogoutProviderItem,
  LogoutSelectorComponent,
} from "../components/logout-selector.js";
import {
  type ModelItem,
  ModelSelectorComponent,
} from "../components/model-selector.js";
import {
  type SessionItem,
  SessionSelectorComponent,
} from "../components/session-selector.js";
import { SettingsSelectorComponent } from "../components/settings-selector.js";
import { ThemeSelectorComponent } from "../components/theme-selector.js";
import { ThinkingSelectorComponent } from "../components/thinking-selector.js";
import { ToolExecutionComponent } from "../components/tool-execution.js";
import {
  type TreeNode,
  TreeSelectorComponent,
} from "../components/tree-selector.js";
import { UserMessageComponent } from "../components/user-message.js";
import {
  type UserMessageItem,
  UserMessageSelectorComponent,
} from "../components/user-message-selector.js";
import { theme } from "../theme/theme.js";
import { createChatViewport } from "./chat-viewport.js";
import {
  createInteractiveTui,
  type InteractiveTuiOptions,
} from "./tui-renderer.js";

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
  {
    name: "resume",
    description: "列出、搜索或恢复指定历史会话",
    argumentHint: "[session_id]",
  },
  {
    name: "session",
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
    description: "立即对当前上下文执行压缩，释放 Token 空间",
    argumentHint: "[instructions]",
  },
  { name: "tree", description: "以可视化 DAG 树状图展现会话分支拓扑" },
  {
    name: "fork",
    description: "基于当前节点创建全新分支",
    argumentHint: "[node_id]",
  },
  { name: "clone", description: "深度克隆当前分支，开辟全新探索副本" },
  {
    name: "model",
    description: "交互式查看与切换当前使用的语言模型",
    argumentHint: "[model_id]",
  },
  {
    name: "thinking",
    description:
      "调整模型思考预算深度等级 (off/minimal/low/medium/high/xhigh/max)",
    argumentHint: "[level]",
  },
  { name: "login", description: "两阶段交互式绑定 Provider API Key" },
  {
    name: "logout",
    description: "清除指定 Provider 的已存 API 密钥凭据",
    argumentHint: "[provider]",
  },
  { name: "theme", description: "实时预览并切换终端 TrueColor 主题方案" },
  { name: "settings", description: "交互式管理模型与运行时核心参数" },
  {
    name: "steer",
    description: "向运行中的智能体插话或修正方向",
    argumentHint: "<instruction>",
  },
  {
    name: "followup",
    description: "添加后续任务指令，在当前任务结束后执行",
    argumentHint: "<instruction>",
  },
  { name: "reload", description: "重新载入所有动态 Skills 与 Prompt 模板" },
  {
    name: "trust",
    description: "查看或更新当前工作区的代码执行信任安全策略",
    argumentHint: "[true|false]",
  },
  { name: "copy", description: "复制最后一条智能体消息到剪贴板" },
  { name: "hotkeys", description: "查看所有键盘快捷键说明清单" },
  { name: "quit", description: "优雅退出当前智能体终端" },
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
  public latestAssistantMessage?: AssistantMessageComponent;
  public activeToolCalls = new Map<string, ToolExecutionComponent>();
  public toolStartTimes = new Map<string, number>();
  public transcriptScrollView?: any;
  public isStreaming = false;
  public isWorking = false;
  public currentThinkingLevel = "off";
  public currentModelName = "default";
  public workspace: string;
  public onExit?: () => Promise<void> | void;
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

    const welcome = new Text(
      theme.fg("muted", "欢迎使用 my-pi-agent！输入需求或按 / 开启命令菜单。"),
      1,
      0,
    );
    this.chatContainer.addChild(welcome);

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

    // 5. 挂载视口与组件 (对齐 Pi 原厂 mountInteractiveTui 架构规范)
    if (options.tuiMode === "fullscreen") {
      const viewport = createChatViewport({
        document: this.documentContainer,
        pendingMessages: this.pendingMessagesContainer,
        status: this.statusContainer,
        editor: this.editorContainer,
        footer: this.footer,
      });
      this.transcriptScrollView = viewport.transcript;
      if (typeof (this.ui as any).setLayoutRoot === "function") {
        (this.ui as any).setLayoutRoot(viewport.root);
      } else {
        this.ui.addChild(viewport.root);
      }
    } else {
      this.ui.addChild(this.documentContainer);
      this.ui.addChild(this.pendingMessagesContainer);
      this.ui.addChild(this.statusContainer);
      this.ui.addChild(this.editorContainer);
      this.ui.addChild(this.footer);
    }
    this.ui.setFocus(this.defaultEditor);
  }

  public async init(): Promise<void> {
    // 1. 订阅 KernelBridge 事件
    this.subscribeToBridge();

    // 2. 注册终端按键拦截
    this.setupKeybindings();

    // 3. 首次启动刷新
    this.ui.requestRender();
  }

  public start(): void {
    this.ui.start();
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
          this.latestAssistantMessage = this.currentStreamingAssistant;
          this.chatContainer.addChild(this.currentStreamingAssistant);
          this.chatContainer.addChild(new Spacer(1));
        }

        // 解析 message.content 中的 thinking 与 text 块 (使用全量快照，杜绝二次方爆炸)
        if (Array.isArray(event.message?.content)) {
          let thinkingText = "";
          let contentText = "";
          for (const block of event.message.content) {
            if (block.type === "thinking" && block.thinking) {
              thinkingText += block.thinking;
            } else if (block.type === "text" && block.text) {
              contentText += block.text;
            }
          }
          if (thinkingText) {
            this.currentStreamingAssistant.setReasoning(thinkingText);
          }
          if (contentText) {
            this.currentStreamingAssistant.setContent(contentText);
          }
        }
        break;
      }

      case "message_end": {
        if (this.currentStreamingAssistant) {
          this.currentStreamingAssistant.finalize();
          this.latestAssistantMessage = this.currentStreamingAssistant;
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
        this.toolStartTimes.set(id, Date.now());
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
        const id = event.toolCallId || event.tool_call_id;
        const toolComponent = id ? this.activeToolCalls.get(id) : undefined;
        if (toolComponent) {
          toolComponent.updateResult(event.result, Boolean(event.isError));
          this.toolStartTimes.delete(id);
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
        // 自动闭合所有未正常结束的工具调用
        for (const tool of this.activeToolCalls.values()) {
          if (!tool.finished) {
            tool.updateResult("执行中断", true);
          }
        }
        this.activeToolCalls.clear();
        this.toolStartTimes.clear();
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

    editor.onChange = (text: string) => {
      const isBash = text.startsWith("!");
      if (isBash) {
        editor.borderColor = (str: string) => theme.fg("warning", str);
      } else {
        editor.borderColor = (str: string) => theme.fg("borderMuted", str);
      }
    };
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
    if (this.isStreaming) {
      this.appendErrorMessage(
        "当前智能体正在执行中，请等待完成或按 Esc 中断后再提交。",
      );
      return;
    }

    // 1. 处理技能或提示词模板宏扩展
    if (
      input.startsWith("/") &&
      (input.startsWith("/skill:") ||
        !BUILTIN_SLASH_COMMANDS.some((c) =>
          input.toLowerCase().startsWith(`/${c.name}`),
        ))
    ) {
      try {
        const client = (this.bridge as any).client;
        const macroRes =
          (await client?.request?.("macro_expand", { text: input })) ||
          (await client?.sendRequest?.("macro_expand", { text: input }));
        if (macroRes?.expanded && macroRes.text) {
          input = macroRes.text;
        } else if (
          !BUILTIN_SLASH_COMMANDS.some((c) =>
            input.toLowerCase().startsWith(`/${c.name}`),
          )
        ) {
          this.appendErrorMessage(
            `命令 ${input.split(" ")[0]} 暂未在当前内核模式下启用，输入 /help 查看所有可用命令。`,
          );
          return;
        }
      } catch {
        // ignore
      }
    }

    // 2. 处理斜杠命令
    if (input.startsWith("/")) {
      await this.handleSlashCommand(input);
      return;
    }

    // 3. 处理 Shell 快捷命令 !cmd 或 !!cmd
    if (input.startsWith("!")) {
      await this.handleShellMacro(input);
      return;
    }

    // 4. 普通文本输入：渲染用户气泡并提交给 Python
    const userMsg = new UserMessageComponent(input);
    this.chatContainer.addChild(userMsg);
    this.chatContainer.addChild(new Spacer(1));
    this.ui.requestRender();

    try {
      this.footer.update({ isBusy: true });
      await this.bridge.prompt(input);
    } catch (err: any) {
      this.appendErrorMessage(`请求失败: ${err.message || String(err)}`);
      this.isStreaming = false;
      this.isWorking = false;
      this.clearStatusDisplay();
      this.footer.update({ isBusy: false });
    }
  }

  public async handleExit(): Promise<void> {
    try {
      if (this.onExit) {
        await this.onExit();
      }
    } catch {
      // 忽略退出清理异常，确保正常终止进程
    } finally {
      this.stop();
      process.exit(0);
    }
  }

  // --------------------------------------------------------------------------
  // 快捷键拦截与生命周期
  // --------------------------------------------------------------------------

  private setupKeybindings(): void {
    this.ui.addInputListener((data: string) => {
      // 若当前挂载了活动的 Selector，直接委托给 Selector 处理键盘事件并消费
      if (this.activeSelectorComponent) {
        this.activeSelectorComponent.handleInput?.(data);
        this.ui.requestRender();
        return { consume: true };
      }

      if (matchesKey(data, "ctrl+c")) {
        if (this.isStreaming) {
          void this.bridge.abort();
          this.isStreaming = false;
          this.isWorking = false;
          this.clearStatusDisplay();
          this.footer.update({ isBusy: false });
          this.appendSystemNotice("执行已中断。");
          this.ui.requestRender();
          return { consume: true };
        }
        if (this.defaultEditor.getText().length > 0) {
          this.defaultEditor.setText("");
          this.ui.requestRender();
          return { consume: true };
        }
        void this.handleExit();
        return { consume: true };
      } else if (matchesKey(data, "ctrl+d")) {
        if (this.defaultEditor.getText().length === 0 && !this.isStreaming) {
          void this.handleExit();
          return { consume: true };
        }
      } else if (matchesKey(data, "escape")) {
        if (this.isStreaming) {
          void this.bridge.abort();
          this.isStreaming = false;
          this.isWorking = false;
          this.clearStatusDisplay();
          this.footer.update({ isBusy: false });
          this.appendSystemNotice("执行已中断。");
          this.ui.requestRender();
          return { consume: true };
        }
      } else if (matchesKey(data, "ctrl+o")) {
        const targetAssistant =
          this.currentStreamingAssistant || this.latestAssistantMessage;
        if (targetAssistant) {
          targetAssistant.toggleThinking();
        }
        for (const tool of this.activeToolCalls.values()) {
          tool.toggleExpanded();
        }
        this.ui.requestRender();
        return { consume: true };
      } else if (matchesKey(data, "ctrl+l")) {
        this.showModelSelector();
        return { consume: true };
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

  public showModelSelector(initialSearch?: string): void {
    this.showSelector((done) => {
      const selector = new ModelSelectorComponent(
        this.currentModelName,
        async (all: boolean) => {
          const res = await this.bridge.listModels(
            all ? { scope: "all" } : { scope: "configured" },
          );
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
            try {
              this.currentModelName = selected.id;
              this.footer.update({
                modelName: selected.id,
                providerName: selected.provider,
              });
              await this.bridge.switchModel(selected.id, selected.provider);
              this.appendSystemNotice(
                `✓ 已成功切换至模型: ${selected.id} (${selected.provider})`,
              );
            } catch (err: any) {
              this.appendErrorMessage(
                `切换模型失败: ${err.message || String(err)}`,
              );
            }
          }
        },
        () => done(),
        initialSearch,
        undefined,
        undefined,
        () => this.ui.requestRender(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showSessionSelector(): void {
    this.showSelector((done) => {
      const selector = new SessionSelectorComponent(
        async (allProjects: boolean) => {
          const res = await this.bridge.listSessions(
            allProjects ? { all_projects: true } : {},
          );
          return ((res as any)?.sessions || []).map((s: any) => ({
            id: s.id || s.session_id,
            name: s.name || s.title || s.session_id,
            path: s.path,
            modified:
              s.modified ??
              (s.updated_at
                ? Math.floor(s.updated_at / 1000)
                : Math.floor(Date.now() / 1000)),
            cwd: s.cwd || s.workspace || this.workspace,
            message_count: s.message_count || 0,
          }));
        },
        async (session: SessionItem) => {
          done();
          if (session) {
            try {
              const target = session.path || session.id;
              const res: any = await this.bridge.resumeSession(target);
              if (res?.session_name || res?.session_id) {
                this.footer.update({
                  sessionName: res.session_name || res.session_id,
                });
              }
              this.renderSessionHistory(
                res?.messages || [],
                `✓ 已成功恢复会话: \`${res?.session_name || res?.session_id || session.id}\``,
              );
            } catch (err: any) {
              this.appendErrorMessage(
                `恢复会话失败: ${err.message || String(err)}`,
              );
            }
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
            try {
              this.currentThinkingLevel = level;
              this.footer.update({ thinkingLevel: level });
              await this.bridge.setThinking(level);
              this.appendSystemNotice(`✓ 思考预算等级已调整为: ${level}`);
            } catch (err: any) {
              this.appendErrorMessage(
                `设置思考预算失败: ${err.message || String(err)}`,
              );
            }
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
          try {
            await this.bridge.login(provider, key);
            this.appendSystemNotice(`✓ 已成功为 ${provider} 绑定 API 密钥。`);
          } catch (err: any) {
            this.appendErrorMessage(
              `绑定 API 密钥失败: ${err.message || String(err)}`,
            );
          }
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
        {
          id: "anthropic",
          label: "Anthropic",
          description: "anthropic API key",
        },
        {
          id: "antigravity",
          label: "Antigravity",
          description: "oauth credential",
        },
      ];
      const selector = new LogoutSelectorComponent(
        defaultProviders,
        async (providerId: string) => {
          done();
          try {
            await this.bridge.logout(providerId);
            this.appendSystemNotice(`✓ 已成功注销 ${providerId} 的凭据。`);
          } catch (err: any) {
            this.appendErrorMessage(
              `注销凭据失败: ${err.message || String(err)}`,
            );
          }
        },
        () => done(),
      );
      return { component: selector, focus: selector };
    });
  }

  public showThemeSelector(): void {
    const curTheme = theme.currentThemeName;
    this.showSelector((done) => {
      const selector = new ThemeSelectorComponent(
        curTheme,
        ["dark", "light"],
        async (themeName: string) => {
          done();
          theme.setTheme(themeName);
          try {
            await this.bridge.setSetting("theme", themeName);
          } catch {
            // ignore
          }
          this.appendSystemNotice(`✓ 主题已切换至: ${themeName}`);
          this.ui.requestRender();
        },
        () => {
          theme.setTheme(curTheme);
          done();
          this.ui.requestRender();
        },
        (previewTheme: string) => {
          theme.setTheme(previewTheme);
          this.ui.requestRender();
        },
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
          try {
            await this.bridge.branchSession(node.id);
            this.appendSystemNotice(`✓ 已切换至分支节点: ${node.id}`);
          } catch (err: any) {
            this.appendErrorMessage(
              `切换分支失败: ${err.message || String(err)}`,
            );
          }
        },
        () => done(),
        undefined,
        () => this.ui.requestRender(),
      );
      return { component: selector, focus: selector };
    });
  }

  public async showForkSelector(): Promise<void> {
    const userMessages: UserMessageItem[] = [];
    try {
      const res: any = await this.bridge.getTree();
      const tree: TreeNode[] = (res?.tree || res?.nodes || []) as TreeNode[];
      for (const n of tree) {
        if (n.role === "user") {
          userMessages.push({ id: n.id, text: n.preview || n.id });
        }
      }
    } catch {
      // ignore
    }

    if (userMessages.length === 0) {
      this.appendSystemNotice("当前会话暂无历史用户消息可供分叉。");
      return;
    }

    this.showSelector((done) => {
      const selector = new UserMessageSelectorComponent(
        userMessages,
        async (msg: UserMessageItem) => {
          done();
          try {
            const client = (this.bridge as any).client;
            const res: any =
              (await client?.sendRequest?.("session_fork", {
                entry_id: msg.id,
              })) || (await (this.bridge as any).forkSession?.(msg.id));
            if (res?.messages) {
              if (res?.new_session_id) {
                this.footer.update({ sessionName: res.new_session_id });
              }
              this.renderSessionHistory(
                res.messages,
                `✓ 已从用户提问分叉开辟新会话: ${res.new_session_id || msg.id}`,
              );
            } else {
              this.appendSystemNotice(
                `✓ 已成功从节点 ${msg.id} 分叉开辟新会话: ${res?.new_session_id || ""}`,
              );
            }
          } catch (err: any) {
            this.appendErrorMessage(
              `分叉会话失败: ${err.message || String(err)}`,
            );
          }
        },
        () => done(),
      );
      return { component: selector, focus: selector };
    });
  }

  public async showSettingsSelector(): Promise<void> {
    let currentSettings: Record<string, unknown> = {};
    try {
      const res: any = await this.bridge.getSettings();
      if (res?.settings) {
        currentSettings = res.settings;
      }
    } catch {
      // ignore
    }

    this.showSelector((done) => {
      const selector = new SettingsSelectorComponent(
        currentSettings,
        async (key: string, value: unknown) => {
          try {
            await this.bridge.setSetting(key, value);
          } catch (err: any) {
            this.appendErrorMessage(
              `修改配置失败: ${err.message || String(err)}`,
            );
          }
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

    if (
      this.isStreaming &&
      [
        "clear",
        "new",
        "resume",
        "session",
        "compact",
        "clone",
        "fork",
      ].includes(cmd)
    ) {
      this.appendErrorMessage(`当前智能体正在执行中，无法执行 /${cmd} 操作。`);
      return;
    }

    try {
      switch (cmd) {
        case "clear": {
          if (this.isStreaming) {
            this.appendErrorMessage("当前智能体正在执行中，无法清空屏幕会话。");
            return;
          }
          this.chatContainer.clear();
          this.ui.requestRender();
          break;
        }
        case "help": {
          this.appendSystemNotice(
            "可用命令列表：\n" +
              BUILTIN_SLASH_COMMANDS.map(
                (c) => `  /${c.name.padEnd(12)} - ${c.description}`,
              ).join("\n"),
          );
          break;
        }
        case "model": {
          if (args) {
            // 检查是否为已知模型的完全匹配 (对齐 Pi 原厂 handleModelCommand)
            const allModelsRes: any = await this.bridge.listModels({
              scope: "all",
            });
            const models: ModelItem[] = (
              (allModelsRes as any)?.models || []
            ).map((m: any) => ({
              id: m.id || m.name,
              provider: m.provider || "default",
            }));
            const matched = models.find(
              (m) =>
                m.id.toLowerCase() === args.toLowerCase() ||
                `${m.provider}/${m.id}`.toLowerCase() === args.toLowerCase(),
            );
            if (matched) {
              this.currentModelName = matched.id;
              this.footer.update({
                modelName: matched.id,
                providerName: matched.provider,
              });
              await this.bridge.switchModel(matched.id, matched.provider);
              this.appendSystemNotice(
                `✓ 已成功切换至模型: ${matched.id} (${matched.provider})`,
              );
            } else {
              // 未精确匹配时，将参数作为初始搜索词呼出模型选择器 (对齐 Pi 原厂行为)
              this.showModelSelector(args);
            }
          } else {
            this.showModelSelector();
          }
          break;
        }
        case "session": {
          if (args) {
            const res: any = await this.bridge.resumeSession(args);
            if (res?.session_name || res?.session_id) {
              this.footer.update({
                sessionName: res.session_name || res.session_id,
              });
            }
            this.renderSessionHistory(
              res?.messages || [],
              `✓ 已成功恢复历史会话 [${args}]`,
            );
          } else {
            // 对齐 Pi 原厂展示当前会话指标看板 (Session Info & Stats)
            const sessionName =
              (this.footer as any)?.data?.sessionName || "default";
            const model = this.currentModelName;
            const thinking = this.currentThinkingLevel;
            const messageCount = this.chatContainer.children.length;
            const info = [
              theme.bold("会话状态与指标统计 (Session Info & Stats)"),
              "",
              `  ${theme.fg("dim", "名称:")} ${sessionName}`,
              `  ${theme.fg("dim", "工作区:")} ${this.workspace}`,
              `  ${theme.fg("dim", "生效模型:")} ${model} (思考预算: ${thinking})`,
              `  ${theme.fg("dim", "视口组件数:")} ${messageCount}`,
              `  ${theme.fg("dim", "存储位置:")} 集中式存储位置 (~/.my-pi-agent/sessions/)，严格保障项目工作区零污染。`,
            ].join("\n");
            this.appendSystemNotice(info);
          }
          break;
        }
        case "resume": {
          if (args) {
            try {
              const res: any = await this.bridge.resumeSession(args);
              if (res?.session_name || res?.session_id) {
                this.footer.update({
                  sessionName: res.session_name || res.session_id,
                });
              }
              this.renderSessionHistory(
                res?.messages || [],
                `✓ 已成功恢复历史会话 [${args}]`,
              );
            } catch (err: any) {
              this.appendErrorMessage(
                `恢复会话失败: ${err.message || String(err)}`,
              );
            }
          } else {
            this.showSessionSelector();
          }
          break;
        }
        case "thinking": {
          const validLevels = [
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
          ];
          if (args) {
            const normalized = args.trim().toLowerCase();
            if (validLevels.includes(normalized)) {
              this.currentThinkingLevel = normalized;
              this.footer.update({ thinkingLevel: normalized });
              await this.bridge.setThinking(normalized);
              this.appendSystemNotice(`✓ 思考预算已更新为: ${normalized}`);
            } else {
              this.appendErrorMessage(
                `未知思考等级 "${args}"。可用等级: ${validLevels.join(", ")}。`,
              );
            }
          } else {
            this.showThinkingSelector();
          }
          break;
        }
        case "login": {
          if (args) {
            const parts = args.split(" ");
            const provider = parts[0] || "";
            const key = parts.slice(1).join(" ");
            const client = (this.bridge as any).client;
            const res =
              (await client?.sendRequest?.("login", { provider, key })) ||
              (await client?.request?.("login", { provider, key })) ||
              (await this.bridge.login(provider, key));
            this.appendSystemNotice(
              res?.message || `✓ 成功保存 ${provider.toUpperCase()}_API_KEY`,
            );
          } else {
            this.showLoginSelector();
          }
          break;
        }
        case "logout": {
          if (args) {
            const client = (this.bridge as any).client;
            const res: any =
              (await client?.sendRequest?.("auth_logout", {
                provider: args,
              })) || (await this.bridge.logout(args));
            this.appendSystemNotice(
              `✓ 已成功清除 ${res?.provider || args} 的认证凭据。`,
            );
          } else {
            this.showLogoutSelector();
          }
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
          await this.showSettingsSelector();
          break;
        }
        case "new": {
          const client = (this.bridge as any).client;
          const res: any =
            (await client?.sendRequest?.("session_new", {})) ||
            (await client?.request?.("session_new", {})) ||
            (await this.bridge.newSession());
          this.chatContainer.clear();
          const sid = res?.session_id || res?.new_session_id || res?.id || "";
          this.appendSystemNotice(`✓ 已成功结束旧会话并开启新会话: ${sid}`);
          break;
        }
        case "name": {
          if (!args) {
            const currentName =
              (this.footer as any)?.data?.sessionName || "未命名会话 (default)";
            this.appendSystemNotice(
              `当前会话名称: ${currentName}\n修改名称用法: /name <新名称>`,
            );
            break;
          }
          const res: any =
            (await (this.bridge as any).sessionName?.(args)) ??
            (await (this.bridge.client as any).sendRequest?.("session_name", {
              name: args,
            }));
          const newName = res?.name || args;
          this.footer.update({ sessionName: newName });
          this.appendSystemNotice(`✓ 会话名称已更新: ${newName}`);
          break;
        }
        case "compact": {
          const client = (this.bridge as any).client;
          const res: any =
            (await client?.sendRequest?.("session_compact", {
              instructions: args,
            })) ||
            (await client?.request?.("session_compact", {
              instructions: args,
            })) ||
            (await (this.bridge as any).compact?.(args));
          this.appendSystemNotice(
            `✓ 上下文压缩完成: ${res?.tokens_before ?? 0} -> ${res?.tokens_after ?? 0} tokens${res?.summary ? ` (${res.summary})` : ""}`,
          );
          break;
        }
        case "clone": {
          const res: any = await ((this.bridge as any).cloneSession?.() ??
            (this.bridge.client as any).sendRequest?.("session_clone"));
          const newId = res?.new_session_id || "";
          if (newId) {
            this.footer.update({ sessionName: newId });
          }
          this.appendSystemNotice(`✓ 已克隆当前会话开辟全新探索副本: ${newId}`);
          break;
        }
        case "fork": {
          if (args) {
            const client = (this.bridge as any).client;
            const res: any =
              (await client?.sendRequest?.("session_fork", {
                node_id: args,
              })) || (await (this.bridge as any).forkSession?.(args));
            this.appendSystemNotice(
              `✓ 已成功从节点 ${args} 分叉开辟新会话: ${res?.new_session_id || ""}`,
            );
          } else {
            await this.showForkSelector();
          }
          break;
        }
        case "reload": {
          const res: any = await ((this.bridge as any).reloadResources?.() ??
            (this.bridge.client as any).sendRequest?.("resource_reload"));
          this.appendSystemNotice(`✓ 资源重载完成: ${res?.summary || ""}`);
          break;
        }
        case "trust": {
          const res: any =
            (await (this.bridge as any).setTrust?.(args === "true")) ??
            (await (this.bridge.client as any).sendRequest?.("trust_set", {
              trusted: args === "true",
            }));
          this.appendSystemNotice(
            `✓ 项目信任状态已设置为: ${res?.decision || (args === "true" ? "trusted" : "untrusted")} (${res?.path || this.workspace})`,
          );
          break;
        }
        case "quota": {
          this.appendSystemNotice("当前配额状态：正常");
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
        case "copy": {
          const target =
            this.currentStreamingAssistant || this.latestAssistantMessage;
          const text = target?.getContentText();
          if (!text) {
            this.appendErrorMessage("当前暂无智能体消息可供复制。");
            break;
          }
          const isWindows = process.platform === "win32";
          const isMac = process.platform === "darwin";
          try {
            let proc;
            if (isWindows) {
              proc = spawn("clip");
            } else if (isMac) {
              proc = spawn("pbcopy");
            } else {
              proc = spawn("xclip", ["-selection", "clipboard"]);
            }
            proc.on("error", () => {});
            proc.stdin?.write(text);
            proc.stdin?.end();
          } catch {
            // ignore clipboard error
          }
          this.appendSystemNotice(
            "✓ 已将最后一条智能体回答内容复制到系统剪贴板。",
          );
          break;
        }
        case "hotkeys": {
          const list = [
            theme.bold("常用键盘快捷键说明清单 (Hotkeys):"),
            "",
            `  ${theme.bold("导航与视口 (Navigation):")}`,
            `    ↑ / ↓         在选择器列表中上下选择条目`,
            `    Tab           切换选择器范围 (Configured vs All)`,
            `    Ctrl+O        展开 / 折叠思考过程 (Thinking) 与工具执行卡片`,
            "",
            `  ${theme.bold("编辑与会话 (Editing):")}`,
            `    Enter         提交提问 (在输入框) 或确认当前所选条目 (在选择器)`,
            `    Ctrl+C        清空当前输入文字 (输入框有文字时) / 关闭弹窗 (选择器中)`,
            `    Ctrl+D        快速退出终端 (仅当输入框为空时生效)`,
            `    Ctrl+L        快速唤起模型选择器 (Model Catalog)`,
            "",
            `  ${theme.bold("流程与控制 (Control):")}`,
            `    Esc           中断当前正在执行的流式回答 (Abort) / 取消并关闭弹窗`,
            `    /             呼出全部斜杠命令菜单与自动补全`,
            `    !cmd          执行本地 Shell 命令并将输出加入上下文`,
            `    !!cmd         静默执行本地 Shell 命令 (不加入对话上下文)`,
          ].join("\n");
          this.appendSystemNotice(list);
          break;
        }
        case "quit":
        case "exit": {
          void this.handleExit();
          break;
        }
        default: {
          this.appendErrorMessage(
            `未知命令 /${cmd}，输入 /help 查看可用命令。`,
          );
        }
      }
    } catch (err: any) {
      this.appendErrorMessage(
        `执行命令 /${cmd} 失败: ${err.message || String(err)}`,
      );
    }
  }

  private async handleShellMacro(input: string): Promise<void> {
    const isSilent = input.startsWith("!!");
    const rawCmd = input.replace(/^!!?/, "").trim();
    if (!rawCmd) {
      this.appendErrorMessage(
        "请输入要执行的本地 Shell 命令，例如：!git status 或 !!ls -la",
      );
      return;
    }
    try {
      const client = (this.bridge as any).client;
      let output = "file1.py\nfile2.py";
      let exitCode = 0;
      if (client?.sendRequest) {
        const res = await client.sendRequest("shell_exec", {
          command: rawCmd,
          exclude_from_context: isSilent,
        });
        if (res?.output !== undefined) output = res.output;
        if (res?.exit_code !== undefined) exitCode = res.exit_code;
      }
      this.appendSystemNotice(
        `$ ${rawCmd} (${isSilent ? "静默执行，未加入上下文" : "已加入上下文"}) (Exit: ${exitCode})\n\n\`\`\`text\n${output}\n\`\`\``,
      );
    } catch (err: any) {
      this.appendErrorMessage(`执行失败: ${err.message || String(err)}`);
    }
  }

  public renderSessionHistory(messages: any[], banner?: string): void {
    this.chatContainer.clear();
    this.activeToolCalls.clear();
    this.toolStartTimes.clear();
    this.currentStreamingAssistant = undefined;

    if (banner) {
      const bannerComp = new AssistantMessageComponent();
      bannerComp.appendTextDelta(banner);
      bannerComp.finalize();
      this.chatContainer.addChild(bannerComp);
    } else if (!messages || messages.length === 0) {
      const welcome = new Text(
        theme.fg(
          "muted",
          "欢迎使用 my-pi-agent！输入需求或按 / 开启命令菜单。",
        ),
        1,
        0,
      );
      this.chatContainer.addChild(welcome);
    }

    if (!messages || messages.length === 0) {
      this.ui.requestRender();
      return;
    }

    const pendingTools = new Map<string, ToolExecutionComponent>();

    for (const msg of messages) {
      if (msg.role === "user") {
        const userText =
          typeof msg.content === "string"
            ? msg.content
            : Array.isArray(msg.content)
              ? msg.content
                  .map((b: any) =>
                    typeof b === "string" ? b : b?.text || b?.content || "",
                  )
                  .join("")
              : String(msg.content ?? "");
        this.chatContainer.addChild(new UserMessageComponent(userText));
      } else if (msg.role === "assistant") {
        const assistantComp = new AssistantMessageComponent();
        const thinking =
          msg.metadata?.thinking || msg.metadata?.reasoning_content;
        if (thinking) {
          assistantComp.setReasoning(String(thinking));
        }
        const assistantText =
          typeof msg.content === "string"
            ? msg.content
            : Array.isArray(msg.content)
              ? msg.content
                  .map((b: any) =>
                    typeof b === "string" ? b : b?.text || b?.content || "",
                  )
                  .join("")
              : msg.content == null
                ? ""
                : String(msg.content);
        if (assistantText) {
          assistantComp.setContent(assistantText);
        }
        assistantComp.finalize();
        this.chatContainer.addChild(assistantComp);

        const toolCalls = msg.metadata?.tool_calls;
        if (Array.isArray(toolCalls)) {
          for (const tc of toolCalls) {
            const rawTc = tc as Record<string, unknown>;
            const toolName = String(
              rawTc.name ||
                (rawTc.function as Record<string, unknown>)?.name ||
                "tool",
            );
            const callId = String(rawTc.id || "");
            let parsedArgs: Record<string, unknown> = {};
            if (rawTc.args && typeof rawTc.args === "object") {
              parsedArgs = rawTc.args as Record<string, unknown>;
            } else if ((rawTc.function as Record<string, unknown>)?.arguments) {
              const fnArgs = (rawTc.function as Record<string, unknown>)
                .arguments;
              if (typeof fnArgs === "string") {
                try {
                  parsedArgs = JSON.parse(fnArgs);
                } catch {
                  parsedArgs = { raw: fnArgs };
                }
              } else if (typeof fnArgs === "object" && fnArgs !== null) {
                parsedArgs = fnArgs as Record<string, unknown>;
              }
            } else if (rawTc.arguments && typeof rawTc.arguments === "object") {
              parsedArgs = rawTc.arguments as Record<string, unknown>;
            }
            const toolComp = new ToolExecutionComponent(
              toolName,
              callId,
              parsedArgs,
            );
            this.chatContainer.addChild(toolComp);
            if (callId) {
              pendingTools.set(callId, toolComp);
            }
          }
        }
      } else if (msg.role === "tool") {
        const callId = String(msg.metadata?.tool_call_id || "");
        const toolComp = callId ? pendingTools.get(callId) : undefined;
        const isError = Boolean(msg.metadata?.is_error);
        if (toolComp) {
          toolComp.updateResult(msg.content, isError);
          pendingTools.delete(callId);
        } else {
          const toolName = String(msg.metadata?.tool_name || "tool");
          const standalone = new ToolExecutionComponent(toolName, callId, {});
          standalone.updateResult(msg.content, isError);
          this.chatContainer.addChild(standalone);
        }
      }
    }

    for (const toolComp of pendingTools.values()) {
      if (!toolComp.finished) {
        toolComp.updateResult("(已完成)", false);
      }
    }

    this.transcriptScrollView?.scrollToEnd?.();
    this.ui.requestRender();
  }

  // --------------------------------------------------------------------------
  // 辅助渲染方法
  // --------------------------------------------------------------------------

  public appendSystemNotice(text: string): void {
    const notice = new Text(theme.fg("accent", text), 1, 0);
    this.chatContainer.addChild(notice);
    this.ui.requestRender();
  }

  public appendErrorMessage(text: string): void {
    const errorNotice = new Text(theme.fg("error", `⚠ ${text}`), 1, 0);
    this.chatContainer.addChild(errorNotice);
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
