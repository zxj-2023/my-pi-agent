import {
  Container,
  fuzzyFilter,
  Input,
  matchesKey,
  SelectList,
  type SelectItem,
  Spacer,
  Text,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";

export const THINKING_LEVEL_DESCRIPTIONS: Record<string, string> = {
  off: "No reasoning",
  minimal: "Very brief reasoning (~1k tokens)",
  low: "Light reasoning (~2k tokens)",
  medium: "Moderate reasoning (~8k tokens)",
  high: "Deep reasoning (~16k tokens)",
  xhigh: "Extra-high reasoning (~32k tokens)",
  max: "Maximum reasoning",
};

export class ThinkingSelectorComponent extends Container {
  public searchInput: Input;
  public selectList: SelectList;
  private selectListChildIndex: number;
  private allItems: SelectItem[];
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
    this.searchInput.focused = value;
  }

  constructor(
    public readonly currentLevel: string,
    public readonly availableLevels: string[],
    public readonly onSelect: (level: string) => void,
    public readonly onCancel: () => void,
    public readonly onSelectAsDefault?: (level: string) => void,
    public readonly defaultLevel?: string,
  ) {
    super();

    this.allItems = availableLevels.map((level) => {
      const isCurrent = level.toLowerCase() === currentLevel.toLowerCase();
      const isDefault =
        level.toLowerCase() === (defaultLevel || "").toLowerCase();
      const desc = THINKING_LEVEL_DESCRIPTIONS[level] || "Reasoning level";
      return {
        value: level,
        label: `${isCurrent ? "✓ " : "  "}${level}`,
        description: isDefault ? `${desc} · default` : desc,
      };
    });

    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));
    this.addChild(new Text(theme.bold("Thinking Level"), 0, 0));
    this.addChild(new Spacer(1));
    this.addChild(
      new Text(
        theme.fg("muted", "Shift+Tab cycles thinking levels in-session"),
        0,
        0,
      ),
    );
    this.addChild(new Spacer(1));

    this.searchInput = new Input();
    this.searchInput.onSubmit = () => {
      const item = this.selectList.getSelectedItem();
      if (item) {
        this.onSelect(item.value);
      }
    };
    this.addChild(this.searchInput);
    this.addChild(new Spacer(1));

    this.selectList = this.buildSelectList(this.allItems, currentLevel);
    this.selectListChildIndex = this.children.length;
    this.addChild(this.selectList);
    this.addChild(new Spacer(1));

    this.addChild(
      new Text(
        theme.fg(
          "dim",
          "  Enter to select · Ctrl+S to set as default · Escape to cancel",
        ),
        0,
        0,
      ),
    );
    this.addChild(new DynamicBorder());
  }

  private buildSelectList(
    items: SelectItem[],
    preselect: string,
  ): SelectList {
    const listTheme = {
      selectedPrefix: (s: string) => theme.fg("accent", s),
      selectedText: (s: string) => theme.bold(theme.fg("accent", s)),
      description: (s: string) => theme.fg("muted", s),
      scrollInfo: (s: string) => theme.dim(s),
      noMatch: (_s: string) => theme.dim("无匹配等级"),
    };
    const list = new SelectList(
      items,
      Math.max(1, items.length),
      listTheme,
      {
        minPrimaryColumnWidth: 12,
        maxPrimaryColumnWidth: 32,
      },
    );
    const curIdx = items.findIndex((i) => i.value === preselect);
    if (curIdx !== -1) {
      list.setSelectedIndex(curIdx);
    }
    list.onSelect = (item) => this.onSelect(item.value);
    list.onCancel = () => this.onCancel();
    return list;
  }

  private applyFilter(query: string): void {
    const filtered = query
      ? fuzzyFilter(
          this.allItems,
          query,
          (item) => `${item.value} ${item.description ?? ""}`,
        )
      : this.allItems;
    const selectedValue = this.selectList.getSelectedItem()?.value;
    const newList = this.buildSelectList(filtered, selectedValue || "");
    this.children[this.selectListChildIndex] = newList;
    this.selectList = newList;
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "ctrl+s") && this.onSelectAsDefault) {
      const item = this.selectList.getSelectedItem();
      if (item) this.onSelectAsDefault(item.value);
      return;
    }

    if (
      matchesKey(data, "up") ||
      matchesKey(data, "down") ||
      matchesKey(data, "return") ||
      matchesKey(data, "escape")
    ) {
      this.selectList.handleInput(data);
      return;
    }

    this.searchInput.handleInput(data);
    this.applyFilter(this.searchInput.getValue());
  }
}
