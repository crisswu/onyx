import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { once } from "node:events";
import path from "node:path";

const PORT = Number.parseInt(process.env.PI_BRIDGE_PORT || "8787", 10);
const HOST = process.env.PI_BRIDGE_HOST || "0.0.0.0";
const PI_BINARY = process.env.PI_BINARY || "/home/criss/Pi/pi";
const PI_WORKSPACE = process.env.PI_WORKSPACE || "/home/criss/pi-workspace";
const PI_PROVIDER = process.env.PI_PROVIDER || "qwen";
const PI_MODEL = process.env.PI_MODEL || "qwen3.7-plus";
const PI_SESSION_DIR =
  process.env.PI_SESSION_DIR || "/home/criss/Pi/.pi/agent/onyx-sessions";
const PI_MAX_SESSIONS = Number.parseInt(process.env.PI_MAX_SESSIONS || "20", 10);
const PI_SESSION_IDLE_TIMEOUT_MS = Number.parseInt(
  process.env.PI_SESSION_IDLE_TIMEOUT_MS || `${30 * 60 * 1000}`,
  10
);
const PI_STREAM_IDLE_TIMEOUT_MS = Number.parseInt(
  process.env.PI_STREAM_IDLE_TIMEOUT_MS || `${90 * 1000}`,
  10
);

mkdirSync(PI_WORKSPACE, { recursive: true });
mkdirSync(PI_SESSION_DIR, { recursive: true });

/** @type {Map<string, PiSession>} */
const sessions = new Map();

class PiSession {
  constructor({ id, userId }) {
    this.id = id;
    this.userId = userId;
    this.listeners = new Set();
    this.responseHandlers = new Map();
    this.stdoutBuffer = "";
    this.stderrBuffer = "";
    this.closed = false;
    this.idleTimer = null;

    this.process = spawn(
      PI_BINARY,
      [
        "--mode",
        "rpc",
        "--provider",
        PI_PROVIDER,
        "--model",
        PI_MODEL,
        "--session-dir",
        PI_SESSION_DIR,
        "--approve",
        "--name",
        `Onyx Pi ${id}`,
      ],
      {
        cwd: PI_WORKSPACE,
        env: {
          ...process.env,
          PI_CODING_AGENT_DIR:
            process.env.PI_CODING_AGENT_DIR || "/home/criss/Pi/.pi/agent",
        },
        stdio: ["pipe", "pipe", "pipe"],
      }
    );

    this.touch();
    this.process.stdout.setEncoding("utf8");
    this.process.stdout.on("data", (chunk) => this.handleStdout(chunk));
    this.process.stderr.setEncoding("utf8");
    this.process.stderr.on("data", (chunk) => this.handleStderr(chunk));
    this.process.on("exit", (code, signal) => {
      this.closed = true;
      this.emit({
        type: "bridge_session_exit",
        code,
        signal,
      });
      sessions.delete(this.id);
    });
    this.process.on("error", (error) => {
      this.closed = true;
      this.emit({
        type: "bridge_error",
        message: error instanceof Error ? error.message : String(error),
      });
    });
  }

  clearIdleTimer() {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  touch() {
    if (PI_SESSION_IDLE_TIMEOUT_MS <= 0 || this.closed) return;
    this.clearIdleTimer();
    this.idleTimer = setTimeout(() => {
      sessions.delete(this.id);
      this.dispose();
    }, PI_SESSION_IDLE_TIMEOUT_MS);
    this.idleTimer.unref?.();
  }

  handleStdout(chunk) {
    this.touch();
    this.stdoutBuffer += chunk;
    const lines = this.stdoutBuffer.split("\n");
    this.stdoutBuffer = lines.pop() || "";
    for (const rawLine of lines) {
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
      if (!line.trim()) continue;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        this.emit({ type: "bridge_stdout", text: line });
        continue;
      }

      if (event.type === "response" && event.id) {
        const handler = this.responseHandlers.get(event.id);
        if (handler) {
          this.responseHandlers.delete(event.id);
          handler(event);
        }
      }
      this.emit(event);
    }
  }

