import { Box, Container, Spacer, Text } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

const MAX_PREVIEW_LINES = 15;

export class ToolExecutionComponent extends Container {
  private box: Box;
  private isFinished = false;
  private isError = false;
  private isExpanded = false;
  private resultText = "";
  private elapsedSeconds = 0;

  constructor(
    public readonly toolName: string,
    public readonly toolCallId: string,
    public args: Record<string, unknown> = {},
  ) {
    super();

    this.addChild(new Spacer(1));
    this.box = new Box(1, 1, (t: string) => theme.bg("toolPendingBg", t));
    this.addChild(this.box);
    this.updateDisplay();
  }

  public updateArgs(args: Record<string, unknown>): void {
    this.args = args;
    this.updateDisplay();
  }

  public updateResult(
    result: unknown,
    isError: boolean,
    elapsedSeconds = 0,
  ): void {
    this.isFinished = true;
    this.isError = isError;
    this.elapsedSeconds = elapsedSeconds;

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
    let icon = theme.fg("warning", "\u27f3");
    let statusSuffix = "";
    if (this.isFinished) {
      if (this.isError) {
        icon = theme.fg("error", "\u2717");
        statusSuffix = theme.fg("error", " (失败)");
      } else {
        icon = theme.fg("success", "\u2713");
        statusSuffix =
          this.elapsedSeconds > 0
            ? theme.fg("dim", ` (${this.elapsedSeconds.toFixed(1)}s)`)
            : "";
      }
    }

    const titleText = `${icon} ${theme.bold(theme.fg("toolTitle", this.toolName))} ${theme.fg("dim", this.formatArgs())}${statusSuffix}`;
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
    }
  }
}
