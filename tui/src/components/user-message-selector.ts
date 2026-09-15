import {
  Container,
  matchesKey,
  Spacer,
  Text,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";

export interface UserMessageItem {
  id: string;
  text: string;
}

export class UserMessageSelectorComponent extends Container {
  private listContainer: Container;
  private selectedIndex = 0;
  private maxVisible = 10;
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
  }

  constructor(
    public readonly messages: UserMessageItem[],
    public readonly onSelect: (msg: UserMessageItem) => void,
    public readonly onCancel: () => void,
  ) {
    super();

    this.listContainer = new Container();

    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));
    this.addChild(new Text(theme.bold("Fork Session from Previous Message"), 0, 0));
    this.addChild(
      new Text(
        theme.fg(
          "muted",
          "Enter: select message to branch from · Up/Down: navigate · Esc: cancel",
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
          "  Enter to branch into a new session · Escape to cancel",
        ),
        0,
        0,
      ),
    );
    this.addChild(new DynamicBorder());

    this.updateList();
  }

  public updateList(): void {
    this.listContainer.clear();

    if (this.messages.length === 0) {
      this.listContainer.addChild(
        new Text(theme.fg("muted", "  当前会话暂无历史用户提问。"), 0, 0),
      );
      return;
    }

    const startIndex = Math.max(
      0,
      Math.min(
        this.selectedIndex - Math.floor(this.maxVisible / 2),
        this.messages.length - this.maxVisible,
      ),
    );
    const endIndex = Math.min(
      startIndex + this.maxVisible,
      this.messages.length,
    );

    for (let i = startIndex; i < endIndex; i++) {
      const msg = this.messages[i];
      if (!msg) continue;
      const isSelected = i === this.selectedIndex;

      const cursor = isSelected ? theme.fg("accent", "› ") : "  ";
      const indexTag = theme.fg("muted", `[Message ${i + 1} of ${this.messages.length}]`);
      const snippet = msg.text.replace(/[\n\r\t]/g, " ").trim();

      const left = `${cursor}${indexTag} ${isSelected ? theme.bold(snippet) : snippet}`;
      const pad = Math.max(2, 78 - visibleWidth(left));
      let lineText = left + " ".repeat(pad);

      if (isSelected) {
        lineText = theme.bg("selectedBg", lineText);
      }

      this.listContainer.addChild(new Text(lineText, 0, 0));
    }

    if (startIndex > 0 || endIndex < this.messages.length) {
      const scrollInfo = theme.fg(
        "muted",
        `  (${this.selectedIndex + 1}/${this.messages.length})`,
      );
      this.listContainer.addChild(new Text(scrollInfo, 0, 0));
    }
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "up")) {
      if (this.messages.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === 0
          ? this.messages.length - 1
          : this.selectedIndex - 1;
      this.updateList();
    } else if (matchesKey(data, "down")) {
      if (this.messages.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === this.messages.length - 1
          ? 0
          : this.selectedIndex + 1;
      this.updateList();
    } else if (matchesKey(data, "return")) {
      const selected = this.messages[this.selectedIndex];
      if (selected) this.onSelect(selected);
    } else if (matchesKey(data, "escape")) {
      this.onCancel();
    }
  }
}
