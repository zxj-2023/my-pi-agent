import { Editor, visibleWidth } from "@earendil-works/pi-tui";
import { type StatusIndicator } from "./status-indicator.js";

export interface CustomEditorOptions {
  embedWorkingStatus?: boolean;
  paddingX?: number;
  autocompleteMaxVisible?: number;
}

/**
 * 扩展版 Editor（100% 对标 Pi 原厂 CustomEditor）：
 * 支持在输入框顶部边框实时嵌入转圈动效：── ⠸ Working ─────────────────────────
 */
export class CustomEditor extends Editor {
  public embedWorkingStatus: boolean;
  private workingStatusIndicator?: StatusIndicator;

  constructor(tui: any, theme: any, options?: CustomEditorOptions) {
    super(tui, theme, options);
    this.embedWorkingStatus = options?.embedWorkingStatus ?? true;
  }

  public setWorkingStatusIndicator(indicator?: StatusIndicator): void {
    this.workingStatusIndicator = indicator;
    this.tui.requestRender();
  }

  public override renderTopBorder(
    width: number,
    hiddenLineCount: number,
  ): string {
    if (
      !this.embedWorkingStatus ||
      !this.workingStatusIndicator ||
      width <= 0
    ) {
      return super.renderTopBorder(width, hiddenLineCount);
    }

    let status = this.workingStatusIndicator.renderInBorder(
      Math.max(1, width - 5),
    );
    let statusWidth = visibleWidth(status);
    if (statusWidth === 0) {
      return super.renderTopBorder(width, hiddenLineCount);
    }

    const overflowLabel =
      hiddenLineCount > 0 ? ` ↑ ${hiddenLineCount} more ` : undefined;
    const overflowLabelWidth = overflowLabel ? visibleWidth(overflowLabel) : 0;
    const overflowStart = Math.floor((width - overflowLabelWidth) / 2);
    const canFitOverflow = () =>
      overflowLabel !== undefined &&
      overflowLabelWidth + 2 <= width &&
      overflowStart - (3 + statusWidth + 1) >= 1;

    if (overflowLabel && !canFitOverflow()) {
      status = this.workingStatusIndicator.renderSpinnerInBorder(width);
      statusWidth = visibleWidth(status);
    }

    if (canFitOverflow()) {
      const leftBlockWidth = 3 + statusWidth + 1;
      return (
        this.borderColor("── ") +
        status +
        this.borderColor(
          ` ${"─".repeat(overflowStart - leftBlockWidth)}${overflowLabel}${"─".repeat(
            Math.max(0, width - overflowStart - overflowLabelWidth),
          )}`,
        )
      );
    }

    if (width >= statusWidth + 5) {
      return (
        this.borderColor("── ") +
        status +
        this.borderColor(` ${"─".repeat(Math.max(0, width - statusWidth - 4))}`)
      );
    }

    status = this.workingStatusIndicator.renderSpinnerInBorder(width);
    statusWidth = visibleWidth(status);
    const prefixWidth = Math.min(3, Math.max(0, width - statusWidth));
    return (
      this.borderColor("─".repeat(prefixWidth)) +
      status +
      this.borderColor(
        "─".repeat(Math.max(0, width - prefixWidth - statusWidth)),
      )
    );
  }
}