  handleStderr(chunk) {
    this.touch();
    this.stderrBuffer += chunk;
    const lines = this.stderrBuffer.split("\n");
    this.stderrBuffer = lines.pop() || "";
    for (const rawLine of lines) {
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
      if (line.trim()) {
        this.emit({ type: "bridge_stderr", text: line });
      }
    }
  }

  emit(event) {
    for (const listener of this.listeners) {
      listener(event);
    }
  }

  send(command) {
    if (this.closed || !this.process.stdin.writable) {
      throw new Error("Pi session is not running");
    }
    this.process.stdin.write(`${JSON.stringify(command)}\n`);
  }

  request(command, timeoutMs = 30000) {
    this.touch();
    const id = command.id || randomUUID();
    const payload = { ...command, id };
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.responseHandlers.delete(id);
        reject(new Error(`Timed out waiting for ${payload.type}`));
      }, timeoutMs);

      this.responseHandlers.set(id, (response) => {
        clearTimeout(timeout);
        resolve(response);
      });

      try {
        this.send(payload);
      } catch (error) {
        clearTimeout(timeout);
        this.responseHandlers.delete(id);
        reject(error);
      }
    });
  }

  dispose() {
    if (this.closed) return;
    this.closed = true;
    this.clearIdleTimer();
    this.listeners.clear();
    this.process.kill("SIGTERM");
    const killTimer = setTimeout(() => {
      if (this.process.exitCode === null && this.process.signalCode === null) {
        this.process.kill("SIGKILL");
      }
    }, 5000);
    killTimer.unref?.();
    this.process.once("exit", () => clearTimeout(killTimer));
  }
}

function writeJson(response, statusCode, body) {
  response.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
  });
  response.end(JSON.stringify(body));
}

async function readJson(request) {
  let body = "";
  request.setEncoding("utf8");
  request.on("data", (chunk) => {
    body += chunk;
    if (body.length > 1024 * 1024) {
      request.destroy(new Error("Request body too large"));
    }
  });
  await once(request, "end");
  return body ? JSON.parse(body) : {};
}

function sendSse(response, event) {
  response.write(`data: ${JSON.stringify(event)}\n\n`);
}

