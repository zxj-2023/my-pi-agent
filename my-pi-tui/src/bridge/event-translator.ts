export interface ContentThinking {
  type: "thinking";
  thinking: string;
}

export interface ContentText {
  type: "text";
  text: string;
}

export interface ContentToolCall {
  type: "toolCall";
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export type ContentBlock = ContentThinking | ContentText | ContentToolCall;

export interface AssistantMessageState {
  role: "assistant";
  content: ContentBlock[];
  stopReason?: string;
  errorMessage?: string;
  metadata?: Record<string, unknown>;
}

export interface AgentStartSessionEvent {
  type: "agent_start";
  systemPrompt: string;
  userInput: string;
}

export interface TurnStartSessionEvent {
  type: "turn_start";
  iteration: number;
}

/** 逐轮统计：Footer 的上下文占用与 ↑↓R/CH%/$ 全靠它，翻译层必须原样透传。 */
interface UsageStatsPassThrough {
  usage?: Record<string, number | undefined>;
  contextWindow?: number;
}

export interface TurnEndSessionEvent extends UsageStatsPassThrough {
  type: "turn_end";
}

export interface MessageStartSessionEvent {
  type: "message_start";
  message: AssistantMessageState | Record<string, unknown>;
}

export interface MessageUpdateSessionEvent {
  type: "message_update";
  message: AssistantMessageState;
}

export interface MessageEndSessionEvent extends UsageStatsPassThrough {
  type: "message_end";
  message: AssistantMessageState;
}

export interface ToolExecutionStartSessionEvent {
  type: "tool_execution_start";
  toolCallId: string;
  toolName: string;
  args: Record<string, unknown>;
}

export interface ToolExecutionUpdateSessionEvent {
  type: "tool_execution_update";
  toolCallId: string;
  toolName: string;
  partialResult: unknown;
}

export interface ToolExecutionEndSessionEvent {
  type: "tool_execution_end";
  toolCallId: string;
  toolName: string;
  result: unknown;
  isError: boolean;
}

export interface AgentEndSessionEvent extends UsageStatsPassThrough {
  type: "agent_end";
  iterations: number;
  stopReason: string;
  stop_reason?: string;
  finalText?: string;
  final_text?: string;
}

export interface ContextCompactedSessionEvent {
  type: "context_compacted";
  tokensBefore?: number;
  tokensAfter?: number;
}

export interface AutoRetryStartSessionEvent {
  type: "auto_retry_start";
  attempt: number;
  maxAttempts: number;
  delayMs: number;
  errorMessage: string;
}

export interface AutoRetryEndSessionEvent {
  type: "auto_retry_end";
  success: boolean;
  attempt: number;
  finalError?: string;
}

export type StandardSessionEvent =
  | AgentStartSessionEvent
  | TurnStartSessionEvent
  | TurnEndSessionEvent
  | MessageStartSessionEvent
  | MessageUpdateSessionEvent
  | MessageEndSessionEvent
  | ToolExecutionStartSessionEvent
  | ToolExecutionUpdateSessionEvent
  | ToolExecutionEndSessionEvent
  | AgentEndSessionEvent
  | ContextCompactedSessionEvent
  | AutoRetryStartSessionEvent
  | AutoRetryEndSessionEvent
  | Record<string, unknown>;

/** 原样提取逐轮统计（usage / contextWindow）；缺失时为 undefined，便于调用方判断。 */
function extractUsageStats(event: Record<string, unknown>): UsageStatsPassThrough {
  const rawUsage = event.usage;
  const rawWindow = event.contextWindow ?? event.context_window;
  return {
    usage:
      typeof rawUsage === "object" && rawUsage !== null
        ? (rawUsage as Record<string, number | undefined>)
        : undefined,
    contextWindow: typeof rawWindow === "number" ? rawWindow : undefined,
  };
}

export class EventTranslator {
  private currentAssistantMessage: AssistantMessageState | null = null;

