import type { PiSessionCreateResponse, PiStreamEvent } from "@/lib/pi/types";

export async function createPiSession(): Promise<PiSessionCreateResponse> {
  const response = await fetch("/api/pi/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

export async function abortPiSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/pi/sessions/${sessionId}/abort`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
}

export async function deletePiSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/pi/sessions/${sessionId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
}

export async function streamPiMessage({
  sessionId,
  message,
  signal,
  onEvent,
}: {
  sessionId: string;
  message: string;
  signal?: AbortSignal;
  onEvent: (event: PiStreamEvent) => void;
}): Promise<void> {
  const response = await fetch(`/api/pi/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ message }),
    signal,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
  if (!response.body) {
    throw new Error("Pi stream response had no body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";

    for (const eventBlock of events) {
      const dataLines = eventBlock
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim());
      if (dataLines.length === 0) continue;

      const data = dataLines.join("\n");
      if (!data) continue;

      onEvent(JSON.parse(data) as PiStreamEvent);
    }
  }
}
