export interface PiSessionCreateResponse {
  session_id: string;
  workspace: string;
  provider: string;
  model: string;
}

export interface PiRpcResponseEvent {
  type: "response";
  id?: string;
  command?: string;
  success: boolean;
  data?: unknown;
  error?: string;
  message?: unknown;
  messageText?: string;
  text?: string;
}

export interface PiAssistantMessageEvent {
  type: "text_delta" | "thinking_delta" | string;
  delta?: string;
}

export interface PiRpcEvent {
  type: string;
  message?: unknown;
  messages?: unknown[];
  assistantMessageEvent?: PiAssistantMessageEvent;
  toolCallId?: string;
  toolName?: string;
  args?: unknown;
  partialResult?: unknown;
  result?: unknown;
  isError?: boolean;
  steering?: readonly string[];
  followUp?: readonly string[];
  text?: string;
  messageText?: string;
  error?: string;
  code?: number | null;
  signal?: string | null;
}

export type PiStreamEvent = PiRpcEvent | PiRpcResponseEvent;

export type PiTranscriptItemType =
  | "user"
  | "assistant"
  | "thinking"
  | "tool"
  | "system"
  | "error";

export interface PiTranscriptItem {
  id: string;
  type: PiTranscriptItemType;
  title?: string;
  content: string;
  running?: boolean;
  error?: boolean;
}
