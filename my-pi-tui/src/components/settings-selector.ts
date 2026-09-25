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

export interface SettingItemDef {
  key: string;
  label: string;
  type: "boolean" | "cycle" | "string";
  options?: string[];
  description: string;
}

const SETTING_DEFINITIONS: SettingItemDef[] = [
  {
    key: "auto_compact",
    label: "Auto Compaction",
    type: "boolean",
    description: "Automatically compact context when usage exceeds threshold",
  },
  {
    key: "default_model",
    label: "Default Model",
    type: "string",
    description: "Default LLM model identifier (switch with /model)",
  },
  {
    key: "default_thinking_level",
    label: "Thinking Level",
    type: "cycle",
    options: ["off", "minimal", "low", "medium", "high", "xhigh", "max"],
    description: "Default reasoning thinking depth budget",
  },
  {
    key: "default_permission_mode",
    label: "Permission Mode",
    type: "cycle",
    options: ["review", "yolo", "strict"],
    description: "Security permission mode for workspace mutations",
  },
  {
    key: "theme",
    label: "Theme",
    type: "cycle",
    options: ["dark", "light"],
    description: "Active terminal color theme palette",
  },
];

export class SettingsSelectorComponent extends Container {
  private listContainer: Container;
  private selectedIndex = 0;
  private currentSettings: Record<string, unknown>;
  private lastWidth = 80;
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
  }

  constructor(
    initialSettings: Record<string, unknown>,
    public readonly onChange: (key: string, value: unknown) => void,
    public readonly onClose: () => void,
    public readonly definitions: SettingItemDef[] = SETTING_DEFINITIONS,
  ) {
    super();

    this.currentSettings = { ...initialSettings };
    this.listContainer = new Container();

    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));
    this.addChild(new Text(theme.bold("Settings"), 0, 0));
    this.addChild(
      new Text(
        theme.fg(
          "muted",
          "Enter: toggle / cycle value · Up/Down: navigate · Esc: close",
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
          "  Changes are saved to ~/.my-pi-agent/settings.json · Esc to close",
        ),
        0,
        0,
      ),
    );
    this.addChild(new DynamicBorder());

    this.updateList();
  }

  public override render(width: number): string[] {
    this.lastWidth = width;
    return super.render(width);
  }

  public updateList(): void {
    this.listContainer.clear();

    for (let i = 0; i < this.definitions.length; i++) {
      const def = this.definitions[i];
      const isSelected = i === this.selectedIndex;
      const val = this.currentSettings[def.key];

      let valueDisplay = "";
      if (def.type === "boolean") {
        valueDisplay = val
          ? theme.fg("success", "[x]")
          : theme.fg("muted", "[ ]");
      } else {
        valueDisplay = theme.fg("accent", String(val ?? "not set"));
      }

      const cursor = isSelected ? theme.fg("accent", "› ") : "  ";
      const label = isSelected ? theme.bold(def.label) : def.label;
      const left = `${cursor}${label}`;
      const right = `${valueDisplay}  ${theme.fg("dim", `(${def.description})`)}`;

      const pad = Math.max(
        2,
        this.lastWidth - 4 - visibleWidth(left) - visibleWidth(right),
      );
      let lineText = left + " ".repeat(pad) + right;

      if (isSelected) {
        lineText = theme.bg("selectedBg", lineText);
      }

      this.listContainer.addChild(new Text(lineText, 0, 0));
    }
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "up")) {
      this.selectedIndex =
        this.selectedIndex === 0
          ? this.definitions.length - 1
          : this.selectedIndex - 1;
      this.updateList();
    } else if (matchesKey(data, "down")) {
      this.selectedIndex =
        this.selectedIndex === this.definitions.length - 1
          ? 0
          : this.selectedIndex + 1;
      this.updateList();
    } else if (isEnterKey(data) || matchesKey(data, "space")) {
      const def = this.definitions[this.selectedIndex];
      if (!def) return;

      let nextVal: unknown;
      if (def.type === "boolean") {
        nextVal = !this.currentSettings[def.key];
      } else if (
        def.type === "cycle" &&
        def.options &&
        def.options.length > 0
      ) {
        const cur = String(this.currentSettings[def.key] ?? def.options[0]);
        const curIdx = def.options.indexOf(cur);
        const nextIdx = (curIdx + 1) % def.options.length;
        nextVal = def.options[nextIdx];
      } else {
        return;
      }

      this.currentSettings[def.key] = nextVal;
      this.onChange(def.key, nextVal);
      this.updateList();
    } else if (matchesKey(data, "escape") || matchesKey(data, "ctrl+c")) {
      this.onClose();
    }
  }
}
