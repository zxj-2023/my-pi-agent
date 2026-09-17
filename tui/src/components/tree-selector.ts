import {
  Container,
  matchesKey,
  Spacer,
  Text,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
import { isEnterKey } from "./keys.js";

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

export interface FlattenedTreeNode {
  node: TreeNode;
  depth: number;
  isLast: boolean;
  ancestorContinues: boolean[];
}

export function buildDAGTree(nodes: TreeNode[]): FlattenedTreeNode[] {
  const byId = new Map<
    string,
    { node: TreeNode; children: { node: TreeNode; children: any[] }[] }
  >();
  for (const n of nodes) {
    byId.set(n.id, { node: n, children: [] });
  }

  const roots: { node: TreeNode; children: any[] }[] = [];
  for (const n of nodes) {
    const item = byId.get(n.id)!;
    if (n.parent_id && byId.has(n.parent_id)) {
      byId.get(n.parent_id)!.children.push(item);
    } else {
      roots.push(item);
    }
  }

  const result: FlattenedTreeNode[] = [];
  const walk = (
    item: { node: TreeNode; children: any[] },
    depth: number,
    ancestorContinues: boolean[],
    isLast: boolean,
  ) => {
    result.push({ node: item.node, depth, isLast, ancestorContinues });
    for (let i = 0; i < item.children.length; i++) {
      const childIsLast = i === item.children.length - 1;
      const continues = depth > 0 ? !isLast : false;
      walk(
        item.children[i],
        depth + 1,
        [...ancestorContinues, continues],
        childIsLast,
      );
    }
  };

  for (let i = 0; i < roots.length; i++) {
    walk(roots[i], 0, [], i === roots.length - 1);
  }
  return result;
}

export function buildDAGTreePrefix(item: FlattenedTreeNode): string {
  if (item.depth === 0) {
    return "■ ";
  }
  const parts = item.ancestorContinues.map((c) => (c ? "│  " : "   "));
  const branch = item.isLast ? "└─ " : "├─ ";
  return parts.join("") + branch;
}

export class TreeSelectorComponent extends Container {
  private listContainer: Container;
  private allNodes: TreeNode[] = [];
  private displayNodes: FlattenedTreeNode[] = [];
  private selectedIndex = 0;
  private maxVisible = 12;
  private lastWidth = 80;
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

  public override render(width: number): string[] {
    this.lastWidth = width;
    return super.render(width);
  }

  public async reload(): Promise<void> {
    try {
      this.allNodes = await this.loadNodes();
    } catch {
      this.allNodes = [];
    }

    this.displayNodes = buildDAGTree(this.allNodes);

    // Default to currently active leaf or the last item
    const initialIdx = this.displayNodes.findIndex(
      (item) =>
        item.node.id === this.activeLeafId ||
        (item.node.is_active && item.node.is_leaf),
    );
    this.selectedIndex =
      initialIdx >= 0 ? initialIdx : Math.max(0, this.displayNodes.length - 1);

    this.updateList();
    if (this.requestRender) {
      this.requestRender();
    }
  }

  public updateList(): void {
    this.listContainer.clear();

    if (this.displayNodes.length === 0) {
      this.listContainer.addChild(
        new Text(theme.fg("muted", "  当前会话暂无节点记录。"), 0, 0),
      );
      return;
    }

    const startIndex = Math.max(
      0,
      Math.min(
        this.selectedIndex - Math.floor(this.maxVisible / 2),
        this.displayNodes.length - this.maxVisible,
      ),
    );
    const endIndex = Math.min(
      startIndex + this.maxVisible,
      this.displayNodes.length,
    );

    for (let i = startIndex; i < endIndex; i++) {
      const item = this.displayNodes[i];
      if (!item) continue;
      const node = item.node;
      const isSelected = i === this.selectedIndex;

      const cursor = isSelected ? theme.fg("accent", "› ") : "  ";
      const activeMarker = node.is_active ? theme.fg("accent", "* ") : "  ";

      const branchPrefix = buildDAGTreePrefix(item);
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
        // Pad dynamically to viewport width
        const pad = Math.max(0, this.lastWidth - 4 - visibleWidth(lineText));
        lineText = theme.bg("selectedBg", lineText + " ".repeat(pad));
      }

      this.listContainer.addChild(new Text(lineText, 0, 0));
    }

    if (startIndex > 0 || endIndex < this.displayNodes.length) {
      const scrollInfo = theme.fg(
        "muted",
        `  (${this.selectedIndex + 1}/${this.displayNodes.length})`,
      );
      this.listContainer.addChild(new Text(scrollInfo, 0, 0));
    }
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "up")) {
      if (this.displayNodes.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === 0
          ? this.displayNodes.length - 1
          : this.selectedIndex - 1;
      this.updateList();
    } else if (matchesKey(data, "down")) {
      if (this.displayNodes.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === this.displayNodes.length - 1
          ? 0
          : this.selectedIndex + 1;
      this.updateList();
    } else if (isEnterKey(data)) {
      const selected = this.displayNodes[this.selectedIndex]?.node;
      if (selected) this.onSelect(selected);
    } else if (matchesKey(data, "escape") || matchesKey(data, "ctrl+c")) {
      this.onCancel();
    }
  }
}