  /**
   * Translates incoming Python RPC notifications or raw event objects
   * into standardized Pi AgentSessionEvents while tracking in-flight message state.
   */
  public translate(raw: unknown): StandardSessionEvent | null {
    if (!raw || typeof raw !== "object") {
      return null;
    }

    const payload = raw as Record<string, unknown>;
    let event: Record<string, unknown> = payload;

    if (
      payload.method === "event" &&
      payload.params &&
      typeof payload.params === "object"
    ) {
      event = payload.params as Record<string, unknown>;
    } else if (
      payload.params &&
      typeof payload.params === "object" &&
      "type" in payload.params
    ) {
      event = payload.params as Record<string, unknown>;
    }

    if (!event.type || typeof event.type !== "string") {
      return null;
    }

    switch (event.type) {
      case "agent_start": {
        this.currentAssistantMessage = null;
        return {
          type: "agent_start",
          systemPrompt: String(event.system_prompt ?? event.systemPrompt ?? ""),
          userInput: String(event.user_input ?? event.userInput ?? ""),
        };
      }

      case "turn_start": {
        return {
          type: "turn_start",
          iteration: Number(event.iteration ?? 1),
        };
      }

      case "turn_end": {
        return {
          type: "turn_end",
          ...extractUsageStats(event),
        };
      }

      case "message_start": {
        const rawMsg = event.message as Record<string, unknown> | undefined;
        const role = String(rawMsg?.role ?? "assistant");
        if (role === "assistant") {
          this.currentAssistantMessage = {
            role: "assistant",
            content: [],
          };
          return {
            type: "message_start",
            message: this.cloneMessage(this.currentAssistantMessage),
          };
        }
        return {
          type: "message_start",
          message: rawMsg ?? { role, content: [] },
        };
      }

      case "message_update": {
        if (!this.currentAssistantMessage) {
          this.currentAssistantMessage = {
            role: "assistant",
            content: [],
          };
        }

        const reasoningDelta = event.reasoning_delta ?? event.reasoningDelta;
        if (typeof reasoningDelta === "string" && reasoningDelta !== "") {
          let thinkingBlock = this.currentAssistantMessage.content.find(
            (b): b is ContentThinking => b.type === "thinking",
          );
          if (!thinkingBlock) {
            thinkingBlock = { type: "thinking", thinking: "" };
            this.currentAssistantMessage.content.push(thinkingBlock);
          }
          thinkingBlock.thinking += reasoningDelta;
        }

        const delta = event.delta;
        if (typeof delta === "string" && delta !== "") {
          let textBlock = this.currentAssistantMessage.content.find(
            (b): b is ContentText => b.type === "text",
          );
          if (!textBlock) {
            textBlock = { type: "text", text: "" };
            this.currentAssistantMessage.content.push(textBlock);
          }
          textBlock.text += delta;
        }

        return {
          type: "message_update",
          message: this.cloneMessage(this.currentAssistantMessage),
        };
      }

      case "message_end": {
        const rawMsg = event.message as Record<string, unknown> | undefined;
        const rawMeta = (rawMsg?.metadata ?? event.metadata) as
          | Record<string, unknown>
          | undefined;
        const stopReason = String(
          event.stop_reason ??
            event.stopReason ??
            rawMeta?.stop_reason ??
            rawMsg?.stopReason ??
            "stop",
        );
        if (this.currentAssistantMessage) {
          this.currentAssistantMessage.stopReason = stopReason;
          if (rawMeta) {
            this.currentAssistantMessage.metadata = { ...rawMeta };
          }

          // 如果在流式期间未积累任何文本块（如 HTTP 握手阶段直接抛出 401/403/500），
          // 但 message_end 的 rawMsg 携带有 content 错误字符串，则补齐一个 text 块！
          const hasText = this.currentAssistantMessage.content.some(
            (b) => b.type === "text" && Boolean(b.text),
          );
          if (!hasText && rawMsg?.content) {
            const fallbackText =
              typeof rawMsg.content === "string"
                ? rawMsg.content
                : Array.isArray(rawMsg.content)
                  ? rawMsg.content
                      .map((b: any) =>
                        typeof b === "string"
                          ? b
                          : b?.text || b?.thinking || "",
                      )
                      .join("")
                  : String(rawMsg.content);
            if (fallbackText) {
              this.currentAssistantMessage.content.push({
                type: "text",
                text: fallbackText,
              });
            }
          }

          const completedMessage = this.cloneMessage(
            this.currentAssistantMessage,
          );
          this.currentAssistantMessage = null;
          return {
            type: "message_end",
            message: completedMessage,
            ...extractUsageStats(event),
          };
        }
        const rawAssistant = rawMsg as AssistantMessageState | undefined;
        const fallbackMsg: AssistantMessageState = rawAssistant
          ? {
              role: "assistant",
              content: Array.isArray(rawAssistant.content)
                ? rawAssistant.content
                : [],
              stopReason,
              metadata: rawMeta ? { ...rawMeta } : undefined,
            }
          : { role: "assistant", content: [], stopReason, metadata: rawMeta };
        return {
          type: "message_end",
          message: fallbackMsg,
          ...extractUsageStats(event),
        };
      }

      case "tool_execution_start": {
        const toolCallId = String(event.toolCallId ?? event.tool_call_id ?? "");
        const toolName = String(event.toolName ?? event.tool_name ?? "");
        const args = (
          event.args && typeof event.args === "object" ? event.args : {}
        ) as Record<string, unknown>;

        if (this.currentAssistantMessage) {
          this.currentAssistantMessage.content.push({
            type: "toolCall",
            id: toolCallId,
            name: toolName,
            arguments: args,
          });
        }

        return {
          type: "tool_execution_start",
          toolCallId,
          toolName,
          args,
        };
      }

      case "tool_execution_update": {
        return {
          type: "tool_execution_update",
          toolCallId: String(event.toolCallId ?? event.tool_call_id ?? ""),
          toolName: String(event.toolName ?? event.tool_name ?? ""),
          partialResult: event.partialResult ?? event.partial_result,
        };
      }

      case "tool_execution_end": {
        return {
          type: "tool_execution_end",
          toolCallId: String(event.toolCallId ?? event.tool_call_id ?? ""),
          toolName: String(event.toolName ?? event.tool_name ?? ""),
          result: event.result,
          isError: Boolean(event.isError ?? event.is_error ?? false),
        };
      }

      case "agent_end": {
        this.currentAssistantMessage = null;
        const stopReason = String(
          event.stop_reason ?? event.stopReason ?? "completed",
        );
        const finalText = String(event.final_text ?? event.finalText ?? "");
        return {
          type: "agent_end",
          iterations: Number(event.iterations ?? 1),
          stopReason,
          stop_reason: stopReason,
          finalText,
          final_text: finalText,
          ...extractUsageStats(event),
        };
      }

      case "context_compacted": {
        const tokensBefore =
          typeof event.tokensBefore === "number"
            ? event.tokensBefore
            : typeof event.tokens_before === "number"
              ? event.tokens_before
              : undefined;
        const tokensAfter =
          typeof event.tokensAfter === "number"
            ? event.tokensAfter
            : typeof event.tokens_after === "number"
              ? event.tokens_after
              : undefined;
        return {
          type: "context_compacted",
          tokensBefore,
          tokensAfter,
        };
      }

      case "auto_retry_start": {
        return {
          type: "auto_retry_start",
          attempt: Number(event.attempt ?? 1),
          maxAttempts: Number(event.maxAttempts ?? event.max_attempts ?? 3),
          delayMs: Number(event.delayMs ?? event.delay_ms ?? 2000),
          errorMessage: String(event.errorMessage ?? event.error_message ?? ""),
        };
      }

      case "auto_retry_end": {
        return {
          type: "auto_retry_end",
          success: Boolean(event.success ?? false),
          attempt: Number(event.attempt ?? 1),
          finalError:
            event.finalError || event.final_error
              ? String(event.finalError || event.final_error)
              : undefined,
        };
      }

      default: {
        return { ...event };
      }
    }
  }

  /**
   * Returns a copy of the current in-flight assistant message state, or null if idle.
   */
  public getCurrentAssistantMessage(): AssistantMessageState | null {
    return this.currentAssistantMessage
      ? this.cloneMessage(this.currentAssistantMessage)
      : null;
  }

  /**
   * Resets internal tracking state.
   */
  public reset(): void {
    this.currentAssistantMessage = null;
  }

  private cloneMessage(msg: AssistantMessageState): AssistantMessageState {
    return {
      role: msg.role,
      content: msg.content.map((block) => {
        if (block.type === "thinking") {
          return { type: "thinking", thinking: block.thinking };
        }
        if (block.type === "text") {
          return { type: "text", text: block.text };
        }
        if (block.type === "toolCall") {
          return {
            type: "toolCall",
            id: block.id,
            name: block.name,
            arguments: { ...block.arguments },
          };
        }
        const exhaustiveCheck: never = block;
        return exhaustiveCheck;
      }),
      stopReason: msg.stopReason,
      errorMessage: msg.errorMessage,
      metadata: msg.metadata ? { ...msg.metadata } : undefined,
    };
  }
}
