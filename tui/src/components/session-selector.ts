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
  private selectedIndex = 0;
  private maxVisible = 10;
  private scope: "current" | "all" = "current";
  private showPath = false;
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
  ) {
    super();
    this.searchInput = new Input();
    this.searchInput.onSubmit = () => {
      const selected = this.filteredSessions[this.selectedIndex];
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
    } else {
      this.filteredSessions = [...this.allSessions];
    }
    this.selectedIndex = Math.min(
      this.selectedIndex,
      Math.max(0, this.filteredSessions.length - 1),
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
    this.addChild(
      new Text(
        theme.fg(
          "muted",
          "Tab: scope · Ctrl+P: path · Enter: resume · Esc: cancel",
        ),
        1,
        0,
      ),
    );
    this.addChild(new Spacer(1));

    // Search Input
    this.addChild(this.searchInput);
    this.addChild(new Spacer(1));

    // List rendering
    if (this.filteredSessions.length === 0) {
      this.addChild(
        new Text(theme.fg("muted", "  未发现匹配的历史会话。"), 1, 0),
      );
    } else {
      const start = Math.max(
        0,
        Math.min(
          this.selectedIndex - Math.floor(this.maxVisible / 2),
          this.filteredSessions.length - this.maxVisible,
        ),
      );
      const end = Math.min(
        start + this.maxVisible,
        this.filteredSessions.length,
      );

      for (let i = start; i < end; i++) {
        const s = this.filteredSessions[i];
        if (!s) continue;
        const isSelected = i === this.selectedIndex;
        const isCurrent = s.id === this.activeSessionId;

        const cursor = isSelected ? theme.fg("accent", "› ") : "  ";
        const titleText = isCurrent
          ? theme.fg("accent", s.name || s.id)
          : s.name || s.id;
        const msgInfo = `${s.message_count || 0} msgs`;
        const timeInfo = formatSessionDate(s.modified);
        let meta = `${msgInfo}  ${timeInfo}`;

        if (this.scope === "all" && s.cwd) {
          meta = `${shortenPath(s.cwd)}  ${meta}`;
        }
        if (this.showPath && s.path) {
          meta = `${shortenPath(s.path)}  ${meta}`;
        }

        const left = cursor + (isSelected ? theme.bold(titleText) : titleText);
        const right = theme.fg("dim", meta);
        const pad = Math.max(2, 75 - visibleWidth(left) - visibleWidth(right));

        let rowStr = left + " ".repeat(pad) + right;
        if (isSelected) {
          rowStr = theme.bg("selectedBg", rowStr);
        }
        this.addChild(new Text(rowStr, 1, 0));
      }

      if (this.filteredSessions.length > this.maxVisible) {
        this.addChild(
          new Text(
            theme.fg(
              "muted",
              `  (${this.selectedIndex + 1}/${this.filteredSessions.length})`,
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
      if (this.filteredSessions.length === 0) return;
      this.selectedIndex = Math.max(0, this.selectedIndex - 1);
      this.rebuildUI();
      if (this.requestRender) this.requestRender();
      return;
    }
    if (matchesKey(data, "down")) {
      if (this.filteredSessions.length === 0) return;
      this.selectedIndex = Math.min(
        this.filteredSessions.length - 1,
        this.selectedIndex + 1,
      );
      this.rebuildUI();
      if (this.requestRender) this.requestRender();
      return;
    }
    if (matchesKey(data, "escape") || matchesKey(data, "ctrl+c")) {
      this.onCancel();
      return;
    }
    if (isEnterKey(data)) {
      const selected =
        this.filteredSessions[this.selectedIndex] || this.filteredSessions[0];
      if (selected) {
        this.onSelect(selected);
      }
      return;
    }

    // 转发常规键入字符到搜索输入框
    this.searchInput.handleInput(data);
    this.applyFilter();
    this.rebuildUI();
    if (this.requestRender) this.requestRender();
  }
}
