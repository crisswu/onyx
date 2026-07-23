"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import BaseInputBar from "@/sections/input/BaseInputBar";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { isPiAllowedUser } from "@/lib/pi/access";
import {
  abortPiSession,
  createPiSession,
  deletePiSession,
  streamPiMessage,
} from "@/lib/pi/client";
import type {
  PiSessionCreateResponse,
  PiStreamEvent,
  PiTranscriptItem,
} from "@/lib/pi/types";
import {
  SvgAlertCircle,
  SvgEditBig,
  SvgSparkle,
  SvgTerminal,
  SvgTerminalSmall,
} from "@opal/icons";
import { Button } from "@opal/components";
import { cn } from "@opal/utils";
import { useUser } from "@/providers/UserProvider";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { TimelineHeaderRow } from "@/app/app/message/messageComponents/timeline/primitives/TimelineHeaderRow";
import { TimelineRoot } from "@/app/app/message/messageComponents/timeline/primitives/TimelineRoot";
import StepContainer from "@/app/app/message/messageComponents/timeline/StepContainer";

function stringifyValue(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function extractTextContent(value: unknown): string {
  if (typeof value === "string") return value;

  if (Array.isArray(value)) {
    return value
      .map((entry) => {
        if (typeof entry === "string") return entry;
        if (isRecord(entry) && typeof entry.text === "string") {
          return entry.text;
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }

  if (!isRecord(value)) return "";

  if (typeof value.text === "string") return value.text;
  if (typeof value.output === "string") return value.output;
  if (typeof value.stdout === "string") return value.stdout;
  if (typeof value.stderr === "string") return value.stderr;
  if (Array.isArray(value.content)) return extractTextContent(value.content);

  return "";
}

function toolStartContent(args: unknown): string {
  if (!isRecord(args)) return stringifyValue(args);

  const command =
    typeof args.command === "string"
      ? args.command
      : typeof args.cmd === "string"
        ? args.cmd
        : null;

  if (command) return command;

  return stringifyValue(args);
}

function toolResultContent(result: unknown): string {
  const extracted = extractTextContent(result);
  if (extracted) return extracted;
  if (isRecord(result) && "content" in result) return "";
  if (Array.isArray(result) && result.length === 0) return "";
  return stringifyValue(result);
}

function newId(prefix: string): string {
  const randomId =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${randomId}`;
}

function appendToItem(
  items: PiTranscriptItem[],
  id: string,
  delta: string
): PiTranscriptItem[] {
  return items.map((item) =>
    item.id === id ? { ...item, content: `${item.content}${delta}` } : item
  );
}

function appendToItemOrCreate(
  items: PiTranscriptItem[],
  item: PiTranscriptItem,
  delta: string
): PiTranscriptItem[] {
  const itemExists = items.some((currentItem) => currentItem.id === item.id);
  if (itemExists) {
    return appendToItem(items, item.id, delta);
  }

  return [...items, { ...item, content: delta }];
}

function replaceItemContent(
  items: PiTranscriptItem[],
  id: string,
  content: string,
  options: { running?: boolean; error?: boolean } = {}
): PiTranscriptItem[] {
  return items.map((item) =>
    item.id === id
      ? {
          ...item,
          content,
          running: options.running ?? item.running,
          error: options.error ?? item.error,
        }
      : item
  );
}

function eventDisplayText(event: PiStreamEvent): string {
  if (event.text) return event.text;
  if (event.messageText) return event.messageText;
  if (typeof event.message === "string") return event.message;
  if (event.error) return event.error;
  return stringifyValue(event);
}

interface PiConsoleRowProps {
  item: PiTranscriptItem;
}

function PiAvatarMark() {
  return (
    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-background-tint-02">
      <SvgTerminal className="h-3.5 w-3.5 stroke-text-04" />
    </div>
  );
}

function PiUserMessage({ content }: { content: string }) {
  return (
    <div className="flex w-full flex-col justify-end">
      <div className="flex justify-end">
        <div className="md:max-w-150">
          <div className="max-w-120 whitespace-break-spaces break-anywhere rounded-t-16 rounded-bl-16 bg-background-tint-02 px-3 py-2 md:max-w-150">
            <p className="inline-block align-middle text-sm leading-6 text-text-05">
              {content}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function PiAssistantMessage({ item }: PiConsoleRowProps) {
  return (
    <div className="flex flex-col gap-3 px-3">
      <div className="overflow-x-visible focus:outline-hidden select-text cursor-text">
        <MinimalMarkdown
          content={item.content}
          streaming={item.running}
          className="text-text-05"
        />
        {item.running && <BlinkingBar addMargin />}
      </div>
    </div>
  );
}

function PiActivityMessage({ item }: PiConsoleRowProps) {
  const isTool = item.type === "tool";
  const isThinking = item.type === "thinking";
  const isError = item.error || item.type === "error";
  const Icon = isError
    ? SvgAlertCircle
    : isTool
      ? SvgTerminalSmall
      : SvgSparkle;
  const headerText = isError
    ? "Pi ran into an error"
    : isTool
      ? item.running
        ? `Using ${item.title || "tool"}`
        : `Used ${item.title || "tool"}`
      : item.running
        ? "Pi is thinking"
        : "Thought";
  const stepTitle = isTool
    ? item.title || "Tool"
    : isThinking
      ? "Reasoning"
      : item.title || "Error";
  const showCodeSurface = isTool || isError;

  return (
    <TimelineRoot>
      <TimelineHeaderRow left={<PiAvatarMark />}>
        <div className="px-(--timeline-header-text-padding-x) py-(--timeline-header-text-padding-y)">
          <p
            className={cn(
              "text-sm font-medium text-text-03",
              item.running && !isError && "shimmer-text",
              isError && "text-status-error-05"
            )}
          >
            {headerText}
          </p>
        </div>
      </TimelineHeaderRow>
      <StepContainer
        stepIcon={Icon}
        header={stepTitle}
        isFirstStep
        isLastStep
        surfaceBackground={isError ? "error" : "tint"}
      >
        {item.content ? (
          showCodeSurface ? (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-anywhere rounded-08 bg-background-neutral-00 px-3 py-2 font-mono text-xs leading-5 text-text-04">
              {item.content}
            </pre>
          ) : (
            <div className="whitespace-pre-wrap break-anywhere text-sm leading-6 text-text-04">
              {item.content}
            </div>
          )
        ) : item.running ? (
          <div className="flex items-center gap-2 text-sm leading-6 text-text-03">
            <span>Working</span>
            <BlinkingBar />
          </div>
        ) : null}
      </StepContainer>
    </TimelineRoot>
  );
}

function PiConsoleRow({ item }: PiConsoleRowProps) {
  const isUser = item.type === "user";
  const isTool = item.type === "tool";
  const isThinking = item.type === "thinking";
  const isAssistant = item.type === "assistant";
  const isError = item.error || item.type === "error";

  if (isUser) return <PiUserMessage content={item.content} />;
  if (isAssistant) return <PiAssistantMessage item={item} />;
  if (isThinking || isTool || isError) return <PiActivityMessage item={item} />;
  return null;
}

interface PiStatusPillProps {
  children: ReactNode;
}

function PiStatusPill({ children }: PiStatusPillProps) {
  return (
    <div className="max-w-full truncate text-xs text-text-03">{children}</div>
  );
}

interface PiInputTopBarProps {
  status: string | null;
  workspace?: string;
  isRunning: boolean;
  onNewSession: () => void;
}

function PiInputTopBar({
  status,
  workspace,
  isRunning,
  onNewSession,
}: PiInputTopBarProps) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 border-b border-border-01 px-3 py-2">
      <div className="flex min-w-0 items-center gap-2">
        <SvgTerminal className="h-4 w-4 shrink-0 stroke-text-03" />
        <div className="min-w-0 truncate text-xs text-text-03">
          {status || "Pi"}
          {workspace ? (
            <span className="text-text-02"> · {workspace}</span>
          ) : null}
        </div>
      </div>
      <Button
        prominence="tertiary"
        size="sm"
        icon={SvgEditBig}
        onClick={onNewSession}
        disabled={isRunning}
      >
        New Session
      </Button>
    </div>
  );
}

interface ClearActiveSessionOptions {
  updateState?: boolean;
}

export default function PiPage() {
  const router = useRouter();
  const { user } = useUser();
  const piAllowed = isPiAllowedUser(user);
  const [session, setSession] = useState<PiSessionCreateResponse | null>(null);
  const [items, setItems] = useState<PiTranscriptItem[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [isInitializing, setIsInitializing] = useState(true);
  const [isInterrupting, setIsInterrupting] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const mountedRef = useRef(false);
  const sessionRequestIdRef = useRef(0);
  const sessionRef = useRef<PiSessionCreateResponse | null>(null);
  const assistantItemIdRef = useRef<string | null>(null);
  const thinkingItemIdRef = useRef<string | null>(null);
  const toolItemIdsRef = useRef<Map<string, string>>(new Map());
  const toolBaseContentRef = useRef<Map<string, string>>(new Map());

  const clearActiveSession = useCallback(
    ({ updateState = true }: ClearActiveSessionOptions = {}) => {
      sessionRequestIdRef.current += 1;
      abortControllerRef.current?.abort();

      const activeSession = sessionRef.current;
      sessionRef.current = null;
      if (updateState) {
        setSession(null);
      }
      if (activeSession) {
        void deletePiSession(activeSession.session_id).catch(() => undefined);
      }
    },
    []
  );

  const startSession = useCallback(async () => {
    const requestId = ++sessionRequestIdRef.current;
    if (mountedRef.current) {
      setIsInitializing(true);
    }

    try {
      const created = await createPiSession();
      if (!mountedRef.current || sessionRequestIdRef.current !== requestId) {
        void deletePiSession(created.session_id).catch(() => undefined);
        return null;
      }

      sessionRef.current = created;
      setSession(created);
      return created;
    } finally {
      if (mountedRef.current && sessionRequestIdRef.current === requestId) {
        setIsInitializing(false);
      }
    }
  }, []);

  const ensureSession = useCallback(async () => {
    const activeSession = sessionRef.current;
    if (activeSession) {
      return activeSession;
    }
    const created = await startSession();
    if (!created) {
      throw new Error("Pi session was closed before it was ready");
    }
    return created;
  }, [startSession]);

  useEffect(() => {
    mountedRef.current = true;
    if (!user) return;
    if (!piAllowed) {
      router.replace("/app");
      return;
    }

    startSession().catch((error: unknown) => {
      if (!mountedRef.current) return;
      setItems([
        {
          id: newId("error"),
          type: "error",
          title: "Pi",
          content: error instanceof Error ? error.message : String(error),
          error: true,
        },
      ]);
    });

    return () => {
      mountedRef.current = false;
      abortControllerRef.current?.abort();
      clearActiveSession({ updateState: false });
    };
  }, [clearActiveSession, piAllowed, router, startSession, user]);

  const handlePiEvent = useCallback((event: PiStreamEvent) => {
    if (event.type === "agent_start") {
      setIsRunning(true);
      assistantItemIdRef.current = null;
      thinkingItemIdRef.current = null;
      toolItemIdsRef.current.clear();
      toolBaseContentRef.current.clear();
      return;
    }

    if (event.type === "agent_end" || event.type === "bridge_stream_end") {
      setIsRunning(false);
      setIsInterrupting(false);
      assistantItemIdRef.current = null;
      thinkingItemIdRef.current = null;
      setItems((current) =>
        current.map((item) => ({ ...item, running: false }))
      );
      return;
    }

    if (event.type === "message_update") {
      const assistantEvent = event.assistantMessageEvent;
      const delta = assistantEvent?.delta ?? "";

      if (
        assistantEvent?.type !== "thinking_delta" &&
        assistantEvent?.type !== "text_delta"
      ) {
        return;
      }
      if (!delta) return;

      const isThinkingDelta = assistantEvent.type === "thinking_delta";
      if (!isThinkingDelta && thinkingItemIdRef.current) {
        const activeThinkingItemId = thinkingItemIdRef.current;
        thinkingItemIdRef.current = null;
        setItems((current) =>
          current.map((item) =>
            item.id === activeThinkingItemId
              ? { ...item, running: false }
              : item
          )
        );
      }

      let outputItemId = isThinkingDelta
        ? thinkingItemIdRef.current
        : assistantItemIdRef.current;
      if (!outputItemId) {
        const newOutputItemId = newId(
          isThinkingDelta ? "thinking" : "assistant"
        );
        if (isThinkingDelta) {
          thinkingItemIdRef.current = newOutputItemId;
        } else {
          assistantItemIdRef.current = newOutputItemId;
        }
        outputItemId = newOutputItemId;
      }
      setItems((current) =>
        appendToItemOrCreate(
          current,
          {
            id: outputItemId,
            type: isThinkingDelta ? "thinking" : "assistant",
            title: isThinkingDelta ? "Thinking" : "Pi",
            content: "",
            running: true,
          },
          delta
        )
      );
      return;
    }

    if (event.type === "tool_execution_start") {
      const itemId = newId("tool");
      const baseContent = toolStartContent(event.args);
      assistantItemIdRef.current = null;
      thinkingItemIdRef.current = null;
      if (event.toolCallId) {
        toolItemIdsRef.current.set(event.toolCallId, itemId);
        toolBaseContentRef.current.set(event.toolCallId, baseContent);
      }
      setItems((current) => [
        ...current,
        {
          id: itemId,
          type: "tool",
          title: event.toolName || "Tool",
          content: baseContent,
          running: true,
        },
      ]);
      return;
    }

    if (event.type === "tool_execution_update" && event.toolCallId) {
      const itemId = toolItemIdsRef.current.get(event.toolCallId);
      if (!itemId) return;
      const update = toolResultContent(event.partialResult);
      if (!update) return;
      const baseContent =
        toolBaseContentRef.current.get(event.toolCallId) || "";
      setItems((current) =>
        replaceItemContent(
          current,
          itemId,
          baseContent ? `${baseContent}\n\n${update}` : update,
          { running: true }
        )
      );
      return;
    }

    if (event.type === "tool_execution_end" && event.toolCallId) {
      const itemId = toolItemIdsRef.current.get(event.toolCallId);
      if (!itemId) return;
      const result = toolResultContent(event.result);
      const baseContent =
        toolBaseContentRef.current.get(event.toolCallId) || "";
      setItems((current) =>
        replaceItemContent(
          current,
          itemId,
          result && baseContent
            ? `${baseContent}\n\n${result}`
            : result || baseContent,
          {
            running: false,
            error: event.isError,
          }
        )
      );
      return;
    }

    if (event.type === "bridge_error" || event.type === "bridge_stderr") {
      setItems((current) => [
        ...current,
        {
          id: newId("error"),
          type: "error",
          title: "Pi",
          content: eventDisplayText(event),
          error: true,
        },
      ]);
    }
  }, []);

  const handleSubmit = useCallback(
    async (message: string) => {
      const controller = new AbortController();
      abortControllerRef.current = controller;
      setItems((current) => [
        ...current,
        {
          id: newId("user"),
          type: "user",
          content: message,
        },
      ]);
      setIsRunning(true);

      try {
        const activeSession = await ensureSession();
        await streamPiMessage({
          sessionId: activeSession.session_id,
          message,
          signal: controller.signal,
          onEvent: handlePiEvent,
        });
      } catch (error: unknown) {
        if (controller.signal.aborted) return;
        setItems((current) => [
          ...current,
          {
            id: newId("error"),
            type: "error",
            title: "Pi",
            content: error instanceof Error ? error.message : String(error),
            error: true,
          },
        ]);
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
        setIsRunning(false);
        setIsInterrupting(false);
      }
    },
    [ensureSession, handlePiEvent]
  );

  const handleInterrupt = useCallback(async () => {
    if (!session || isInterrupting) return;
    setIsInterrupting(true);
    abortControllerRef.current?.abort();
    try {
      await abortPiSession(session.session_id);
    } finally {
      setIsRunning(false);
      setIsInterrupting(false);
    }
  }, [session, isInterrupting]);

  const status = useMemo(() => {
    if (!session) return null;
    return `${session.provider}/${session.model}`;
  }, [session]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollTo({
      top: container.scrollHeight,
      behavior: isRunning ? "auto" : "smooth",
    });
  }, [items, isRunning]);

  const handleNewSession = useCallback(() => {
    clearActiveSession();
    setItems([]);
    void startSession();
  }, [clearActiveSession, startSession]);

  const hasMessages = items.length > 0;
  const gridStyle = {
    gridTemplateColumns: "1fr",
    gridTemplateRows: hasMessages ? "1fr auto 0fr" : "1fr auto 1fr",
  };

  return (
    <div className="h-full w-full overflow-hidden">
      <div className="flex h-full w-full flex-col items-center overflow-hidden">
        <div
          className="grid min-h-0 w-full flex-1 transition-[grid-template-rows] duration-150 ease-in-out"
          style={gridStyle}
        >
          <div className="row-start-1 flex min-h-0 flex-col items-center overflow-hidden px-4">
            {hasMessages ? (
              <div
                ref={scrollContainerRef}
                className="h-full w-full overflow-y-auto overscroll-y-contain"
                style={{ scrollbarWidth: "thin" }}
              >
                <div className="mx-auto flex w-full max-w-(--app-page-main-content-width) flex-col gap-6 px-1 pb-8 pt-4">
                  {items.map((item) => (
                    <PiConsoleRow key={item.id} item={item} />
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex w-full flex-1 flex-col items-center justify-end">
                <div className="flex w-full max-w-(--app-page-main-content-width) flex-row items-end justify-between">
                  <div className="min-w-0">
                    <div className="text-3xl font-semibold text-text-05">
                      Pi
                    </div>
                    <div className="mt-2 max-w-xl text-sm text-text-03">
                      {status ? (
                        <PiStatusPill>{status}</PiStatusPill>
                      ) : (
                        "Initializing"
                      )}
                    </div>
                  </div>
                </div>
                <div className="h-6" />
              </div>
            )}
          </div>

          <div className="row-start-2 flex flex-col items-center px-4">
            <div className="relative flex w-full max-w-(--app-page-main-content-width) flex-col">
              <div>
                <div
                  className={cn(
                    "overflow-hidden",
                    hasMessages ? "h-0" : "h-[14px]"
                  )}
                />
                <BaseInputBar
                  onSubmit={handleSubmit}
                  isRunning={isRunning}
                  disabled={isInitializing}
                  sandboxInitializing={isInitializing}
                  placeholder="Ask Pi..."
                  onInterrupt={handleInterrupt}
                  isInterrupting={isInterrupting}
                  topSlot={
                    <PiInputTopBar
                      status={status}
                      workspace={session?.workspace}
                      isRunning={isRunning}
                      onNewSession={handleNewSession}
                    />
                  }
                />
                <div
                  className={cn(
                    "overflow-hidden",
                    hasMessages ? "h-[14px]" : "h-0"
                  )}
                />
              </div>
            </div>
          </div>

          <div className="row-start-3 min-h-0 overflow-hidden" />
        </div>
      </div>
    </div>
  );
}