function getSessionOr404(response, sessionId) {
  const session = sessions.get(sessionId);
  if (!session) {
    writeJson(response, 404, { detail: "Pi session not found" });
    return null;
  }
  return session;
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", "http://localhost");
    const parts = url.pathname.split("/").filter(Boolean);

    if (request.method === "GET" && url.pathname === "/health") {
      writeJson(response, 200, {
        status: "ok",
        workspace: PI_WORKSPACE,
        provider: PI_PROVIDER,
        model: PI_MODEL,
      });
      return;
    }

    if (request.method === "POST" && url.pathname === "/sessions") {
      if (sessions.size >= PI_MAX_SESSIONS) {
        writeJson(response, 429, { detail: "Too many active Pi sessions" });
        return;
      }

      const body = await readJson(request);
      const id = randomUUID();
      const session = new PiSession({ id, userId: body.userId ?? null });
      sessions.set(id, session);
      writeJson(response, 200, {
        sessionId: id,
        workspace: path.resolve(PI_WORKSPACE),
        provider: PI_PROVIDER,
        model: PI_MODEL,
      });
      return;
    }

    if (
      request.method === "POST" &&
      parts.length === 3 &&
      parts[0] === "sessions" &&
      parts[2] === "messages"
    ) {
      const session = getSessionOr404(response, parts[1]);
      if (!session) return;
      const body = await readJson(request);
      const message = typeof body.message === "string" ? body.message : "";
      if (!message.trim()) {
        writeJson(response, 400, { detail: "Message is required" });
        return;
      }

      response.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      });

      let runStarted = false;
      let streamClosed = false;
      let inactivityTimer = null;
      const closeStream = () => {
        if (streamClosed) return;
        streamClosed = true;
        if (inactivityTimer) {
          clearTimeout(inactivityTimer);
          inactivityTimer = null;
        }
        session.listeners.delete(listener);
        response.end();
      };
      const resetInactivityTimer = () => {
        if (PI_STREAM_IDLE_TIMEOUT_MS <= 0 || streamClosed) return;
        if (inactivityTimer) clearTimeout(inactivityTimer);
        inactivityTimer = setTimeout(() => {
          if (streamClosed) return;
          sendSse(response, {
            type: "bridge_error",
            message:
              "Pi stopped sending output before completing the response. The stream was closed to avoid hanging.",
          });
          sendSse(response, { type: "bridge_stream_end" });
          closeStream();
        }, PI_STREAM_IDLE_TIMEOUT_MS);
        inactivityTimer.unref?.();
      };
      const listener = (event) => {
        if (streamClosed) return;
        resetInactivityTimer();
        sendSse(response, event);
        if (event.type === "agent_start") {
          runStarted = true;
        }
        if (
          runStarted &&
          (event.type === "agent_end" || event.type === "bridge_session_exit")
        ) {
          sendSse(response, { type: "bridge_stream_end" });
          closeStream();
        }
      };
      session.listeners.add(listener);
      resetInactivityTimer();
      response.on("close", () => {
        session.listeners.delete(listener);
        if (inactivityTimer) {
          clearTimeout(inactivityTimer);
          inactivityTimer = null;
        }
        streamClosed = true;
      });

      try {
        const responseEvent = await session.request({
          type: "prompt",
          message,
        });
        if (!responseEvent.success) {
          sendSse(response, responseEvent);
          sendSse(response, { type: "bridge_stream_end" });
          closeStream();
        }
      } catch (error) {
        sendSse(response, {
          type: "bridge_error",
          message: error instanceof Error ? error.message : String(error),
        });
        sendSse(response, { type: "bridge_stream_end" });
        closeStream();
      }
      return;
    }

    if (
      request.method === "POST" &&
      parts.length === 3 &&
      parts[0] === "sessions" &&
      parts[2] === "abort"
    ) {
      const session = getSessionOr404(response, parts[1]);
      if (!session) return;
      const result = await session.request({ type: "abort" }, 10000);
      writeJson(response, result.success ? 200 : 500, result);
      return;
    }

    if (
      request.method === "POST" &&
      url.pathname === "/set_model"
    ) {
      const body = await readJson(request);
      const { provider, modelId } = body;
      if (!provider || !modelId) {
        writeJson(response, 400, { detail: "provider and modelId are required" });
        return;
      }
      const results = [];
      for (const [sessionId, session] of sessions) {
        try {
          const result = await session.request(
            { type: "set_model", provider, modelId },
            15000
          );
          results.push({ sessionId, success: result.success, data: result.data });
        } catch (error) {
          results.push({ sessionId, success: false, error: error.message });
        }
      }
      writeJson(response, 200, { success: true, results });
      return;
    }

    if (
      request.method === "DELETE" &&
      parts.length === 2 &&
      parts[0] === "sessions"
    ) {
      const session = getSessionOr404(response, parts[1]);
      if (!session) return;
      session.dispose();
      sessions.delete(parts[1]);
      writeJson(response, 200, { success: true });
      return;
    }

    writeJson(response, 404, { detail: "Not found" });
  } catch (error) {
    writeJson(response, 500, {
      detail: error instanceof Error ? error.message : String(error),
    });
  }
});

process.on("SIGTERM", () => {
  for (const session of sessions.values()) session.dispose();
  server.close(() => process.exit(0));
});

server.listen(PORT, HOST, () => {
  console.log(
    `Pi bridge listening on ${HOST}:${PORT}; workspace=${PI_WORKSPACE}; model=${PI_PROVIDER}/${PI_MODEL}`
  );
});
