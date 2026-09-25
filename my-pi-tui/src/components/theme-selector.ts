import {
  Container,
  matchesKey,
  SelectList,
  type SelectItem,
  Spacer,
  Text,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
import { isEnterKey } from "./keys.js";

const THEME_LAYOUT_OPTIONS = {
  minPrimaryColumnWidth: 12,
  maxPrimaryColumnWidth: 28,
};

export class ThemeSelectorComponent extends Container {
  public selectList: SelectList;
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
  }

  constructor(
    public readonly currentTheme: string,
    public readonly availableThemes: string[] = ["dark", "light"],
    public readonly onSelect: (themeName: string) => void,
    public readonly onCancel: () => void,
    public readonly onPreview?: (themeName: string) => void,
  ) {
    super();

    const items: SelectItem[] = availableThemes.map((name) => ({
      value: name,
      label: name,
      description: name === currentTheme ? "(current)" : undefined,
    }));

    const listTheme = {
      selectedPrefix: (s: string) => theme.fg("accent", s),
      selectedText: (s: string) => theme.bold(theme.fg("accent", s)),
      description: (s: string) => theme.fg("muted", s),
      scrollInfo: (s: string) => theme.dim(s),
      noMatch: (_s: string) => theme.dim("无匹配主题"),
    };

    this.selectList = new SelectList(
      items,
      Math.max(1, items.length),
      listTheme,
      THEME_LAYOUT_OPTIONS,
    );

    const curIdx = availableThemes.indexOf(currentTheme);
    if (curIdx !== -1) {
      this.selectList.setSelectedIndex(curIdx);
    }

    this.selectList.onSelect = (item) => onSelect(item.value);
    this.selectList.onCancel = () => onCancel();
    this.selectList.onSelectionChange = (item) => onPreview?.(item.value);

    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));
    this.addChild(new Text(theme.bold("Theme Selector"), 0, 0));
    this.addChild(
      new Text(
        theme.fg(
          "muted",
          "Enter: select · Up/Down: live preview · Esc: revert & exit",
        ),
        0,
        0,
      ),
    );
    this.addChild(new Spacer(1));

    this.addChild(this.selectList);
    this.addChild(new Spacer(1));

    this.addChild(
      new Text(
        theme.fg(
          "dim",
          "  Changes persist to settings.json · Escape to cancel",
        ),
        0,
        0,
      ),
    );
    this.addChild(new DynamicBorder());
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "ctrl+c")) {
      this.onCancel();
      return;
    }

    if (
      matchesKey(data, "up") ||
      matchesKey(data, "down") ||
      isEnterKey(data) ||
      matchesKey(data, "escape")
    ) {
      if (isEnterKey(data)) {
        this.selectList.handleInput("\r");
      } else {
        this.selectList.handleInput(data);
      }
    }
  }
}
