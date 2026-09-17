import * as os from "node:os";
import {
  Container,
  fuzzyMatch,
  Input,
  matchesKey,
  Spacer,
  Text,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
import { isEnterKey } from "./keys.js";

export interface SessionItem {
  id: string;
  name?: string;
  path?: string;
  cwd?: string;
  modified: number;
  message_count?: number;
  parent_session?: string;
  parent_session_path?: string;
}

export interface SessionTreeNode {
  session: SessionItem;
  children: SessionTreeNode[];
  latestActivity: number;
}

export interface FlattenedSessionNode {
  session: SessionItem;
  depth: number;
  isLast: boolean;
  ancestorContinues: boolean[];
}

function normalizeKey(k: string | undefined): string {
  if (!k) return "";
  return k.replace(/\\/g, "/").toLowerCase();
}

export function buildSessionTree(sessions: SessionItem[]): SessionTreeNode[] {
  const byKey = new Map<string, SessionTreeNode>();
  for (const s of sessions) {
    const node: SessionTreeNode = {
      session: s,
      children: [],
      latestActivity: s.modified * 1000,
    };
    byKey.set(s.id, node);
    byKey.set(s.id.toLowerCase(), node);
    if (s.path) {
      byKey.set(s.path, node);
      byKey.set(normalizeKey(s.path), node);
      const filename = s.path.split(/[/\\]/).pop() || "";
      const stem = filename.replace(/\.jsonl$/i, "");
      if (stem) {
        byKey.set(stem, node);
        byKey.set(stem.toLowerCase(), node);
      }
    }
  }

  const roots: SessionTreeNode[] = [];
  for (const s of sessions) {
    const node = byKey.get(s.id)!;
    const pKey = s.parent_session || s.parent_session_path;
    let parentNode: SessionTreeNode | undefined;
    if (pKey) {
      const pFilename = pKey.split(/[/\\]/).pop() || "";
      const pStem = pFilename.replace(/\.jsonl$/i, "");
      parentNode =
        byKey.get(pKey) ||
        byKey.get(normalizeKey(pKey)) ||
        byKey.get(pKey.toLowerCase()) ||
        (pStem
          ? byKey.get(pStem) || byKey.get(pStem.toLowerCase())
          : undefined);
    }

    if (parentNode && parentNode !== node) {
      parentNode.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const updateLatestActivity = (node: SessionTreeNode): number => {
    let latest = node.latestActivity;
    for (const child of node.children) {
      latest = Math.max(latest, updateLatestActivity(child));
    }
    node.latestActivity = latest;
    return latest;
  };

  for (const r of roots) {
    updateLatestActivity(r);
  }

  const sortNodes = (nodes: SessionTreeNode[]) => {
    nodes.sort((a, b) => b.latestActivity - a.latestActivity);
    for (const n of nodes) {
      sortNodes(n.children);
    }
  };
  sortNodes(roots);
  return roots;
}

export function flattenSessionTree(
  roots: SessionTreeNode[],
): FlattenedSessionNode[] {
  const result: FlattenedSessionNode[] = [];
  const walk = (
    node: SessionTreeNode,
    depth: number,
    ancestorContinues: boolean[],
    isLast: boolean,
  ) => {
    result.push({ session: node.session, depth, isLast, ancestorContinues });
    for (let i = 0; i < node.children.length; i++) {
      const childIsLast = i === node.children.length - 1;
      const continues = depth > 0 ? !isLast : false;
      walk(
        node.children[i],
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

export function buildTreePrefix(node: FlattenedSessionNode): string {
  if (node.depth === 0) {
    return "";
  }
  const parts = node.ancestorContinues.map((continues) =>
    continues ? "│  " : "   ",
  );
  const branch = node.isLast ? "└─ " : "├─ ";
  return parts.join("") + branch;
}

function shortenPath(p: string): string {
  const home = os.homedir();
  if (!p) return p;
  if (p.startsWith(home)) {
    return `~${p.slice(home.length)}`;
  }
  return p;
}

function formatSessionDate(timestampSec: number): string {
  const now = Date.now();
  const diffMs = now - timestampSec * 1000;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "now";
  if (diffMins < 60) return `${diffMins}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo`;
  return `${Math.floor(diffDays / 365)}y`;
}

export class SessionSelectorComponent extends Container {
  public searchInput: Input;
  private allSessions: SessionItem[] = [];
  private filteredSessions: SessionItem[] = [];
  private displayNodes: FlattenedSessionNode[] = [];
  private selectedIndex = 0;
  private maxVisible = 10;
  private scope: "current" | "all" = "current";
  private showPath = false;
  private confirmingDeleteId: string | null = null;
  private errorMessage: string | null = null;
  private errorTimeout: ReturnType<typeof setTimeout> | null = null;
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
    this.searchInput.focused = value;
  }

  constructor(
    private loadSessions: (allProjects: boolean) => Promise<SessionItem[]>,
    private onSelect: (session: SessionItem) => void,
    private onCancel: () => void,
    private requestRender?: () => void,
    private activeSessionId?: string,
    private onDelete?: (session: SessionItem) => Promise<void> | void,
  ) {
    super();
    this.searchInput = new Input();
    this.searchInput.onSubmit = () => {
      const selected = this.displayNodes[this.selectedIndex]?.session;
      if (selected) this.onSelect(selected);
    };

    void this.reload();
  }

  public async reload(): Promise<void> {
    try {
      this.allSessions = await this.loadSessions(this.scope === "all");
    } catch {
      this.allSessions = [];
    }
    this.applyFilter();
    this.rebuildUI();
    if (this.requestRender) {
      this.requestRender();
    }
  }

  private applyFilter(): void {
    const q = this.searchInput.getValue().trim().toLowerCase();
    if (q) {
      this.filteredSessions = this.allSessions.filter((s) => {
        const text = `${s.id} ${s.name || ""} ${s.cwd || ""}`.toLowerCase();
        return fuzzyMatch(q, text).matches || text.includes(q);
      });
      this.displayNodes = this.filteredSessions.map((s) => ({
        session: s,
        depth: 0,
        isLast: false,
        ancestorContinues: [],
      }));
    } else {
      this.filteredSessions = [...this.allSessions];
      const roots = buildSessionTree(this.allSessions);
      this.displayNodes = flattenSessionTree(roots);
    }
    this.selectedIndex = Math.min(
      this.selectedIndex,
      Math.max(0, this.displayNodes.length - 1),
    );
  }

  private rebuildUI(): void {
    this.clear();
    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));

    // Header Info
    const scopeLabel =
      this.scope === "current"
        ? "◉ Current Folder | ○ All"
        : "○ Current Folder | ◉ All";
    this.addChild(
      new Text(
        `${theme.bold("Resume Session")}               ${theme.fg("accent", scopeLabel)}`,
        1,
        0,
      ),
    );
    if (this.confirmingDeleteId !== null) {
      this.addChild(
        new Text(
          theme.fg("error", "Delete session? Enter to confirm · Esc to cancel"),
          1,
          0,
        ),
      );
    } else if (this.errorMessage === null) {
      this.addChild(
        new Text(
          theme.fg(
            "muted",
            "Tab: scope · Ctrl+D: delete · Ctrl+P: path · Enter: resume · Esc: cancel",
          ),
          1,
          0,
        ),
      );
    } else {
      this.addChild(new Text(theme.fg("error", this.errorMessage), 1, 0));
    }
    this.addChild(new Spacer(1));

    // Search Input
    this.addChild(this.searchInput);
    this.addChild(new Spacer(1));

    // List rendering
    if (this.displayNodes.length === 0) {
      this.addChild(
        new Text(theme.fg("muted", "  未发现匹配的历史会话。"), 1, 0),
      );
    } else {
      const start = Math.max(
        0,
        Math.min(
          this.selectedIndex - Math.floor(this.maxVisible / 2),
          this.displayNodes.length - this.maxVisible,
        ),
      );
      const end = Math.min(start + this.maxVisible, this.displayNodes.length);

      for (let i = start; i < end; i++) {
        const node = this.displayNodes[i];
        if (!node) continue;
        const s = node.session;
        const isSelected = i === this.selectedIndex;
        const isCurrent = s.id === this.activeSessionId;

        const isConfirming = s.id === this.confirmingDeleteId;
        const deletePrefix = isConfirming
          ? theme.fg("error", "[delete?] ")
          : "";
        const cursor = isSelected ? theme.fg("accent", "› ") : "  ";

        const treePrefix = buildTreePrefix(node);
        let titleText = s.name || s.id;
        if (isConfirming) {
          titleText = theme.fg("error", titleText);
        } else if (isCurrent) {
          titleText = theme.fg("accent", titleText);
        } else if (s.name) {
          titleText = theme.fg("warning", titleText);
        }

        const msgInfo = `${s.message_count || 0}`;
        const timeInfo = formatSessionDate(s.modified);
        let meta = `${msgInfo} ${timeInfo}`;

        if (this.scope === "all" && s.cwd) {
          meta = `${shortenPath(s.cwd)}  ${meta}`;
        }
        if (this.showPath && s.path) {
          meta = `${shortenPath(s.path)}  ${meta}`;
        }

        const left =
          cursor +
          deletePrefix +
          theme.fg("dim", treePrefix) +
          (isSelected ? theme.bold(titleText) : titleText);
        const right = theme.fg(isConfirming ? "error" : "dim", meta);
        const pad = Math.max(2, 75 - visibleWidth(left) - visibleWidth(right));

        let rowStr = left + " ".repeat(pad) + right;
        if (isSelected) {
          rowStr = theme.bg("selectedBg", rowStr);
        }
        this.addChild(new Text(rowStr, 1, 0));
      }

      if (this.displayNodes.length > this.maxVisible) {
        this.addChild(
          new Text(
            theme.fg(
              "muted",
              `  (${this.selectedIndex + 1}/${this.displayNodes.length})`,
            ),
            1,
            0,
          ),
        );
      }
    }

    this.addChild(new Spacer(1));
    this.addChild(new DynamicBorder());
  }

  public handleInput(data: string): void {
    // 处于删除二次确认拦截模式
    if (this.confirmingDeleteId !== null) {
      if (isEnterKey(data)) {
        const toDelete = this.displayNodes.find(
          (n) => n.session.id === this.confirmingDeleteId,
        )?.session;
        if (toDelete) {
          this.executeDelete(toDelete);
        }
        return;
      }
      if (matchesKey(data, "escape") || matchesKey(data, "ctrl+c")) {
        this.confirmingDeleteId = null;
        this.rebuildUI();
        if (this.requestRender) this.requestRender();
        return;
      }
      return;
    }

    if (matchesKey(data, "escape") || matchesKey(data, "ctrl+c")) {
      this.onCancel();
      return;
    }

    if (matchesKey(data, "ctrl+d")) {
      const selected = this.displayNodes[this.selectedIndex]?.session;
      if (selected) {
        if (selected.id === this.activeSessionId) {
          this.setErrorMessage("Cannot delete the currently active session");
          return;
        }
        this.confirmingDeleteId = selected.id;
        this.rebuildUI();
        if (this.requestRender) this.requestRender();
      }
      return;
    }

    if (matchesKey(data, "tab")) {
      this.scope = this.scope === "current" ? "all" : "current";
      void this.reload();
      return;
    }

    if (matchesKey(data, "ctrl+p")) {
      this.showPath = !this.showPath;
      this.rebuildUI();
      if (this.requestRender) this.requestRender();
      return;
    }

    if (matchesKey(data, "up")) {
      this.selectedIndex = Math.max(0, this.selectedIndex - 1);
      this.rebuildUI();
      if (this.requestRender) this.requestRender();
      return;
    }

    if (matchesKey(data, "down")) {
      this.selectedIndex = Math.min(
        this.displayNodes.length - 1,
        this.selectedIndex + 1,
      );
      this.rebuildUI();
      if (this.requestRender) this.requestRender();
      return;
    }

    if (isEnterKey(data)) {
      const selected = this.displayNodes[this.selectedIndex]?.session;
      if (selected) {
        this.onSelect(selected);
        return;
      }
    }

    const prevQuery = this.searchInput.getValue();
    this.searchInput.handleInput?.(data);
    if (this.searchInput.getValue() !== prevQuery) {
      this.applyFilter();
      this.rebuildUI();
      if (this.requestRender) this.requestRender();
    }
  }

  private setErrorMessage(msg: string): void {
    if (this.errorTimeout) {
      clearTimeout(this.errorTimeout);
    }
    this.errorMessage = msg;
    this.rebuildUI();
    if (this.requestRender) this.requestRender();
    this.errorTimeout = setTimeout(() => {
      this.errorMessage = null;
      this.errorTimeout = null;
      this.rebuildUI();
      if (this.requestRender) this.requestRender();
    }, 2500);
  }

  private executeDelete(session: SessionItem): void {
    this.confirmingDeleteId = null;
    if (this.onDelete) {
      void Promise.resolve(this.onDelete(session)).then(() => {
        void this.reload();
      });
    } else {
      this.allSessions = this.allSessions.filter((s) => s.id !== session.id);
      this.applyFilter();
      this.rebuildUI();
      if (this.requestRender) this.requestRender();
    }
  }
}
