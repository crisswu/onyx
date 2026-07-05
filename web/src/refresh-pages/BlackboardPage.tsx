"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type UIEvent,
} from "react";
import { useRouter } from "next/navigation";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { isBlackboardAllowedUser } from "@/lib/blackboard/access";
import {
  getBlackboard,
  listBlackboards,
  saveBlackboard,
} from "@/lib/blackboard/client";
import type {
  BlackboardSettings,
  BlackboardSummary,
} from "@/lib/blackboard/types";
import { useUser } from "@/providers/UserProvider";
import { Button } from "@opal/components";
import { SvgFileText } from "@opal/icons";
import { cn } from "@opal/utils";

const BOARD_NUMBERS = Array.from({ length: 10 }, (_, index) => index + 1);
const FONT_SIZES = [12, 14, 16, 18, 20, 24];
type ResolvedBlackboardSettings = BlackboardSettings & { fontSize: number };
const DEFAULT_SETTINGS: ResolvedBlackboardSettings = {
  fontSize: 16,
};

function formatSaveTime(timestamp: string | null): string {
  if (!timestamp) return "--:--:--";

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function BlackboardPage() {
  const router = useRouter();
  const { user } = useUser();
  const blackboardAllowed = isBlackboardAllowedUser(user);
  const editorRef = useRef<HTMLTextAreaElement | null>(null);
  const previewRef = useRef<HTMLDivElement | null>(null);
  const [currentBoard, setCurrentBoard] = useState(1);
  const [boards, setBoards] = useState<BlackboardSummary[]>([]);
  const [content, setContent] = useState("");
  const [settings, setSettings] =
    useState<ResolvedBlackboardSettings>(DEFAULT_SETTINGS);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saved" | "failed">(
    "idle"
  );
  const [error, setError] = useState<string | null>(null);

  const boardByNumber = useMemo(() => {
    return new Map(boards.map((board) => [board.board_number, board]));
  }, [boards]);

  const refreshBoardList = useCallback(async () => {
    const summaries = await listBlackboards();
    setBoards(summaries);
  }, []);

  const loadBoard = useCallback(
    async (boardNumber: number) => {
      setIsLoading(true);
      setError(null);
      try {
        const [board] = await Promise.all([
          getBlackboard(boardNumber),
          refreshBoardList(),
        ]);
        setCurrentBoard(board.board_number);
        setContent(board.content || "");
        const savedFontSize =
          typeof board.settings.fontSize === "number"
            ? board.settings.fontSize
            : DEFAULT_SETTINGS.fontSize;
        setSettings({
          ...DEFAULT_SETTINGS,
          ...board.settings,
          fontSize: savedFontSize,
        });
        setLastSavedAt(board.updated_at);
        setHasUnsavedChanges(false);
        setSaveState("idle");
      } catch (requestError: unknown) {
        setError(
          requestError instanceof Error
            ? requestError.message
            : String(requestError)
        );
      } finally {
        setIsLoading(false);
      }
    },
    [refreshBoardList]
  );

  useEffect(() => {
    if (!user) return;
    if (!blackboardAllowed) {
      router.replace("/app");
      return;
    }

    void loadBoard(1);
  }, [blackboardAllowed, loadBoard, router, user]);

  const handleSave = useCallback(async (): Promise<boolean> => {
    setIsSaving(true);
    setSaveState("idle");
    setError(null);
    try {
      const result = await saveBlackboard({
        boardNumber: currentBoard,
        content,
        settings,
      });
      setLastSavedAt(result.updated_at);
      setHasUnsavedChanges(false);
      setSaveState("saved");
      await refreshBoardList();
      window.setTimeout(() => setSaveState("idle"), 1200);
      return true;
    } catch (requestError: unknown) {
      setSaveState("failed");
      setError(
        requestError instanceof Error
          ? requestError.message
          : String(requestError)
      );
      window.setTimeout(() => setSaveState("idle"), 2200);
      return false;
    } finally {
      setIsSaving(false);
    }
  }, [content, currentBoard, refreshBoardList, settings]);

  const handleBoardChange = useCallback(
    async (event: ChangeEvent<HTMLSelectElement>) => {
      const nextBoard = Number(event.target.value);
      if (nextBoard === currentBoard) return;

      if (hasUnsavedChanges) {
        const shouldSave = window.confirm(
          `黑板 ${currentBoard} 有未保存的更改，是否保存后切换？\n\n` +
            `[确定] = 保存后切换\n` +
            `[取消] = 放弃更改`
        );
        if (shouldSave) {
          const saved = await handleSave();
          if (!saved) return;
        }
      }

      await loadBoard(nextBoard);
    },
    [currentBoard, handleSave, hasUnsavedChanges, loadBoard]
  );

  const handleContentChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      setContent(event.target.value);
      setHasUnsavedChanges(true);
    },
    []
  );

  const handleFontSizeChange = useCallback(
    (event: ChangeEvent<HTMLSelectElement>) => {
      setSettings({
        ...settings,
        fontSize: Number(event.target.value),
      });
      setHasUnsavedChanges(true);
    },
    [settings]
  );

  const handleEditorScroll = useCallback(
    (event: UIEvent<HTMLTextAreaElement>) => {
      const preview = previewRef.current;
      if (!preview) return;

      const editor = event.currentTarget;
      const editorScrollable = editor.scrollHeight - editor.clientHeight;
      const previewScrollable = preview.scrollHeight - preview.clientHeight;
      if (editorScrollable <= 0 || previewScrollable <= 0) return;

      preview.scrollTop =
        (editor.scrollTop / editorScrollable) * previewScrollable;
    },
    []
  );

  const handleEditorKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== "Tab") return;

      event.preventDefault();
      const editor = event.currentTarget;
      const start = editor.selectionStart;
      const end = editor.selectionEnd;
      const nextContent = `${content.slice(0, start)}    ${content.slice(end)}`;
      setContent(nextContent);
      setHasUnsavedChanges(true);

      window.requestAnimationFrame(() => {
        editor.selectionStart = start + 4;
        editor.selectionEnd = start + 4;
      });
    },
    [content]
  );

  const saveButtonText =
    saveState === "saved" ? "保存成功" : saveState === "failed" ? "保存失败" : "保存";

  return (
    <main className="flex h-full min-h-0 flex-col bg-background text-text-04">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center border border-border bg-background-sidebar text-text-03">
            <SvgFileText size={18} />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold text-text-05">
              黑板
            </h1>
            <div className="truncate text-xs text-text-03">
              最后保存: {formatSaveTime(lastSavedAt)}
              {hasUnsavedChanges ? " · 未保存" : ""}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <select
            className="h-9 min-w-28 border border-border bg-background-sidebar px-3 text-sm text-text-04 outline-none transition-colors hover:border-text-03 focus:border-link"
            value={currentBoard}
            onChange={handleBoardChange}
            disabled={isLoading || isSaving}
            aria-label="选择黑板"
          >
            {BOARD_NUMBERS.map((boardNumber) => {
              const board = boardByNumber.get(boardNumber);
              return (
                <option key={boardNumber} value={boardNumber}>
                  黑板 {boardNumber}
                  {board?.has_content ? " ✓" : ""}
                </option>
              );
            })}
          </select>
          <Button
            onClick={() => void handleSave()}
            disabled={isSaving || isLoading}
            size="sm"
          >
            {isSaving ? "保存中..." : saveButtonText}
          </Button>
        </div>
      </header>

      {error ? (
        <div className="border-b border-red-200 bg-red-50 px-5 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {error}
        </div>
      ) : null}

      <section className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden p-4 lg:grid-cols-2">
        <div className="flex min-h-0 flex-col border border-border bg-background-sidebar">
          <div className="shrink-0 border-b border-border px-4 py-3 text-xs font-semibold uppercase tracking-wide text-link">
            Editor
          </div>
          <textarea
            ref={editorRef}
            className="min-h-0 flex-1 resize-none bg-transparent p-4 font-mono leading-7 text-text-05 outline-none placeholder:text-text-02"
            style={{ fontSize: settings.fontSize }}
            value={content}
            onChange={handleContentChange}
            onScroll={handleEditorScroll}
            onKeyDown={handleEditorKeyDown}
            placeholder="在这里记录你的想法..."
            spellCheck={false}
            disabled={isLoading}
          />
        </div>

        <div className="flex min-h-0 flex-col border border-border bg-background">
          <div className="shrink-0 border-b border-border px-4 py-3 text-xs font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-300">
            Preview
          </div>
          <div
            ref={previewRef}
            className={cn(
              "min-h-0 flex-1 overflow-y-auto p-4",
              isLoading && "opacity-60"
            )}
          >
            <MinimalMarkdown
              content={content}
              className="max-w-none text-text-04"
              showHeader={false}
            />
          </div>
        </div>
      </section>

      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3">
        <label className="flex items-center gap-2 text-sm text-text-03">
          <span className="text-xs uppercase tracking-wide">字体</span>
          <select
            className="h-8 border border-border bg-background-sidebar px-2 text-sm text-text-04 outline-none hover:border-text-03 focus:border-link"
            value={settings.fontSize}
            onChange={handleFontSizeChange}
            disabled={isLoading || isSaving}
          >
            {FONT_SIZES.map((fontSize) => (
              <option key={fontSize} value={fontSize}>
                {fontSize}px
              </option>
            ))}
          </select>
        </label>

        <div className="text-xs text-text-03">
          黑板 {currentBoard}
          {boardByNumber.get(currentBoard)?.has_content ? " · 已记录" : ""}
        </div>
      </footer>
    </main>
  );
}
