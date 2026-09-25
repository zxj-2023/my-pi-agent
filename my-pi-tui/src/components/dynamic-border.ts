import { theme } from "../theme/theme.js";

/**
 * 宽度自适应横向边界线组件 (100% 对标 Pi DynamicBorder)
 */
export class DynamicBorder {
  constructor(
    public color: (str: string) => string = (str) =>
      theme.fg("borderMuted", str),
  ) {}

  public invalidate(): void {}

  public render(width: number): string[] {
    return [this.color("─".repeat(Math.max(1, width)))];
  }
}
