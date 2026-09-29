/**
 * pi-jev-mem — JEV Memory middleware adapter for pi (Core-as-Writer, D9).
 *
 * Connects pi to the jev-mem-core daemon via jev_mem_core.client (HTTP
 * + auto-start + spool). Hermes path unchanged (regression 0).
 *
 * Turn flow (mirrors Hermes):
 *   before_agent_start -> prefetch(prompt) -> append Mnemosyne Context block
 *   turn_end           -> sync_turn(user, assistant) via client.turn()
 *
 * Zero-dependency: spawns the Hermes venv python directly (`-m jev_mem_core
 * .client`) with PYTHONPATH pointing at the repo (hoplite pattern).
 * Falls back silently when the repo/venv is unavailable (best-effort).
 */
import { spawn } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

// Resolved from the repo checkout; env override for tests/dev.
const REPO = process.env.JEV_MEM_REPO ?? "C:/Users/mandu/hermes-made/jev-memory-middleware";
const PYTHON =
  process.env.JEV_MEM_PYTHON ??
  "C:/Users/mandu/AppData/Local/hermes/installs/315db7b763fb0d0a/environments/746564964b1042b79add42260378503b/venv/Scripts/python.exe";

const AGENT = "pi";
const PREFETCH_TIMEOUT_MS = 2000; // v1.1 D7a: prefetch 상한 2.0s
const SYNC_TIMEOUT_MS = 20000;    // gate는 JEV 15s + retry 1회 — 여유

/** Run one jev_mem_core.client CLI call, resolve with stdout. */
function runClient(args: string[], timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const env = {
      ...process.env,
      PYTHONPATH: REPO,
      PYTHONIOENCODING: "utf-8",
    };
    const child = spawn(
      PYTHON,
      ["-m", "jev_mem_core.client", "--agent", AGENT, ...args],
      { env, windowsHide: true }
    );
    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`jev-mem-client timeout (${timeoutMs}ms): ${err || out || "no output"}`));
    }, timeoutMs + 3000);
    child.stdout.on("data", (d: Buffer) => (out += d.toString()));
    child.stderr.on("data", (d: Buffer) => (err += d.toString()));
    child.on("error", (e: Error) => {
      clearTimeout(timer);
      reject(e);
    });
    child.on("close", (code: number | null) => {
      clearTimeout(timer);
      if (code === 0) resolve(out.trim());
      else reject(new Error(`jev-mem-client exit ${code}: ${err || out || "no output"}`));
    });
  });
}

/** Text of an AgentMessage content (string | content blocks | null). */
function textOf(content: unknown): string {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter(
        (b: { type?: string; text?: string }) =>
          b && b.type === "text" && typeof b.text === "string"
      )
      .map((b: { text: string }) => b.text)
      .join("\n");
  }
  return "";
}

export default function jevMemExtension(api: ExtensionAPI): void {
  const log = (...a: unknown[]) => {
    // no logger in ExtensionAPI; stderr shows in diagnostics
    console.error("[jev-mem]", ...a);
  };

  let sessionIdCache: string | undefined;

  api.on("session_start", async (evt, ctx: ExtensionContext) => {
    try {
      sessionIdCache = ctx.sessionManager.getSessionId();
    } catch {
      sessionIdCache = undefined;
    }
    log("session_start", sessionIdCache ?? "(none)");
  });

  api.on("before_agent_start", async (evt) => {
    const ev = evt as { prompt?: string; systemPrompt?: string };
    const prompt = ev.prompt ?? "";
    if (!prompt || prompt.trim().length < 20) return;
    try {
      const out = await runClient(["prefetch", prompt], PREFETCH_TIMEOUT_MS);
      const line = out.split("\n").filter((l) => l.startsWith("{")).join("\n");
      let blockText = "";
      if (line) {
        const parsed = JSON.parse(line) as { block?: string };
        blockText = parsed.block ?? "";
      } else if (out.trim().length > 0) {
        // CLI stdout may be raw block text
        blockText = out.trim();
      }
      if (!blockText) return;
      const sys = ev.systemPrompt ?? "";
      ev.systemPrompt = sys
        ? `${sys}\n\n${blockText.trim()}\n`
        : `${blockText.trim()}\n`;
      log("prefetch injected", blockText.length);
    } catch (e) {
      log("prefetch skipped", String(e));
    }
  });

  api.on("turn_end", async (evt, ctx: ExtensionContext) => {
    try {
      const ev = evt as { message?: { content?: unknown } };
      const asst = textOf(ev.message?.content);
      // user text: turn_end carries no user message; take the last user entry
      let userText = "";
      try {
        const entries = (ctx.sessionManager.getEntries() ?? []) as Array<{
          type?: string;
          message?: { role?: string; content?: unknown };
        }>;
        for (let i = entries.length - 1; i >= 0; i--) {
          const e = entries[i];
          if (e?.type === "message" && e.message?.role === "user") {
            userText = textOf(e.message.content);
            break;
          }
        }
      } catch {
        userText = "";
      }
      if (!asst && !userText) return;

      const sessionId =
        sessionIdCache ?? ctx.sessionManager.getSessionId() ?? "pi-session";
      const out = await runClient(
        ["turn", "--session-id", sessionId, "--user", userText, "--assistant", asst],
        SYNC_TIMEOUT_MS
      );
      const line = out.split("\n").filter((l) => l.startsWith("{")).join("\n");
      if (line) {
        const res = JSON.parse(line) as {
          ok?: boolean;
          status?: string;
          error?: string;
          pending?: boolean;
        };
        log("sync_turn", res.status ?? res.error ?? "ok");
      }
    } catch (e) {
      // core 다운/시간 초과 — client가 스풀에 기록하므로 손실 없음
      log("sync_turn failed (spooled if core down)", String(e));
    }
  });
}