import {
  EventTranslator,
  type StandardSessionEvent,
} from "./event-translator.js";

export interface PromptOptions {
  streamingBehavior?: "steer" | "followUp";
  [key: string]: unknown;
}

export interface RpcResponseData {
  [key: string]: unknown;
}

export interface ClientLike {
  request?(method: string, params?: Record<string, unknown>): Promise<unknown>;
  sendRequest?(
    method: string,
    params?: Record<string, unknown>,
  ): Promise<unknown>;
  on?(event: string, listener: (...args: any[]) => void): void;
  off?(event: string, listener: (...args: any[]) => void): void;
  removeListener?(event: string, listener: (...args: any[]) => void): void;
}

export interface TranslatorLike {
  translate(event: unknown): StandardSessionEvent | null;
}

/**
 * KernelBridge acts as a lightweight Session Adapter between the presentation
 * layer and the PythonKernelClient.
 */
// Export bridge
export class KernelBridge {
  public readonly client: ClientLike;
  public readonly translator: TranslatorLike;

  constructor(client: ClientLike, translator?: TranslatorLike) {
    this.client = client;
    this.translator = translator ?? new EventTranslator();
  }

  private async call<T = RpcResponseData>(
    method: string,
    params: Record<string, unknown> = {},
  ): Promise<T> {
    if (typeof this.client.request === "function") {
      return (await this.client.request(method, params)) as T;
    }
    if (typeof this.client.sendRequest === "function") {
      return (await this.client.sendRequest(method, params)) as T;
    }
    throw new Error(
      "KernelBridge: Provided client must implement request() or sendRequest().",
    );
  }

  public async prompt(
    text: string,
    options?: PromptOptions,
  ): Promise<RpcResponseData> {
    if (typeof (this.client as any).prompt === "function") {
      return (this.client as any).prompt(text, options);
    }
    const params: Record<string, unknown> = {
      text,
      ...(options || {}),
    };
    return this.call<RpcResponseData>("prompt", params);
  }

  public async abort(): Promise<RpcResponseData> {
    if (typeof (this.client as any).abort === "function") {
      return (this.client as any).abort();
    }
    return this.call<RpcResponseData>("abort", {});
  }

  public async steer(text: string): Promise<RpcResponseData> {
    if (typeof (this.client as any).steer === "function") {
      return (this.client as any).steer(text);
    }
    return this.call<RpcResponseData>("steer", { message: text });
  }

  public async followUp(text: string): Promise<RpcResponseData> {
    if (typeof (this.client as any).followup === "function") {
      return (this.client as any).followup(text);
    }
    if (typeof (this.client as any).followUp === "function") {
      return (this.client as any).followUp(text);
    }
    return this.call<RpcResponseData>("followup", { message: text });
  }

  public async clearQueue(): Promise<RpcResponseData> {
    if (typeof (this.client as any).clearQueue === "function") {
      return (this.client as any).clearQueue();
    }
    return this.call<RpcResponseData>("clear_queue", {});
  }

  public async listModels(
    options: Record<string, unknown> = {},
  ): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("models_list", options);
  }

  public async switchModel(
    model: string,
    provider?: string,
  ): Promise<RpcResponseData> {
    const params: Record<string, unknown> = { model };
    if (provider !== undefined) {
      params.provider = provider;
    }
    return this.call<RpcResponseData>("model_switch", params);
  }

  public async listSessions(
    options: Record<string, unknown> = {},
  ): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("session_list", options);
  }

  public async resumeSession(sessionId: string): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("session_resume", {
      session_id: sessionId,
    });
  }

  public async deleteSession(sessionId: string): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("session_delete", {
      session_id: sessionId,
    });
  }

  public async getSessionHistory(): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("session_history", {});
  }

  public async newSession(
    options?: Record<string, unknown>,
  ): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("session_new", options || {});
  }

  public async getTree(): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("session_tree", {});
  }

  public async getSessionStats(): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("session_stats", {});
  }

  public async branchSession(nodeId: string): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("session_branch", {
      target_id: nodeId,
      node_id: nodeId,
    });
  }

  public async setThinking(level: string): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("thinking_set", { level });
  }

  public async login(provider: string, key: string): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("login", { provider, key });
  }

  public async logout(provider: string): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("auth_logout", { provider });
  }

  public async getSettings(): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("settings_get", {});
  }

  public async setSetting(
    key: string,
    value: unknown,
  ): Promise<RpcResponseData> {
    return this.call<RpcResponseData>("settings_set", { key, value });
  }

  public subscribe(
    listener: (event: StandardSessionEvent) => void,
  ): () => void {
    const handler = (rawEvent: unknown) => {
      const translated = this.translator.translate(rawEvent);
      if (translated !== null && translated !== undefined) {
        listener(translated);
      }
    };

    if (typeof this.client.on === "function") {
      this.client.on("event", handler);
      this.client.on("notification", handler);
    }

    return () => {
      if (typeof this.client.off === "function") {
        this.client.off("event", handler);
        this.client.off("notification", handler);
      } else if (typeof this.client.removeListener === "function") {
        this.client.removeListener("event", handler);
        this.client.removeListener("notification", handler);
      }
    };
  }
}
