import {
  Container,
  fuzzyFilter,
  Input,
  matchesKey,
  Spacer,
  Text,
} from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";

export interface ModelItem {
  id: string;
  provider: string;
  name?: string;
  contextWindow?: number;
  is_configured?: boolean;
}

export type ModelListLoader = (all: boolean) => Promise<ModelItem[]>;

export class ModelSelectorComponent extends Container {
  public searchInput: Input;
  private headerContainer: Container;
  private listContainer: Container;
  private allModels: ModelItem[] = [];
  private filteredModels: ModelItem[] = [];
  private selectedIndex = 0;
  private scope: "configured" | "all" = "configured";
  private loader?: ModelListLoader;
  private _focused = false;

  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
    this.searchInput.focused = value;
  }

  constructor(
    public readonly currentModel: string,
    modelsOrLoader: ModelItem[] | ModelListLoader,
    public readonly onSelect: (model: ModelItem) => void,
    public readonly onCancel: () => void,
    initialSearch?: string,
    public readonly onSelectAsDefault?: (model: ModelItem) => void,
    public readonly defaultModelId?: string,
    private readonly requestRender?: () => void,
  ) {
    super();

    this.headerContainer = new Container();
    this.listContainer = new Container();
    this.searchInput = new Input();

    if (typeof modelsOrLoader === "function") {
      this.loader = modelsOrLoader;
    } else {
      this.allModels = this.sortModels(modelsOrLoader);
      this.filteredModels = [...this.allModels];
    }

    this.rebuildStaticLayout(initialSearch);

    if (this.loader) {
      void this.reload(initialSearch);
    } else {
      this.updateHeader();
      if (initialSearch) {
        this.filterModels(initialSearch);
      } else {
        const curIdx = this.filteredModels.findIndex(
          (m) =>
            m.id === currentModel || `${m.provider}/${m.id}` === currentModel,
        );
        this.selectedIndex = curIdx >= 0 ? curIdx : 0;
        this.updateList();
      }
    }
  }

  private rebuildStaticLayout(initialSearch?: string): void {
    this.addChild(new DynamicBorder());
    this.addChild(new Spacer(1));
    this.addChild(this.headerContainer);
    this.addChild(new Spacer(1));

    if (initialSearch) {
      this.searchInput.setValue(initialSearch);
    }
    this.searchInput.onSubmit = () => {
      const selected = this.filteredModels[this.selectedIndex];
      if (selected) this.onSelect(selected);
    };
    this.addChild(this.searchInput);
    this.addChild(new Spacer(1));

    this.addChild(this.listContainer);
    this.addChild(new Spacer(1));

    this.addChild(
      new Text(
        theme.fg(
          "dim",
          "  Enter to select · Ctrl+S to set as default · Tab to switch scope · Escape to cancel",
        ),
        0,
        0,
      ),
    );
    this.addChild(new DynamicBorder());
  }

  private updateHeader(): void {
    this.headerContainer.clear();
    const scopeLabel =
      this.scope === "configured"
        ? "◉ Configured | ○ All"
        : "○ Configured | ◉ All";
    this.headerContainer.addChild(
      new Text(
        `${theme.bold("Model Catalog")}                  ${theme.fg("accent", scopeLabel)}`,
        0,
        0,
      ),
    );
    const hint =
      this.scope === "configured"
        ? "Only showing models from configured providers. Use /login to bind credentials. (Tab to toggle all)"
        : "Showing all catalog models. Use /login to configure unconfigured providers. (Tab to toggle configured only)";
    this.headerContainer.addChild(new Text(theme.fg("muted", hint), 0, 0));
  }

  public async reload(initialSearch?: string): Promise<void> {
    if (!this.loader) return;
    try {
      const models = await this.loader(this.scope === "all");
      this.allModels = this.sortModels(models);
      this.updateHeader();
      const q =
        initialSearch === undefined
          ? this.searchInput.getValue()
          : initialSearch;
      if (q) {
        this.filterModels(q);
      } else {
        this.filteredModels = [...this.allModels];
        const curIdx = this.filteredModels.findIndex(
          (m) =>
            m.id === this.currentModel ||
            `${m.provider}/${m.id}` === this.currentModel,
        );
        this.selectedIndex = curIdx >= 0 ? curIdx : 0;
        this.updateList();
      }
    } catch {
      this.allModels = [];
      this.filteredModels = [];
      this.updateList();
    }
    if (this.requestRender) {
      this.requestRender();
    }
  }

  private sortModels(models: ModelItem[]): ModelItem[] {
    return [...models].sort((a, b) => {
      const aCur =
        a.id === this.currentModel ||
        `${a.provider}/${a.id}` === this.currentModel;
      const bCur =
        b.id === this.currentModel ||
        `${b.provider}/${b.id}` === this.currentModel;
      if (aCur && !bCur) return -1;
      if (!aCur && bCur) return 1;

      const aDef = a.id === this.defaultModelId;
      const bDef = b.id === this.defaultModelId;
      if (aDef && !bDef) return -1;
      if (!aDef && bDef) return 1;

      return a.provider.localeCompare(b.provider);
    });
  }

  public filterModels(query: string): void {
    const q = query.trim();
    if (q) {
      this.filteredModels = fuzzyFilter(this.allModels, q, (item) => {
        const isDefault = item.id === this.defaultModelId ? " default" : "";
        const name = item.name ? ` ${item.name}` : "";
        return `${item.provider} ${item.provider}/${item.id} ${item.provider} ${item.id}${name}${isDefault}`;
      });
      this.selectedIndex = 0;
    } else {
      this.filteredModels = [...this.allModels];
      this.selectedIndex = Math.min(
        this.selectedIndex,
        Math.max(0, this.filteredModels.length - 1),
      );
    }
    this.updateList();
  }

  public updateList(): void {
    this.listContainer.clear();
    const maxVisible = 10;
    const startIndex = Math.max(
      0,
      Math.min(
        this.selectedIndex - Math.floor(maxVisible / 2),
        this.filteredModels.length - maxVisible,
      ),
    );
    const endIndex = Math.min(
      startIndex + maxVisible,
      this.filteredModels.length,
    );

    for (let i = startIndex; i < endIndex; i++) {
      const item = this.filteredModels[i];
      if (!item) continue;
      const isSelected = i === this.selectedIndex;
      const isCurrent =
        item.id === this.currentModel ||
        `${item.provider}/${item.id}` === this.currentModel;
      const isDefault = item.id === this.defaultModelId;

      const cursor = isSelected ? theme.fg("accent", "→ ") : "  ";
      const currentMarker = isCurrent ? theme.fg("accent", "✓ ") : "  ";
      const modelText = isSelected ? theme.fg("accent", item.id) : item.id;
      const providerBadge = theme.fg("muted", `[${item.provider}]`);
      const ctxBadge = item.contextWindow
        ? theme.fg("muted", ` · ${Math.round(item.contextWindow / 1024)}k`)
        : "";
      const defaultBadge = isDefault ? theme.fg("muted", " · default") : "";
      const unconfBadge =
        item.is_configured === false
          ? theme.fg("dim", " (unconfigured)")
          : "";

      const line = `${cursor}${currentMarker}${modelText} ${providerBadge}${ctxBadge}${unconfBadge}${defaultBadge}`;
      this.listContainer.addChild(new Text(line, 0, 0));
    }

    if (startIndex > 0 || endIndex < this.filteredModels.length) {
      const scrollInfo = theme.fg(
        "muted",
        `  (${this.selectedIndex + 1}/${this.filteredModels.length})`,
      );
      this.listContainer.addChild(new Text(scrollInfo, 0, 0));
    }

    if (this.filteredModels.length === 0) {
      this.listContainer.addChild(
        new Text(theme.fg("muted", "  No matching models"), 0, 0),
      );
    } else {
      const selected = this.filteredModels[this.selectedIndex];
      if (selected?.name) {
        this.listContainer.addChild(new Spacer(1));
        this.listContainer.addChild(
          new Text(theme.fg("muted", `  Model Name: ${selected.name}`), 0, 0),
        );
      }
    }
  }

  public handleInput(data: string): void {
    if (matchesKey(data, "tab")) {
      this.scope = this.scope === "configured" ? "all" : "configured";
      void this.reload();
      return;
    }

    if (matchesKey(data, "up")) {
      if (this.filteredModels.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === 0
          ? this.filteredModels.length - 1
          : this.selectedIndex - 1;
      this.updateList();
    } else if (matchesKey(data, "down")) {
      if (this.filteredModels.length === 0) return;
      this.selectedIndex =
        this.selectedIndex === this.filteredModels.length - 1
          ? 0
          : this.selectedIndex + 1;
      this.updateList();
    } else if (matchesKey(data, "return")) {
      const selected = this.filteredModels[this.selectedIndex];
      if (selected) this.onSelect(selected);
    } else if (matchesKey(data, "escape")) {
      this.onCancel();
    } else if (matchesKey(data, "ctrl+s") && this.onSelectAsDefault) {
      const selected = this.filteredModels[this.selectedIndex];
      if (selected) this.onSelectAsDefault(selected);
    } else {
      this.searchInput.handleInput(data);
      this.filterModels(this.searchInput.getValue());
    }
  }
}
