import {
  Container,
  matchesKey,
  Spacer,
  Text,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";

export interface LogoutProviderItem {
  id: string;
  label: string;
  description?: string;
}

export class LogoutSelectorComponent extends Container {
  private listContainer: Container;
  private selectedIndex = 0;
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
  }

  constructor(
    public readonly providers: LogoutProviderItem[],
    public readonly onSelect: (providerId: string) => void,
    public readonly onCancel: () => void,
  ) {
    super();

    this.listContainer = new Container();

    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));
    this.addChild(
      new Text(theme.bold("Logout / Remove Stored Credentials"), 0, 0),
    );
    this.addChild(
      new Text(
        theme.fg(
          "muted",
          "Select a provider to remove its credentials from ~/.my-pi-agent/auth.json:",
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
        theme.fg("dim", "  Enter to remove credentials · Escape to cancel"),
        0,
        0,
      ),
    );
    this.addChild(new DynamicBorder());

    this.updateList();
  }

  public updateList(): void {
    this.listContainer.clear();

    if (this.providers.length === 0) {
      this.listContainer.addChild(
        new Text(
          theme.fg(
            "muted",
            "  未发现任何已保存的凭据 (No stored credentials)。",
          ),
          0,
          0,
        ),
      );
      return;
    }

    for (let i = 0; i < this.providers.length; i++) {
      const item = this.providers[i];
      if (!item) continue;
      const isSelected = i === this.selectedIndex;

      const cursor = isSelected ? theme.fg("accent", "› ") : "  ";
      const label = isSelected ? theme.bold(item.label) : item.label;
      const desc = item.description
        ? theme.fg("dim", ` (${item.description})`)
        : "";

      const left = `${cursor}${label}${desc}`;
      const pad = Math.max(2, 78 - visibleWidth(left));
      let lineText = left + " ".repeat(pad);

      if (isSelected) {
        lineText = theme.bg("selectedBg", lineText);
      }

      this.listContainer.addChild(new Text(lineText, 0, 0));
    }
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "up")) {
      if (this.providers.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === 0
          ? this.providers.length - 1
          : this.selectedIndex - 1;
      this.updateList();
    } else if (matchesKey(data, "down")) {
      if (this.providers.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === this.providers.length - 1
          ? 0
          : this.selectedIndex + 1;
      this.updateList();
    } else if (matchesKey(data, "return")) {
      const selected = this.providers[this.selectedIndex];
      if (selected) this.onSelect(selected.id);
    } else if (matchesKey(data, "escape")) {
      this.onCancel();
    }
  }
}
