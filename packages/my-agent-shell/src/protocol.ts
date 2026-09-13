export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number | string;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number | string;
  result?: unknown;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
}

export interface JsonRpcNotification {
  jsonrpc: "2.0";
  method: string;
  params: Record<string, unknown>;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string;
}

export interface AgentStartEvent {
  type: "agent_start";
  system_prompt?: string;
  user_input?: string;
}

export interface AgentEndEvent {
  type: "agent_end";
  iterations: number;
  stop_reason: string;
  final_text?: string;
}

export interface TurnStartEvent {
  type: "turn_start";
  iteration: number;
}

export interface TurnEndEvent {
  type: "turn_end";
}

export interface MessageStartEvent {
  type: "message_start";
  message: ChatMessage;
}

export interface MessageUpdateEvent {
  type: "message_update";
  message: ChatMessage;
  delta?: string;
  reasoning_delta?: string;
}

export interface MessageEndEvent {
  type: "message_end";
  message: ChatMessage;
}

export interface ToolExecutionStartEvent {
  type: "tool_execution_start";
  toolCallId: string;
  toolName: string;
  args: Record<string, unknown>;
}

export interface ToolExecutionUpdateEvent {
  type: "tool_execution_update";
  toolCallId: string;
  toolName: string;
  partialResult: unknown;
}

export interface ToolExecutionEndEvent {
  type: "tool_execution_end";
  toolCallId: string;
  toolName: string;
  result: unknown;
  isError: boolean;
}

export type AgentEvent =
  | AgentStartEvent
  | AgentEndEvent
  | TurnStartEvent
  | TurnEndEvent
  | MessageStartEvent
  | MessageUpdateEvent
  | MessageEndEvent
  | ToolExecutionStartEvent
  | ToolExecutionUpdateEvent
  | ToolExecutionEndEvent;
