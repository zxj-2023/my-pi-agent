import { spawn } from "node:child_process";
import { Spacer } from "@earendil-works/pi-tui";
import { CompactionSummaryMessageComponent } from "../components/compaction-summary-message.js";
import { CompactionStatusIndicator } from "../components/status-indicator.js";
import type { ModelItem } from "../components/model-selector.js";
import { theme } from "../theme/theme.js";

export interface SlashCommand {
  name: string;
  description: string;
  argumentHint?: string;
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
    name: "branch",
    description: "在当前分支树中回退并开辟新分支继续交互",
    argumentHint: "[node_id]",
  },
  {
    name: "fork",
    description: "从当前或指定节点分叉生成独立的新会话副本",
    argumentHint: "[node_id]",
  },
  { name: "clone", description: "克隆当前会话开辟全新探索副本" },
  {
    name: "model",
    description: "快速切换底层大模型或唤起模型选择器",
    argumentHint: "[model_name]",
  },
  {
    name: "thinking",
    description: "调整思考预算等级 (off/minimal/low/medium/high/max)",
    argumentHint: "[level]",
  },
  { name: "settings", description: "打开可视化交互配置管理面板" },
  { name: "theme", description: "切换 TUI 终端高亮配色主题" },
  {
    name: "login",
    description: "配置或切换指定大模型提供商的 API 认证凭据",
    argumentHint: "<provider> [key]",
  },
  {
    name: "logout",
    description: "清除指定模型提供商的已保存认证凭据",
    argumentHint: "<provider>",
  },
  {
    name: "steer",
    description: "向正在运行的 Agent 注入插话指示 (打断/干预)",
    argumentHint: "<instruction>",
  },
  {
    name: "followup",
    description: "排队追加后续提问 (当前任务完成后顺延执行)",
    argumentHint: "<instruction>",
  },
  { name: "copy", description: "复制上一条智能体消息内容至系统剪贴板" },
  { name: "hotkeys", description: "查看常用终端快捷键完整操作说明" },
  { name: "reload", description: "热重载系统指导文件、技能、子代理与提示词" },
  {
    name: "trust",
    description: "管理当前工作区脚本/命令安全信任状态",
    argumentHint: "[true/false]",
  },
  { name: "quota", description: "查看 Antigravity 免费层额度与重置倒计时" },
  { name: "debug", description: "导出当前会话的完整调试状态与追踪日志" },
  { name: "quit", description: "退出当前交互终端 (也可按 Ctrl+D)" },
  { name: "exit", description: "退出当前交互终端" },
];

export interface SlashCommandContext {
  isStreaming: boolean;
  workspace?: string;
  currentModelName: string;
  currentThinkingLevel?: string;
  chatContainer: any;
  ui: any;
  bridge: any;
  footer: any;
  defaultEditor?: any;
  activeStatusIndicator?: any;
  latestAssistantMessage?: any;
  currentStreamingAssistant?: any;
  appendErrorMessage(msg: string): void;
  appendSystemNotice(msg: string): void;
  handleExit(): void;
  clearStatusDisplay(): void;
  updateResources(resources: any): void;
  updateFooterUsage(usage: any, contextWindow?: any): void;
  updateEditorBorderColor(): void;
  renderSessionHistory(messages: any[], banner?: string): void;
  renderPiSessionStats(stats: any): void;
  renderFallbackSessionStats(): void;
  showModelSelector(search?: string): void;
  showSessionSelector(): void;
  showForkSelector(): void;
  showTreeSelector(): void;
  showThinkingSelector(): void;
  showLoginSelector(): void;
  showLogoutSelector(): void;
  showThemeSelector(): void;
  showSettingsSelector(): void;
}

