import type {
  BlackboardEntry,
  BlackboardSaveResponse,
  BlackboardSettings,
  BlackboardSummary,
} from "@/lib/blackboard/types";

async function readJsonOrThrow<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.json() as Promise<T>;
  }

  let message = await response.text();
  try {
    const payload = JSON.parse(message) as { detail?: string };
    if (typeof payload.detail === "string") {
      message = payload.detail;
    }
  } catch {
    // Keep the raw response text.
  }
  throw new Error(message || "Blackboard request failed");
}

export async function listBlackboards(): Promise<BlackboardSummary[]> {
  const response = await fetch("/api/blackboard/all");
  return readJsonOrThrow<BlackboardSummary[]>(response);
}

export async function getBlackboard(
  boardNumber: number
): Promise<BlackboardEntry> {
  const response = await fetch(`/api/blackboard/${boardNumber}`);
  return readJsonOrThrow<BlackboardEntry>(response);
}

export async function saveBlackboard({
  boardNumber,
  content,
  settings,
}: {
  boardNumber: number;
  content: string;
  settings: BlackboardSettings;
}): Promise<BlackboardSaveResponse> {
  const response = await fetch(`/api/blackboard/${boardNumber}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, settings }),
  });
  return readJsonOrThrow<BlackboardSaveResponse>(response);
}

