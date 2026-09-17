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
import { isEnterKey } from "./keys.js";

export interface ModelItem {
  id: string;
  provider: string;
  name?: string;
  contextWindow?: number;
  is_configured?: boolean;
}

export type ModelListLoader = () => Promise<ModelItem[]>;

export class ModelSelectorComponent extends Container {
  public searchInput: Input;
  private headerContainer: Container;
  private listContainer: Container;
  private allModels: ModelItem[] = [];
  private scopedModelItems: ModelItem[] = [];
  private activeModels: ModelItem[] = [];
  private filteredModels: ModelItem[] = [];
  private selectedIndex = 0;
  private scope: "all" | "scoped" = "all";
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
    scopedModels: ModelItem[] = [],
  ) {
    super();

    this.headerContainer = new Container();
    this.listContainer = new Container();
    this.searchInput = new Input();
    this.scopedModelItems = [...scopedModels];
    this.scope = this.scopedModelItems.length > 0 ? "scoped" : "all";

    if (typeof modelsOrLoader === "function") {
      this.loader = modelsOrLoader;
    } else {
      this.allModels = this.sortModels(modelsOrLoader);
      this.activeModels =
        this.scope === "scoped" ? this.scopedModelItems : this.allModels;
      this.filteredModels = [...this.activeModels];
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

    const defaultHint = this.onSelectAsDefault
      ? " · Ctrl+S to set as default"
      : "";
    this.addChild(
      new Text(
        theme.fg("dim", `  Enter to select${defaultHint} · Escape to cancel`),
        0,
        0,
      ),
    );
    this.addChild(new DynamicBorder());
  }

  private getScopeText(): string {
    const allText =
      this.scope === "all"
        ? theme.fg("accent", "all")
        : theme.fg("muted", "all");
    const scopedText =
      this.scope === "scoped"
        ? theme.fg("accent", "scoped")
        : theme.fg("muted", "scoped");
    return `${theme.fg("muted", "Scope: ")}${allText}${theme.fg("muted", " | ")}${scopedText}`;
  }

  private getScopeHintText(): string {
    return theme.fg("dim", "tab scope (all/scoped)");
  }

  private updateHeader(): void {
    this.headerContainer.clear();
    if (this.scopedModelItems.length > 0) {
      this.headerContainer.addChild(new Text(this.getScopeText(), 0, 0));
      this.headerContainer.addChild(new Text(this.getScopeHintText(), 0, 0));
    } else {
      const hintText =
        "Only showing models from configured providers. Use /login to add providers.";
      this.headerContainer.addChild(
        new Text(theme.fg("warning", hintText), 0, 0),
      );
    }
  }

  public async reload(initialSearch?: string): Promise<void> {
    if (!this.loader) return;
    try {
      const models = await this.loader();
      this.allModels = this.sortModels(models);
      this.activeModels =
        this.scope === "scoped" && this.scopedModelItems.length > 0
          ? this.scopedModelItems
          : this.allModels;
      this.updateHeader();
      const q =
        initialSearch === undefined
          ? this.searchInput.getValue()
          : initialSearch;
      if (q) {
        this.filterModels(q);
      } else {
        this.filteredModels = [...this.activeModels];
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
      this.filteredModels = fuzzyFilter(this.activeModels, q, (item) => {
        const isDefault = item.id === this.defaultModelId ? " default" : "";
        const name = item.name ? ` ${item.name}` : "";
        return `${item.provider} ${item.provider}/${item.id} ${item.provider} ${item.id}${name}${isDefault}`;
      });
      this.selectedIndex = 0;
    } else {
      this.filteredModels = [...this.activeModels];
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
      const defaultBadge = isDefault ? theme.fg("muted", " · default") : "";

      const line = `${cursor}${currentMarker}${modelText} ${providerBadge}${defaultBadge}`;
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
      if (this.scopedModelItems.length > 0) {
        this.scope = this.scope === "all" ? "scoped" : "all";
        this.activeModels =
          this.scope === "scoped" ? this.scopedModelItems : this.allModels;
        this.updateHeader();
        this.filterModels(this.searchInput.getValue());
        if (this.requestRender) this.requestRender();
      }
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
    } else if (isEnterKey(data)) {
      const selected = this.filteredModels[this.selectedIndex];
      if (selected) this.onSelect(selected);
    } else if (matchesKey(data, "escape") || matchesKey(data, "ctrl+c")) {
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
