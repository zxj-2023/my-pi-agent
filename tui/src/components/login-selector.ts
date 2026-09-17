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
import { isEnterKey } from "./keys.js";

export interface ProviderOption {
  id: string;
  label: string;
  description: string;
}

export const SUPPORTED_LOGIN_PROVIDERS: ProviderOption[] = [
  {
    id: "deepseek",
    label: "DeepSeek",
    description: "API Key (deepseek-chat, deepseek-reasoner)",
  },
  {
    id: "openai",
    label: "OpenAI",
    description: "API Key (gpt-4o, gpt-4o-mini, o1, o3)",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    description: "API Key (claude-3-5-sonnet, claude-3-5-haiku)",
  },
  {
    id: "antigravity",
    label: "Antigravity",
    description: "读取 auth.json 认证凭据 (Google Cloud Code Assist)",
  },
];

export class LoginSelectorComponent extends Container {
  public searchInput: Input;
  public keyInput: Input;
  public selectList: SelectList;
  private phase: "select_provider" | "enter_key" = "select_provider";
  private selectedProvider: ProviderOption = SUPPORTED_LOGIN_PROVIDERS[0];
  private allItems: SelectItem[];
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
    if (this.phase === "select_provider") {
      this.searchInput.focused = value;
    } else {
      this.keyInput.focused = value;
    }
  }

  constructor(
    public readonly onSubmit: (provider: string, key: string) => void,
    public readonly onCancel: () => void,
    public readonly providers: ProviderOption[] = SUPPORTED_LOGIN_PROVIDERS,
  ) {
    super();

    this.allItems = providers.map((p) => ({
      value: p.id,
      label: p.label,
      description: p.description,
    }));

    this.searchInput = new Input();
    this.keyInput = new Input();
    this.selectList = this.buildSelectList(this.allItems);

    this.rebuildUI();
  }

  private buildSelectList(items: SelectItem[]): SelectList {
    const listTheme = {
      selectedPrefix: (s: string) => theme.fg("accent", s),
      selectedText: (s: string) => theme.bold(theme.fg("accent", s)),
      description: (s: string) => theme.fg("muted", s),
      scrollInfo: (s: string) => theme.dim(s),
      noMatch: (_s: string) => theme.dim("无匹配 Provider"),
    };
    const list = new SelectList(items, Math.max(1, items.length), listTheme, {
      minPrimaryColumnWidth: 14,
      maxPrimaryColumnWidth: 28,
    });
    list.onSelect = (item) => {
      const found = this.providers.find((p) => p.id === item.value);
      if (found) {
        this.selectedProvider = found;
        this.phase = "enter_key";
        this.rebuildUI();
      }
    };
    list.onCancel = () => this.onCancel();
    return list;
  }

  private applyFilter(query: string): void {
    const filtered = query
      ? fuzzyFilter(
          this.allItems,
          query,
          (item) => `${item.value} ${item.label} ${item.description ?? ""}`,
        )
      : this.allItems;
    this.selectList = this.buildSelectList(filtered);
    this.rebuildUI();
  }

  private rebuildUI(): void {
    this.clear();
    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));

    if (this.phase === "select_provider") {
      this.searchInput.focused = this._focused;
      this.keyInput.focused = false;
      this.addChild(
        new Text(theme.bold("Login / Bind Provider Credentials"), 0, 0),
      );
      this.addChild(new Spacer(1));
      this.addChild(
        new Text(
          theme.fg(
            "muted",
            "Credentials will be securely saved to ~/.my-pi-agent/auth.json",
          ),
          0,
          0,
        ),
      );
      this.addChild(new Spacer(1));

      this.addChild(this.searchInput);
      this.addChild(new Spacer(1));

      this.addChild(this.selectList);
      this.addChild(new Spacer(1));

      this.addChild(
        new Text(theme.fg("dim", "  Enter to select · Escape to cancel"), 0, 0),
      );
    } else {
      this.keyInput.focused = this._focused;
      this.searchInput.focused = false;

      if (this.selectedProvider.id === "antigravity") {
        this.addChild(
          new Text(theme.bold("Antigravity 认证凭据配置 (auth.json)"), 0, 0),
        );
        this.addChild(new Spacer(1));
        this.addChild(
          new Text(
            theme.fg(
              "muted",
              "Antigravity 依赖 Google OAuth 凭据，系统将自动扫描并读取下列路径：",
            ),
            0,
            0,
          ),
        );
        this.addChild(
          new Text(
            theme.fg(
              "accent",
              "  1. ~/.my-pi-agent/auth.json (推荐：当前 Agent 专属凭据路径)\n  2. ~/.pi/agent/auth.json    (Pi 官方扩展认证凭据路径)",
            ),
            0,
            0,
          ),
        );
        this.addChild(new Spacer(1));
        this.addChild(
          new Text(
            theme.fg(
              "dim",
              "• 若上述路径已放置包含 antigravity 字段的 auth.json，直接按 Enter 即可自动读取绑定。\n• 若需手动输入，请在下方粘贴 Access Token，或按 Escape 返回：",
            ),
            0,
            0,
          ),
        );
        this.addChild(new Spacer(1));
        this.addChild(this.keyInput);
        this.addChild(new Spacer(1));
        this.addChild(
          new Text(
            theme.fg(
              "dim",
              "  Enter 直接读取 auth.json / 提交 Token · Escape 返回",
            ),
            0,
            0,
          ),
        );
      } else {
        this.addChild(
          new Text(
            theme.bold(`Enter API Key for ${this.selectedProvider.label}`),
            0,
            0,
          ),
        );
        this.addChild(new Spacer(1));
        this.addChild(
          new Text(
            theme.fg(
              "muted",
              `Paste your key below and press Enter (saved to ~/.my-pi-agent/auth.json):`,
            ),
            0,
            0,
          ),
        );
        this.addChild(new Spacer(1));

        this.addChild(this.keyInput);
        this.addChild(new Spacer(1));

        this.addChild(
          new Text(
            theme.fg("dim", "  Enter to confirm & save · Escape to back"),
            0,
            0,
          ),
        );
      }
    }

    this.addChild(new DynamicBorder());
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "ctrl+c")) {
      this.onCancel();
      return;
    }

    if (this.phase === "select_provider") {
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
        return;
      }
      this.searchInput.handleInput(data);
      this.applyFilter(this.searchInput.getValue());
    } else {
      if (matchesKey(data, "escape")) {
        this.phase = "select_provider";
        this.rebuildUI();
        return;
      }
      if (isEnterKey(data)) {
        const key = this.keyInput.getValue().trim();
        if (this.selectedProvider.id === "antigravity") {
          // Antigravity 支持直接按 Enter 自动读取 auth.json，或提交手动粘贴的 token
          this.onSubmit("antigravity", key);
          return;
        }
        if (key) {
          this.onSubmit(this.selectedProvider.id, key);
        }
        return;
      }
      this.keyInput.handleInput(data);
    }
  }
}
