import {
  Container,
  matchesKey,
  Spacer,
  Text,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";

export interface TreeNode {
  id: string;
  parent_id: string | null;
  role: string;
  type: string;
  preview: string;
  is_leaf: boolean;
  is_active: boolean;
  timestamp: number;
}

export class TreeSelectorComponent extends Container {
  private listContainer: Container;
  private allNodes: TreeNode[] = [];
  private selectedIndex = 0;
  private maxVisible = 12;
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
  }

  constructor(
    private loadNodes: () => Promise<TreeNode[]>,
    public readonly onSelect: (node: TreeNode) => void,
    public readonly onCancel: () => void,
    public readonly activeLeafId?: string,
    private requestRender?: () => void,
  ) {
    super();

    this.listContainer = new Container();

    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));
    this.addChild(new Text(theme.bold("Session Tree (DAG Explorer)"), 0, 0));
    this.addChild(
      new Text(
        theme.fg(
          "muted",
          "Enter: switch to branch · Up/Down: navigate · Esc: exit",
        ),
        0,
        0,
      ),
    );
    this.addChild(new Spacer(1));

    this.addChild(this.listContainer);
    this.addChild(new Spacer(1));

    this.addChild(
      new Text(
        theme.fg(
          "dim",
          "  Enter to switch branch · Up/Down to navigate · Escape to cancel",
        ),
        0,
        0,
      ),
    );
    this.addChild(new DynamicBorder());

    void this.reload();
  }

  public async reload(): Promise<void> {
    try {
      this.allNodes = await this.loadNodes();
    } catch {
      this.allNodes = [];
    }

    // Default to currently active leaf or the last item
    const initialIdx = this.allNodes.findIndex(
      (n) => n.id === this.activeLeafId || (n.is_active && n.is_leaf),
    );
    this.selectedIndex =
      initialIdx >= 0 ? initialIdx : Math.max(0, this.allNodes.length - 1);

    this.updateList();
    if (this.requestRender) {
      this.requestRender();
    }
  }

  public updateList(): void {
    this.listContainer.clear();

    if (this.allNodes.length === 0) {
      this.listContainer.addChild(
        new Text(theme.fg("muted", "  当前会话暂无节点记录。"), 0, 0),
      );
      return;
    }

    const startIndex = Math.max(
      0,
      Math.min(
        this.selectedIndex - Math.floor(this.maxVisible / 2),
        this.allNodes.length - this.maxVisible,
      ),
    );
    const endIndex = Math.min(
      startIndex + this.maxVisible,
      this.allNodes.length,
    );

    for (let i = startIndex; i < endIndex; i++) {
      const node = this.allNodes[i];
      if (!node) continue;
      const isSelected = i === this.selectedIndex;

      const cursor = isSelected ? theme.fg("accent", "› ") : "  ";
      const activeMarker = node.is_active ? theme.fg("accent", "* ") : "  ";

      const branchPrefix = node.parent_id === null ? "■ " : "├─ ";
      let roleBadge = `[${node.role}]`;
      if (node.role === "user") {
        roleBadge = theme.fg("accent", roleBadge);
      } else if (node.role === "assistant") {
        roleBadge = theme.fg("success", roleBadge);
      } else {
        roleBadge = theme.fg("muted", roleBadge);
      }

      let lineText = `${cursor}${activeMarker}${theme.fg("dim", branchPrefix)}${roleBadge} ${node.preview}`;
      if (node.id === this.activeLeafId || (node.is_active && node.is_leaf)) {
        lineText += theme.fg("accent", " [ACTIVE LEAF]");
      }

      if (isSelected) {
        // Pad to line width
        const pad = Math.max(0, 80 - visibleWidth(lineText));
        lineText = theme.bg("selectedBg", lineText + " ".repeat(pad));
      }

      this.listContainer.addChild(new Text(lineText, 0, 0));
    }

    if (startIndex > 0 || endIndex < this.allNodes.length) {
      const scrollInfo = theme.fg(
        "muted",
        `  (${this.selectedIndex + 1}/${this.allNodes.length})`,
      );
      this.listContainer.addChild(new Text(scrollInfo, 0, 0));
    }
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "up")) {
      if (this.allNodes.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === 0
          ? this.allNodes.length - 1
          : this.selectedIndex - 1;
      this.updateList();
    } else if (matchesKey(data, "down")) {
      if (this.allNodes.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === this.allNodes.length - 1
          ? 0
          : this.selectedIndex + 1;
      this.updateList();
    } else if (matchesKey(data, "return")) {
      const selected = this.allNodes[this.selectedIndex];
      if (selected) this.onSelect(selected);
    } else if (matchesKey(data, "escape")) {
      this.onCancel();
    }
  }
}
