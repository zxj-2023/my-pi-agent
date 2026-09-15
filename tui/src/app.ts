import {
  type Container,
  type Editor,
  type TuiMainScreen,
} from "@earendil-works/pi-tui";
import { KernelBridge } from "./bridge/kernel-bridge.js";
import {
  PythonKernelClient,
  type PythonKernelClientOptions,
} from "./client.js";
import { type FooterComponent } from "./components/footer.js";
import { type ToolExecutionComponent } from "./components/tool-execution.js";
import {
  BUILTIN_SLASH_COMMANDS,
  InteractiveMode,
  type InteractiveModeOptions,
} from "./interactive/interactive-mode.js";

export { BUILTIN_SLASH_COMMANDS };

export interface AppOptions
  extends InteractiveModeOptions,
    PythonKernelClientOptions {
  workspace?: string;
  model?: string;
  mode?: string;
  continueSession?: boolean;
  resume?: string | boolean;
  sessionName?: string;
  thinking?: string;
  noSession?: boolean;
  newSession?: boolean;
  prompt?: string;
  pythonExecutable?: string;
}

export class AgentApp {
  public readonly client: PythonKernelClient;
  public readonly bridge: KernelBridge;
  public readonly interactiveMode: InteractiveMode;
  public get activeSelectorComponent(): any {
    return this.interactiveMode.activeSelectorComponent;
  }

  public get isBusy(): boolean {
    return this.interactiveMode.isStreaming;
  }

  public set isBusy(val: boolean) {
    this.interactiveMode.isStreaming = val;
  }

  constructor(public readonly options: AppOptions = {}) {
    this.client = new PythonKernelClient(options);
    this.bridge = new KernelBridge(this.client);
    this.interactiveMode = new InteractiveMode(this.bridge, options);
  }

  public get tui(): TuiMainScreen {
    return this.interactiveMode.ui;
  }

  public get chatContainer(): Container {
    return this.interactiveMode.chatContainer;
  }

  public get editor(): Editor {
    return this.interactiveMode.defaultEditor;
  }

  public get footer(): FooterComponent {
    return this.interactiveMode.footer;
  }

  public get activeTools(): Map<string, ToolExecutionComponent> {
    return this.interactiveMode.activeToolCalls;
  }

  public get toolStartTimes(): Map<string, number> {
    return this.interactiveMode.toolStartTimes;
  }

  public handleAgentEvent(event: any): void {
    this.interactiveMode.handleAgentEvent(event);
  }

  public async handleUserSubmit(input: string): Promise<void> {
    await this.interactiveMode.handleUserInput(input);
  }

  public renderSessionHistory(messages: any[], banner?: string): void {
    this.interactiveMode.renderSessionHistory(messages, banner);
  }

  public async start(): Promise<void> {
    const initResult: any = await this.client.start();
    await this.interactiveMode.init();
    this.interactiveMode.start();

    if (initResult?.session_name || initResult?.session_id) {
      this.footer.update({
        sessionName: initResult.session_name || initResult.session_id,
      });
    }

    if (initResult?.messages && initResult.messages.length > 0) {
      this.interactiveMode.renderSessionHistory(initResult.messages);
    }

    if (this.options.resume === true) {
      await this.interactiveMode.handleSlashCommand("/resume");
    } else if (typeof this.options.resume === "string" && this.options.resume) {
      await this.interactiveMode.handleSlashCommand(
        `/resume ${this.options.resume}`,
      );
    } else if (this.options.prompt) {
      await this.interactiveMode.handleUserInput(this.options.prompt);
    }
    this.tui.requestRender();
  }

  public async stop(): Promise<void> {
    this.interactiveMode.stop();
    await this.client.shutdown();
  }
}
