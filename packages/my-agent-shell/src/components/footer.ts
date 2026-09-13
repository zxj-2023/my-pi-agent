import * as os from "node:os";
import { Container, Text } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

export interface FooterData {
  workspace: string;
  gitBranch?: string;
  modelName?: string;
  tokensUsed?: number;
  elapsedSeconds?: number;
  isBusy?: boolean;
}

export class FooterComponent extends Container {
  private data: FooterData = {
    workspace: process.cwd(),
    gitBranch: "main",
    modelName: "default",
    tokensUsed: 0,
    elapsedSeconds: 0,
    isBusy: false,
  };

  constructor(initialData?: Partial<FooterData>) {
    super();
    if (initialData) {
      this.data = { ...this.data, ...initialData };
    }
    this.updateDisplay();
  }

  public update(partial: Partial<FooterData>): void {
    this.data = { ...this.data, ...partial };
    this.updateDisplay();
  }

  private formatCwd(dir: string): string {
    const home = os.homedir();
    if (dir.startsWith(home)) {
      return "~" + dir.slice(home.length).replace(/\\/g, "/");
    }
    return dir.replace(/\\/g, "/");
  }

  private formatTokens(count: number): string {
    if (count < 1000) {
      return String(count);
    }
    if (count < 1_000_000) {
      return `${(count / 1000).toFixed(1)}k`;
    }
    return `${(count / 1_000_000).toFixed(1)}M`;
  }

  private updateDisplay(): void {
    this.clear();

    const cwdStr = this.formatCwd(this.data.workspace);
    const branchStr = this.data.gitBranch ? `\u{1f33f} ${this.data.gitBranch}` : "\u{1f33f} (no git)";
    const modelStr = `\u{1f916} ${this.data.modelName || "default"}`;
    const tokenStr = `\u{1f4ca} Tokens: ${this.formatTokens(this.data.tokensUsed || 0)}`;

    let line = `${theme.bold(theme.fg("accent", `\u{1f4c1} ${cwdStr}`))} ` +
      `[${theme.fg("success", branchStr)}] ` +
      `[${theme.fg("borderAccent", modelStr)}] ` +
      `[${theme.fg("warning", tokenStr)}]`;

    if (this.data.elapsedSeconds && this.data.elapsedSeconds > 0) {
      line += ` [${theme.dim(`\u23f1\ufe0f ${this.data.elapsedSeconds.toFixed(1)}s`)}]`;
    }

    if (this.data.isBusy) {
      line += ` ${theme.bold(theme.fg("warning", "\u27f3 思考计算中..."))}`;
    }

    this.addChild(new Text(line, 1, 0));
  }
}
