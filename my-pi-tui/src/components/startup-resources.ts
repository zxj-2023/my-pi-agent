import { Container, Spacer, Text } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

export interface LoadedResourcesData {
  context?: string[];
  skills?: string[];
  prompts?: string[];
  extensions?: string[];
}

export class StartupResourcesComponent extends Container {
  private data: LoadedResourcesData;
  private isExpanded = false;
  private contentTextComponent: Text;

  constructor(data?: LoadedResourcesData) {
    super();
    this.data = data || {};
    this.contentTextComponent = new Text("", 0, 0);
    this.addChild(this.contentTextComponent);
    this.addChild(new Spacer(1));
    this.updateDisplay();
  }

  public updateData(data: LoadedResourcesData): void {
    this.data = data;
    this.updateDisplay();
  }

  public toggleExpanded(): void {
    this.isExpanded = !this.isExpanded;
    this.updateDisplay();
  }

  public getExpanded(): boolean {
    return this.isExpanded;
  }

  private wrapList(items: string[], indent = "  ", maxWidth = 100): string[] {
    if (!items || items.length === 0) return [];
    const lines: string[] = [];
    let currentLine = indent;
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const separator = i < items.length - 1 ? ", " : "";
      const toAdd = item + separator;
      if (
        currentLine.length + toAdd.length > maxWidth &&
        currentLine.trim().length > 0
      ) {
        lines.push(currentLine);
        currentLine = indent + toAdd;
      } else {
        currentLine += toAdd;
      }
    }
    if (currentLine.trim().length > 0) {
      lines.push(currentLine);
    }
    return lines;
  }

  public updateDisplay(): void {
    const sections: string[] = [];

    // 1. [Context]
    if (this.data.context && this.data.context.length > 0) {
      sections.push(theme.fg("mdHeading", "[Context]"));
      for (const c of this.data.context) {
        sections.push(theme.fg("dim", `  ${c}`));
      }
      sections.push("");
    }

    // 2. [Skills]
    if (this.data.skills && this.data.skills.length > 0) {
      sections.push(theme.fg("mdHeading", "[Skills]"));
      if (this.isExpanded) {
        for (const s of this.data.skills) {
          sections.push(theme.fg("dim", `  ${s}`));
        }
      } else {
        const wrapped = this.wrapList(this.data.skills, "  ", 100);
        for (const line of wrapped) {
          sections.push(theme.fg("dim", line));
        }
      }
      sections.push("");
    }

    // 3. [Prompts]
    if (this.data.prompts && this.data.prompts.length > 0) {
      sections.push(theme.fg("mdHeading", "[Prompts]"));
      if (this.isExpanded) {
        for (const p of this.data.prompts) {
          sections.push(theme.fg("dim", `  ${p}`));
        }
      } else {
        const wrapped = this.wrapList(this.data.prompts, "  ", 100);
        for (const line of wrapped) {
          sections.push(theme.fg("dim", line));
        }
      }
      sections.push("");
    }

    // 4. [Extensions]
    if (this.data.extensions && this.data.extensions.length > 0) {
      sections.push(theme.fg("mdHeading", "[Extensions]"));
      if (this.isExpanded) {
        for (const e of this.data.extensions) {
          sections.push(theme.fg("dim", `  ${e}`));
        }
      } else {
        const wrapped = this.wrapList(this.data.extensions, "  ", 100);
        for (const line of wrapped) {
          sections.push(theme.fg("dim", line));
        }
      }
    }

    const textContent = sections.join("\n").trim();
    this.contentTextComponent.setText(textContent);
  }
}
