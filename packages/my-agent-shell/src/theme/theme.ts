import chalk from "chalk";
import type { MarkdownTheme } from "@earendil-works/pi-tui";
import darkJson from "./dark.json" with { type: "json" };

export class ThemeManager {
  private colors = new Map<string, string>();

  constructor() {
    this.load(darkJson);
  }

  public load(json: { vars: Record<string, string>; colors: Record<string, string> }): void {
    const vars = json.vars || {};
    const colors = json.colors || {};

    for (const [name, val] of Object.entries(colors)) {
      const hex = vars[val] || val;
      this.colors.set(name, hex);
    }
  }

  public getHex(colorName: string): string {
    return this.colors.get(colorName) || "#d4d4d4";
  }

  public fg(colorName: string, text: string): string {
    const hex = this.getHex(colorName);
    return chalk.hex(hex)(text);
  }

  public bg(colorName: string, text: string): string {
    const hex = this.getHex(colorName);
    return chalk.bgHex(hex)(text);
  }

  public bold(text: string): string {
    return chalk.bold(text);
  }

  public italic(text: string): string {
    return chalk.italic(text);
  }

  public dim(text: string): string {
    return chalk.dim(text);
  }
}

export const theme = new ThemeManager();

export function getMarkdownTheme(): MarkdownTheme {
  return {
    heading: (text: string) => theme.bold(theme.fg("mdHeading", text)),
    link: (text: string) => theme.fg("mdLink", text),
    linkUrl: (text: string) => theme.fg("mdLinkUrl", text),
    code: (text: string) => theme.fg("mdCode", text),
    codeBlock: (text: string) => theme.fg("mdCodeBlock", text),
    codeBlockBorder: (text: string) => theme.fg("mdCodeBlockBorder", text),
    quote: (text: string) => theme.fg("mdQuote", text),
    quoteBorder: (text: string) => theme.fg("mdQuoteBorder", text),
    hr: (text: string) => theme.fg("mdHr", text),
    listBullet: (text: string) => theme.fg("mdListBullet", text),
    bold: (text: string) => theme.bold(text),
    italic: (text: string) => theme.italic(text),
    strikethrough: (text: string) => chalk.strikethrough(text),
    underline: (text: string) => chalk.underline(text),
  };
}
