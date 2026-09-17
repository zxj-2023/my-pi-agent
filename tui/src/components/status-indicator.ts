import { Loader, truncateToWidth } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

/**
 * 基础状态指示器（100% 对标 Pi 原厂 StatusIndicator）：继承 Loader 带有 80ms 动态旋转帧
 */
export class StatusIndicator extends Loader {
  public kind: string;

  constructor(
    kind: string,
    ui: any,
    spinnerColorFn: (spinner: string) => string,
    messageColorFn: (msg: string) => string,
    message: string,
    indicator?: any,
  ) {
    super(ui, spinnerColorFn, messageColorFn, message, indicator);
    this.kind = kind;
    // unref 内部定时器，防止挂死 Node 进程或测试退出
    const timer = (this as any).intervalId;
    if (timer && typeof timer.unref === "function") {
      timer.unref();
    }
  }

  public dispose(): void {
    this.stop();
  }
}

/**
 * 运行中状态指示器（100% 对标 Pi 原厂 WorkingStatusIndicator）：
 * 可直接嵌入 CustomEditor 顶部边框，展示转圈动效：── ⠸ Working ───────────
 */
export class WorkingStatusIndicator extends StatusIndicator {
  constructor(
    ui: any,
    message = "Working",
    indicator?: any,
    colorFn?: (text: string) => string,
  ) {
    super(
      "working",
      ui,
      colorFn ?? ((text: string) => theme.fg("accent", text)),
      colorFn ?? ((text: string) => theme.fg("muted", text)),
      message,
      indicator,
    );
  }

  public override start(): void {
    super.start();
    const timer = (this as any).intervalId;
    if (timer && typeof timer.unref === "function") {
      timer.unref();
    }
  }

  public renderInBorder(width: number): string {
    const lines = super.render(width + 2);
    const line = lines[1] ?? lines[0] ?? "";
    const clean = line.startsWith(" ") ? line.slice(1).trimEnd() : line.trimEnd();
    return truncateToWidth(clean, width, "");
  }

  public renderSpinnerInBorder(width: number): string {
    const ind = (this as any).getRenderedIndicator?.() ?? "⠋";
    return truncateToWidth(ind, width, "");
  }
}

/**
 * 上下文压缩状态指示器（对标 Pi 原厂 CompactionStatusIndicator）
 */
export class CompactionStatusIndicator extends StatusIndicator {
  constructor(ui: any, reason: "manual" | "overflow" = "manual") {
    const cancelHint = "(Esc to cancel)";
    const label =
      reason === "manual"
        ? `Compacting context... ${cancelHint}`
        : "Context overflow, auto-compacting... (Esc to cancel)";
    super(
      "compaction",
      ui,
      (spinner: string) => theme.fg("accent", spinner),
      (text: string) => theme.fg("muted", text),
      label,
    );
  }

  public override start(): void {
    super.start();
    const timer = (this as any).intervalId;
    if (timer && typeof timer.unref === "function") {
      timer.unref();
    }
  }
}
