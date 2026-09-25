import * as os from "node:os";
import * as path from "node:path";
import {
  Container,
  truncateToWidth,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { SPINNER_FRAMES } from "./tool-execution.js";

export interface FooterData {
  workspace: string;
  gitBranch?: string;
  sessionName?: string;
  providerName?: string;
  modelName?: string;
  thinkingLevel?: string;
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  cacheHitRate?: number;
  totalTokens?: number;
  tokensUsed?: number; // 兼容旧版调用场景
  contextTokens?: number;
  contextWindow?: number;
  autoCompactEnabled?: boolean;
  costUsd?: number;
  elapsedSeconds?: number;
  isBusy?: boolean;
  debugMode?: boolean;
}

export function formatTokens(count: number): string {
  if (count < 1000) return count.toString();
  if (count < 10000) return `${(count / 1000).toFixed(1)}k`;
  if (count < 1000000) return `${Math.round(count / 1000)}k`;
  if (count < 10000000) return `${(count / 1000000).toFixed(1)}M`;
  return `${Math.round(count / 1000000)}M`;
}

export class FooterComponent extends Container {
  private data: FooterData;
  private spinnerFrame = 0;
  private busyInterval: ReturnType<typeof setInterval> | null = null;

  constructor(
    initialData?: Partial<FooterData>,
    private readonly onRequestRender?: () => void,
  ) {
    super();
    this.data = {
      workspace: process.cwd(),
      modelName: "default",
      thinkingLevel: "off",
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
      contextWindow: 128000,
      costUsd: 0,
      ...initialData,
    };
    if (this.data.isBusy) {
      this.startAnimation();
    }
  }

  public update(partial: Partial<FooterData>): void {
    const wasBusy = Boolean(this.data.isBusy);
    this.data = { ...this.data, ...partial };
    const nowBusy = Boolean(this.data.isBusy);
    if (nowBusy && !wasBusy) {
      this.startAnimation();
    } else if (!nowBusy && wasBusy) {
      this.stopAnimation();
    }
  }

  private startAnimation(): void {
    if (this.busyInterval) return;
    this.busyInterval = setInterval(() => {
      this.spinnerFrame = (this.spinnerFrame + 1) % SPINNER_FRAMES.length;
      if (this.onRequestRender) {
        this.onRequestRender();
      }
    }, 80);
    if (typeof this.busyInterval?.unref === "function") {
      this.busyInterval.unref();
    }
  }

  private stopAnimation(): void {
    if (this.busyInterval) {
      clearInterval(this.busyInterval);
      this.busyInterval = null;
    }
  }

  public dispose(): void {
    this.stopAnimation();
  }

  public getContextWindow(): number {
    return this.data.contextWindow || 128000;
  }

  public getSessionName(): string | undefined {
    return this.data.sessionName;
  }

  public override render(width: number): string[] {
    // 1. 第一行：工作区路径 (~ 折叠) + 分支 + 会话名
    let pwd = this.formatCwd(this.data.workspace);
    if (this.data.gitBranch) {
      pwd += ` (${this.data.gitBranch})`;
    }
    if (this.data.sessionName) {
      pwd += ` • ${this.data.sessionName}`;
    }
    const line1 = truncateToWidth(
      theme.fg("dim", pwd),
      width,
      theme.fg("dim", "..."),
    );

    // 2. 第二行左侧：Token 指标与实时状态 (完全对齐 Pi 原厂格式)
    const statsParts: string[] = [];
    if (this.data.inputTokens && this.data.inputTokens > 0) {
      statsParts.push(`↑${this.formatTokens(this.data.inputTokens)}`);
    }
    if (this.data.outputTokens && this.data.outputTokens > 0) {
      statsParts.push(`↓${this.formatTokens(this.data.outputTokens)}`);
    }
    if (this.data.cacheReadTokens && this.data.cacheReadTokens > 0) {
      statsParts.push(`R${this.formatTokens(this.data.cacheReadTokens)}`);
    }
    if (this.data.cacheWriteTokens && this.data.cacheWriteTokens > 0) {
      statsParts.push(`W${this.formatTokens(this.data.cacheWriteTokens)}`);
    }
    let chRate = this.data.cacheHitRate;
    if (
      chRate === undefined &&
      ((this.data.cacheReadTokens && this.data.cacheReadTokens > 0) ||
        (this.data.cacheWriteTokens && this.data.cacheWriteTokens > 0))
    ) {
      const promptSum =
        (this.data.inputTokens || 0) +
        (this.data.cacheReadTokens || 0) +
        (this.data.cacheWriteTokens || 0);
      if (promptSum > 0) {
        chRate = ((this.data.cacheReadTokens || 0) / promptSum) * 100;
      }
    }
    if (
      chRate !== undefined &&
      ((this.data.cacheReadTokens && this.data.cacheReadTokens > 0) ||
        (this.data.cacheWriteTokens && this.data.cacheWriteTokens > 0))
    ) {
      statsParts.push(`CH${chRate.toFixed(1)}%`);
    }
    if (
      this.data.tokensUsed &&
      this.data.tokensUsed > 0 &&
      !this.data.inputTokens &&
      !this.data.outputTokens
    ) {
      statsParts.push(this.formatTokens(this.data.tokensUsed));
    }
    if (this.data.costUsd && this.data.costUsd > 0) {
      statsParts.push(`$${this.data.costUsd.toFixed(3)}`);
    }

    const contextWin = this.data.contextWindow || 128000;
    const autoIndicator =
      this.data.autoCompactEnabled === false ? "" : " (auto)";
    const contextTok = this.data.contextTokens ?? this.data.totalTokens ?? 0;
    const percent = contextWin > 0 ? (contextTok / contextWin) * 100 : 0;
    const percentStr = `${percent.toFixed(1)}%/${this.formatTokens(contextWin)}${autoIndicator}`;
    const contextColor =
      percent > 90 ? "error" : percent > 70 ? "warning" : "dim";
    statsParts.push(theme.fg(contextColor, percentStr));

    if (this.data.elapsedSeconds && this.data.elapsedSeconds > 0) {
      statsParts.push(
        theme.fg("dim", `${this.data.elapsedSeconds.toFixed(1)}s`),
      );
    }
    if (this.data.isBusy) {
      const char = SPINNER_FRAMES[this.spinnerFrame] || "⠋";
      statsParts.push(theme.fg("warning", char));
    }
    if (this.data.debugMode) {
      statsParts.push(theme.fg("warning", "[DEBUG]"));
    }

    const statsLeft = statsParts.join(" ");

    // 3. 第二行右侧：模型与思考深度 (provider) model • thinking
    const prov = this.data.providerName ? `(${this.data.providerName}) ` : "";
    const model = this.data.modelName || "default";
    const thinking =
      this.data.thinkingLevel && this.data.thinkingLevel !== "off"
        ? ` • ${this.data.thinkingLevel}`
        : "";
    const rightSide = `${prov}${model}${thinking}`;

    // 4. 动态计算填充间距并右对齐，应用 ANSI 独立染色保护
    let statsLeftFormatted = statsLeft;
    let statsLeftWidth = visibleWidth(statsLeftFormatted);
    if (statsLeftWidth > width) {
      statsLeftFormatted = truncateToWidth(statsLeftFormatted, width, "...");
      statsLeftWidth = visibleWidth(statsLeftFormatted);
    }

    const minPadding = 2;
    const rightWidth = visibleWidth(rightSide);
    let line2: string;

    if (statsLeftWidth + minPadding + rightWidth <= width) {
      const padLen = width - statsLeftWidth - rightWidth;
      const remainder = " ".repeat(padLen) + rightSide;
      line2 = theme.fg("dim", statsLeftFormatted) + theme.fg("dim", remainder);
    } else {
      const availableForRight = width - statsLeftWidth - minPadding;
      if (availableForRight > 0) {
        const truncatedRight = truncateToWidth(
          rightSide,
          availableForRight,
          "",
        );
        const padLen = Math.max(
          0,
          width - statsLeftWidth - visibleWidth(truncatedRight),
        );
        const remainder = " ".repeat(padLen) + truncatedRight;
        line2 =
          theme.fg("dim", statsLeftFormatted) + theme.fg("dim", remainder);
      } else {
        line2 = truncateToWidth(
          theme.fg("dim", statsLeftFormatted),
          width,
          "...",
        );
      }
    }

    return [line1, line2];
  }

  private formatCwd(dir: string): string {
    if (!dir) return "";
    const home = os.homedir();
    const resolved = path.resolve(dir);
    const isWindows = process.platform === "win32";
    const normResolved = isWindows ? resolved.toLowerCase() : resolved;
    const normHome = isWindows ? home.toLowerCase() : home;

    if (normResolved === normHome) return "~";
    if (
      normResolved.startsWith(normHome + path.sep) ||
      normResolved.startsWith(normHome + "/")
    ) {
      return "~" + resolved.slice(home.length).replace(/\\/g, "/");
    }
    return resolved.replace(/\\/g, "/");
  }

  public formatTokens(count: number): string {
    return formatTokens(count);
  }
}