export async function executeSlashCommand(mode: SlashCommandContext, input: string): Promise<void> {
  const parts = input.slice(1).split(" ");
  const cmd = (parts[0] || "").toLowerCase();
  const args = parts.slice(1).join(" ").trim();

  if (
    mode.isStreaming &&
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
    mode.appendErrorMessage(`当前智能体正在执行中，无法执行 /${cmd} 操作。`);
    return;
  }

  try {
    switch (cmd) {
      case "clear": {
        if (mode.isStreaming) {
          mode.appendErrorMessage("当前智能体正在执行中，无法清空屏幕会话。");
          return;
        }
        mode.chatContainer.clear();
        mode.ui.requestRender();
        break;
      }
      case "help": {
        mode.appendSystemNotice(
          "可用命令列表：\n" +
            BUILTIN_SLASH_COMMANDS.map(
              (c) => `  /${c.name.padEnd(12)} - ${c.description}`,
            ).join("\n"),
        );
        break;
      }
      case "model": {
        if (args) {
          const allModelsRes: any = await mode.bridge.listModels({
            scope: "all",
          });
          const models: ModelItem[] = (
            (allModelsRes as any)?.models || []
          ).map((m: any) => ({
            id: m.id || m.name,
            provider: m.provider || "default",
            contextWindow: m.contextWindow || m.context_window,
          }));
          const matched = models.find(
            (m) =>
              m.id.toLowerCase() === args.toLowerCase() ||
              `${m.provider}/${m.id}`.toLowerCase() === args.toLowerCase(),
          );
          if (matched) {
            mode.currentModelName = matched.id;
            const ctxWin =
              matched.contextWindow ||
              (matched.id.startsWith("gemini-") ? 1048576 : 128000);
            mode.footer.update({
              modelName: matched.id,
              providerName: matched.provider,
              contextWindow: ctxWin,
            });
            const switchRes: any = await mode.bridge.switchModel(
              matched.id,
              matched.provider,
            );
            if (switchRes?.context_window || switchRes?.contextWindow) {
              mode.footer.update({
                contextWindow:
                  switchRes.context_window || switchRes.contextWindow,
              });
            }
            mode.appendSystemNotice(
              `✓ 已成功切换至模型: ${matched.id} (${matched.provider})`,
            );
          } else {
            mode.showModelSelector(args);
          }
        } else {
          mode.showModelSelector();
        }
        break;
      }
      case "session": {
        if (args) {
          const res: any = await mode.bridge.resumeSession(args);
          if (res?.session_name || res?.session_id) {
            mode.footer.update({
              sessionName: res.session_name || res.session_id,
            });
          }
          mode.renderSessionHistory(
            res?.messages || [],
            `✓ 已成功恢复历史会话 [${args}]`,
          );
        } else {
          try {
            const res: any = await mode.bridge.getSessionStats();
            if (res?.stats) {
              mode.renderPiSessionStats(res.stats);
            } else {
              mode.renderFallbackSessionStats();
            }
          } catch {
            mode.renderFallbackSessionStats();
          }
        }
        break;
      }
      case "resume": {
        if (args) {
          try {
            const res: any = await mode.bridge.resumeSession(args);
            if (res?.session_name || res?.session_id) {
              mode.footer.update({
                sessionName: res.session_name || res.session_id,
              });
            }
            if (res?.usage) {
              mode.updateFooterUsage(res.usage, res.context_window);
            }
            mode.renderSessionHistory(
              res?.messages || [],
              `✓ 已成功恢复历史会话 [${args}]`,
            );
          } catch (err: any) {
            mode.appendErrorMessage(
              `恢复会话失败: ${err.message || String(err)}`,
            );
          }
        } else {
          mode.showSessionSelector();
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
            mode.currentThinkingLevel = normalized;
            mode.footer.update({ thinkingLevel: normalized });
            mode.updateEditorBorderColor();
            await mode.bridge.setThinking(normalized);
            mode.appendSystemNotice(`✓ 思考预算已更新为: ${normalized}`);
          } else {
            mode.appendErrorMessage(
              `未知思考等级 "${args}"。可用等级: ${validLevels.join(", ")}。`,
            );
          }
        } else {
          mode.showThinkingSelector();
        }
        break;
      }
      case "login": {
        if (args) {
          const parts = args.split(" ");
          const provider = parts[0] || "";
          const key = parts.slice(1).join(" ");
          const client = (mode.bridge as any).client;
          const res =
            (await client?.sendRequest?.("login", { provider, key })) ||
            (await client?.request?.("login", { provider, key })) ||
            (await mode.bridge.login(provider, key));
          mode.appendSystemNotice(
            res?.message || `✓ 成功保存 ${provider.toUpperCase()}_API_KEY`,
          );
        } else {
          mode.showLoginSelector();
        }
        break;
      }
      case "logout": {
        if (args) {
          const client = (mode.bridge as any).client;
          const res: any =
            (await client?.sendRequest?.("auth_logout", {
              provider: args,
            })) || (await mode.bridge.logout(args));
          mode.appendSystemNotice(
            `✓ 已成功清除 ${res?.provider || args} 的认证凭据。`,
          );
        } else {
          mode.showLogoutSelector();
        }
        break;
      }
      case "theme": {
        mode.showThemeSelector();
        break;
      }
      case "tree": {
        mode.showTreeSelector();
        break;
      }
      case "settings": {
        await mode.showSettingsSelector();
        break;
      }
      case "new": {
        const client = (mode.bridge as any).client;
        const res: any =
          (await client?.sendRequest?.("session_new", {})) ||
          (await client?.request?.("session_new", {})) ||
          (await mode.bridge.newSession());
        mode.chatContainer.clear();
        const sid = res?.session_id || res?.new_session_id || res?.id || "";
        const sname = res?.session_name || sid;
        if (res?.usage) {
          mode.updateFooterUsage(
            res.usage,
            res.context_window || res.contextWindow,
          );
        } else {
          mode.footer.update({
            inputTokens: 0,
            outputTokens: 0,
            cacheReadTokens: 0,
            cacheWriteTokens: 0,
            totalTokens: 0,
            contextTokens: 0,
            costUsd: 0,
            cacheHitRate: undefined,
          });
        }
        mode.footer.update({
          sessionName: sname,
          contextWindow:
            res?.context_window ||
            res?.contextWindow ||
            mode.footer.getContextWindow(),
        });
        mode.appendSystemNotice(`✓ 已成功结束旧会话并开启新会话: ${sid}`);
        break;
      }
      case "name": {
        if (!args) {
          const currentName =
            (mode.footer as any)?.data?.sessionName || "未命名会话 (default)";
          mode.appendSystemNotice(
            `当前会话名称: ${currentName}\n修改名称用法: /name <新名称>`,
          );
          break;
        }
        const res: any =
          (await (mode.bridge as any).sessionName?.(args)) ??
          (await (mode.bridge.client as any).sendRequest?.("session_name", {
            name: args,
          }));
        const newName = res?.name || args;
        mode.footer.update({ sessionName: newName });
        mode.appendSystemNotice(`✓ 会话名称已更新: ${newName}`);
        break;
      }
      case "compact": {
        mode.isStreaming = true;
        mode.clearStatusDisplay();
        const compIndicator = new CompactionStatusIndicator(
          mode.ui,
          "manual",
        );
        compIndicator.start();
        mode.activeStatusIndicator = compIndicator;
        mode.defaultEditor.setWorkingStatusIndicator(compIndicator);
        mode.footer.update({ isBusy: true });
        mode.ui.requestRender();
        try {
          const client = (mode.bridge as any).client;
          const res: any =
            (await client?.sendRequest?.("session_compact", {
              instructions: args,
            })) ||
            (await client?.request?.("session_compact", {
              instructions: args,
            })) ||
            (await (mode.bridge as any).compact?.(args));

          if (res?.tokens_after !== undefined) {
            mode.footer.update({ contextTokens: res.tokens_after });
          }

          if (res?.summary) {
            const compComponent = new CompactionSummaryMessageComponent({
              summary: res.summary,
              tokensBefore: res.tokens_before ?? 0,
            });
            mode.chatContainer.addChild(new Spacer(1));
            mode.chatContainer.addChild(compComponent);
          }
        } catch (err: any) {
          mode.appendErrorMessage(`压缩失败: ${err.message || String(err)}`);
        } finally {
          mode.isStreaming = false;
          mode.clearStatusDisplay();
          mode.footer.update({ isBusy: false });
          mode.ui.requestRender();
        }
        break;
      }
      case "clone": {
        const res: any = await ((mode.bridge as any).cloneSession?.() ??
          (mode.bridge.client as any).sendRequest?.("session_clone"));
        const newId = res?.new_session_id || "";
        if (newId) {
          mode.footer.update({ sessionName: newId });
        }
        mode.appendSystemNotice(`✓ 已克隆当前会话开辟全新探索副本: ${newId}`);
        break;
      }
      case "fork": {
        if (args) {
          const client = (mode.bridge as any).client;
          const res: any =
            (await client?.sendRequest?.("session_fork", {
              node_id: args,
            })) || (await (mode.bridge as any).forkSession?.(args));
          mode.appendSystemNotice(
            `✓ 已成功从节点 ${args} 分叉开辟新会话: ${res?.new_session_id || ""}`,
          );
        } else {
          await mode.showForkSelector();
        }
        break;
      }
      case "reload": {
        const res: any =
          (await (mode.bridge as any).reloadResources?.()) ??
          (await (mode.bridge.client as any).sendRequest?.(
            "resource_reload",
          ));
        if (res?.resources) {
          mode.updateResources(res.resources);
        }
        mode.appendSystemNotice(`✓ 资源重载完成: ${res?.summary || ""}`);
        break;
      }
      case "trust": {
        const res: any =
          (await (mode.bridge as any).setTrust?.(args === "true")) ??
          (await (mode.bridge.client as any).sendRequest?.("trust_set", {
            trusted: args === "true",
          }));
        mode.appendSystemNotice(
          `✓ 项目信任状态已设置为: ${res?.decision || (args === "true" ? "trusted" : "untrusted")} (${res?.path || mode.workspace})`,
        );
        break;
      }
      case "quota": {
        mode.appendSystemNotice("当前配额状态：正常");
        break;
      }
      case "debug": {
        try {
          const client = (mode.bridge as any).client;
          const res: any =
            (await client?.request?.("debug_dump", {})) ||
            (await client?.sendRequest?.("debug_dump", {}));
          if (res?.dump_file) {
            const lines = [`✓ 调试快照已导出至: ${res.dump_file}`];
            if (res?.log_file) {
              lines.push(`  会话调试日志: ${res.log_file}`);
            }
            if (res?.events_file) {
              lines.push(`  会话事件流: ${res.events_file}`);
            }
            mode.appendSystemNotice(lines.join("\n"));
          } else {
            mode.appendErrorMessage("导出调试快照失败。");
          }
        } catch (err: any) {
          mode.appendErrorMessage(
            `导出调试快照异常: ${err.message || String(err)}`,
          );
        }
        break;
      }
      case "steer": {
        if (args) {
          await mode.bridge.steer(args);
          mode.appendSystemNotice(`[Steer 提示已注入]: ${args}`);
        }
        break;
      }
      case "followup": {
        if (args) {
          await mode.bridge.followUp(args);
          mode.appendSystemNotice(`[Followup 任务已排队]: ${args}`);
        }
        break;
      }
      case "copy": {
        const target =
          mode.currentStreamingAssistant || mode.latestAssistantMessage;
        const text = target?.getContentText();
        if (!text) {
          mode.appendErrorMessage("当前暂无智能体消息可供复制。");
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
        mode.appendSystemNotice(
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
          `    Tab           切换选择器范围 (all vs scoped)`,
          `    Ctrl+O        展开 / 折叠思考过程 (Thinking) 与工具执行卡片`,
          "",
          `  ${theme.bold("编辑与会话 (Editing):")}`,
          `    Enter         提交提问 (在输入框) 或确认当前所选条目 (在选择器)`,
          `    Ctrl+V        粘贴剪贴板图片（也支持 Ctrl+Shift+V）`,
          `    Ctrl+Q        排队追问 (Follow-up) 当前任务完成后自动顺延执行`,
          `    Alt+Q/Alt+Up  召回并编辑全部待发排队消息 (Steering & Follow-up)`,
          `    Ctrl+C        清空当前输入文字 (输入框有文字时) / 关闭弹窗 (选择器中)`,
          `    Ctrl+D        快速退出终端 (仅当输入框为空时生效)`,
          `    Ctrl+L        快速唤起模型选择器 (Model Catalog)`,
          "",
          `  ${theme.bold("流程与控制 (Control):")}`,
          `    Esc           中断当前正在执行的流式回答 (Abort) / 取消并关闭弹窗`,
          `    Shift+Tab     轮转切换思考预算深度 (off -> low -> high -> max)`,
          `    /             呼出全部斜杠命令菜单与自动补全`,
          `    !cmd          执行本地 Shell 命令并将输出加入上下文`,
          `    !!cmd         静默执行本地 Shell 命令 (不加入对话上下文)`,
        ].join("\n");
        mode.appendSystemNotice(list);
        break;
      }
      case "quit":
      case "exit": {
        void mode.handleExit();
        break;
      }
      default: {
        mode.appendErrorMessage(
          `未知命令 /${cmd}，输入 /help 查看可用命令。`,
        );
      }
    }
  } catch (err: any) {
    mode.appendErrorMessage(
      `执行命令 /${cmd} 失败: ${err.message || String(err)}`,
    );
  }
}
