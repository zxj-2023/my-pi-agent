import * as os from "node:os";
import * as path from "node:path";
import {
  Container,
  truncateToWidth,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

export interface FooterData {
  workspace: string;
  gitBranch?: string;
  sessionName?: string;
  providerName?: string;
  modelName?: string;
  thinkingLevel?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  tokensUsed?: number; // 兼容旧版调用场景
  contextWindow?: number;
  costUsd?: number;
  elapsedSeconds?: number;
  isBusy?: boolean;
}

export class FooterComponent extends Container {
  private data: FooterData;

  constructor(initialData?: Partial<FooterData>) {
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
  }

  public update(partial: Partial<FooterData>): void {
    this.data = { ...this.data, ...partial };
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

    // 2. 第二行左侧：Token 指标与实时状态
    const statsParts: string[] = [];
    if (this.data.inputTokens && this.data.inputTokens > 0) {
      statsParts.push(`↑${this.formatTokens(this.data.inputTokens)}`);
    }
    if (this.data.outputTokens && this.data.outputTokens > 0) {
      statsParts.push(`↓${this.formatTokens(this.data.outputTokens)}`);
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

    const totalTok =
      this.data.totalTokens ??
      this.data.tokensUsed ??
      (this.data.inputTokens || 0) + (this.data.outputTokens || 0);
    const contextWin = this.data.contextWindow || 128000;
    const percent = (totalTok / contextWin) * 100;
    const percentStr = `${percent.toFixed(1)}%/${this.formatTokens(contextWin)}`;
    const contextColor =
      percent > 90 ? "error" : percent > 70 ? "warning" : "dim";
    statsParts.push(theme.fg(contextColor, percentStr));

    if (this.data.elapsedSeconds && this.data.elapsedSeconds > 0) {
      statsParts.push(
        theme.fg("dim", `${this.data.elapsedSeconds.toFixed(1)}s`),
      );
    }
    if (this.data.isBusy) {
      statsParts.push(theme.fg("warning", "⠋"));
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

  private formatTokens(count: number): string {
    if (count < 1000) return String(count);
    if (count < 1000000) {
      const k = count / 1000;
      const formatted = k.toFixed(1);
      return formatted.endsWith(".0") ? `${Math.round(k)}k` : `${formatted}k`;
    }
    const m = count / 1000000;
    const formatted = m.toFixed(1);
    return formatted.endsWith(".0") ? `${Math.round(m)}M` : `${formatted}M`;
  }
}
