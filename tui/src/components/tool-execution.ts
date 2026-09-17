import { Box, Container, Spacer, Text } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

export const SPINNER_FRAMES = [
  "⠋",
  "⠙",
  "⠹",
  "⠸",
  "⠼",
  "⠴",
  "⠦",
  "⠧",
  "⠇",
  "⠏",
];
const SPINNER_INTERVAL_MS = 80;
const MAX_PREVIEW_LINES = 15;

export class ToolExecutionComponent extends Container {
  private box: Box;
  private isFinished = false;
  private isError = false;
  private isExpanded = false;
  private resultText = "";
  private partialOutput = "";
  private elapsedSeconds = 0;
  private startTime = Date.now();
  private spinnerFrame = 0;
  private animInterval: ReturnType<typeof setInterval> | null = null;

  constructor(
    public readonly toolName: string,
    public readonly toolCallId: string,
    public args: Record<string, unknown> = {},
    private readonly onRequestRender?: () => void,
  ) {
    super();

    this.addChild(new Spacer(1));
    this.box = new Box(1, 1, (t: string) => theme.bg("toolPendingBg", t));
    this.addChild(this.box);
    this.updateDisplay();
    this.startAnimation();
  }

  private startAnimation(): void {
    if (this.isFinished || this.animInterval) return;
    this.animInterval = setInterval(() => {
      if (this.isFinished) {
        this.stopAnimation();
        return;
      }
      this.spinnerFrame = (this.spinnerFrame + 1) % SPINNER_FRAMES.length;
      this.updateDisplay();
      if (this.onRequestRender) {
        this.onRequestRender();
      }
    }, SPINNER_INTERVAL_MS);
    if (typeof this.animInterval?.unref === "function") {
      this.animInterval.unref();
    }
  }

  private stopAnimation(): void {
    if (this.animInterval) {
      clearInterval(this.animInterval);
      this.animInterval = null;
    }
  }

  public dispose(): void {
    this.stopAnimation();
  }

  public get finished(): boolean {
    return this.isFinished;
  }

  public get elapsed(): number {
    if (this.isFinished) {
      return this.elapsedSeconds;
    }
    return Math.max(0, (Date.now() - this.startTime) / 1000);
  }

  public updateArgs(args: Record<string, unknown>): void {
    this.args = args;
    this.updateDisplay();
  }

  public updatePartialResult(partial: unknown): void {
    if (this.isFinished) return;
    if (typeof partial === "string") {
      this.partialOutput = partial;
    } else if (partial && typeof partial === "object") {
      const data = (partial as Record<string, unknown>).data;
      this.partialOutput = String(data || JSON.stringify(partial));
    } else {
      this.partialOutput = String(partial ?? "");
    }
    this.updateDisplay();
    if (this.onRequestRender) {
      this.onRequestRender();
    }
  }

  public updateResult(
    result: unknown,
    isError: boolean,
    elapsedSeconds?: number,
  ): void {
    this.stopAnimation();
    this.isFinished = true;
    this.isError = isError;
    this.partialOutput = "";
    this.elapsedSeconds =
      elapsedSeconds !== undefined && elapsedSeconds >= 0
        ? elapsedSeconds
        : Math.max(0, (Date.now() - this.startTime) / 1000);

    if (typeof result === "string") {
      this.resultText = result;
    } else if (result && typeof result === "object") {
      const data = (result as Record<string, unknown>).data;
      const error = (result as Record<string, unknown>).error;
      this.resultText = String(data || error || JSON.stringify(result));
    } else {
      this.resultText = String(result ?? "");
    }

    this.box.setBgFn((t: string) =>
      theme.bg(this.isError ? "toolErrorBg" : "toolSuccessBg", t),
    );
    this.updateDisplay();
  }

  public toggleExpanded(): void {
    this.isExpanded = !this.isExpanded;
    this.updateDisplay();
  }

  public override render(width: number): string[] {
    if (!this.isFinished) {
      this.updateDisplay();
    }
    return super.render(width);
  }

  private formatArgs(): string {
    const keys = Object.keys(this.args);
    if (keys.length === 0) {
      return "";
    }
    const parts = keys.map((k) => {
      const val = this.args[k];
      let s = typeof val === "object" ? JSON.stringify(val) : String(val);
      if (s.length > 50) {
        s = s.slice(0, 47) + "...";
      }
      return `${k}=${s}`;
    });
    return `(${parts.join(", ")})`;
  }

  private updateDisplay(): void {
    this.box.clear();

    // 1. Header
    const spinnerChar = SPINNER_FRAMES[this.spinnerFrame] || "⠋";
    let icon = theme.fg("warning", spinnerChar);
    let statusSuffix = "";
    if (this.isFinished) {
      if (this.isError) {
        icon = theme.fg("error", "✗");
        statusSuffix = theme.fg("error", "(失败)");
      } else {
        icon = theme.fg("success", "✓");
        statusSuffix = theme.fg("dim", `(${this.elapsedSeconds.toFixed(1)}s)`);
      }
    } else {
      statusSuffix = theme.fg("dim", `Elapsed ${this.elapsed.toFixed(1)}s`);
    }

    const argsStr = this.formatArgs();
    const parts = [icon, theme.bold(theme.fg("toolTitle", this.toolName))];
    if (argsStr) {
      parts.push(theme.fg("dim", argsStr));
    }
    if (statusSuffix) {
      parts.push(statusSuffix);
    }
    const titleText = parts.join(" ");
    this.box.addChild(new Text(titleText, 0, 0));

    // 2. Result Output (if finished)
    if (this.isFinished && this.resultText.trim()) {
      this.box.addChild(new Spacer(1));
      const lines = this.resultText.trim().split("\n");
      let renderedText = "";

      if (this.isExpanded || lines.length <= MAX_PREVIEW_LINES) {
        renderedText = lines.map((l) => theme.fg("toolOutput", l)).join("\n");
      } else {
        const preview = lines.slice(0, MAX_PREVIEW_LINES);
        const remaining = lines.length - MAX_PREVIEW_LINES;
        renderedText = preview.map((l) => theme.fg("toolOutput", l)).join("\n");
        renderedText += `\n${theme.dim(`... (剩余 ${remaining} 行，按 Ctrl+O 展开查看)`)}`;
      }

      this.box.addChild(new Text(renderedText, 0, 0));
    } else if (!this.isFinished && this.partialOutput.trim()) {
      // 正在运行中的实时流式输出预览 (对标 Pi bash renderer options.isPartial)
      this.box.addChild(new Spacer(1));
      const lines = this.partialOutput.trim().split("\n");
      const previewLines = lines.slice(-MAX_PREVIEW_LINES);
      const renderedText = previewLines
        .map((l) => theme.fg("dim", l))
        .join("\n");
      this.box.addChild(new Text(renderedText, 0, 0));
    }
  }
}
