import { define } from "@opencode-ai/plugin/v2/effect";
import { Effect, Stream } from "effect";
import { spawn } from "node:child_process";
import path from "node:path";

const PYTHON =
  process.env.MNEMOSYNE_PYTHON ??
  "C:\\Users\\mandu\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe";

const REPO =
  process.env.JEV_MEM_REPO ??
  "C:\\Users\\mandu\\hermes-made\\jev-memory-middleware";

const SCRIPT = path.join(
  __dirname,
  "..",
  "jev_mem_record.py",
);

const TASK_MAX = 300;
const SNIPPET_MAX = 500;
const LIST_MAX = 12;
const ENTRY_MAX = 200;
const SPAWN_TIMEOUT_MS = 15_000;
const PREFETCH_TIMEOUT_MS = 2_000;
const MIN_WRITE_INTERVAL_MS = 30_000;

interface Acc {
  sessionID: string;
  dir: string;
  worktree: string;
  task: string;
  files: Set<string>;
  commands: Set<string>;
  outcome: string;
  turnCount: number;
  lastWriteAt: number;
  lastUserMessageID: string;
  dirty: boolean;
}

function truncate(s: string, n: number): string {
  const clean = s.replace(/\s+/g, " ").trim();
  return clean.length > n ? clean.slice(0, n) + "…" : clean;
}

function firstText(parts: Array<{ type: string; text?: string }>): string {
  const part = parts.find((p) => p.type === "text" && p.text);
  return part?.text ? truncate(part.text, TASK_MAX) : "";
}

/** Spawn `python -m jev_mem_core.client prefetch ...` — context block or "". */
function prefetch(query: string, sessionID: string): Promise<string> {
  return new Promise((resolve) => {
    const args = [
      "-m",
      "jev_mem_core.client",
      "prefetch",
      query,
      "--session-id",
      sessionID,
      "--timeout-ms",
      String(PREFETCH_TIMEOUT_MS),
    ];
    const child = spawn(PYTHON, args, {
      windowsHide: true,
      env: { ...process.env, PYTHONPATH: REPO, JEV_MEM_REPO: REPO },
    });
    let out = "";
    child.stdout.on("data", (d) => (out += d.toString()));
    const timer = setTimeout(() => {
      child.kill();
      resolve("");
    }, PREFETCH_TIMEOUT_MS + 1_000);
    child.on("error", () => {
      clearTimeout(timer);
      resolve("");
    });
    child.on("close", () => {
      clearTimeout(timer);
      resolve(out.trim());
    });
  });
}

/** Spawn `python jev_mem_record.py --content ... --session-id ... --turn-seq N`. */
function writeMemory(acc: Acc): Promise<boolean> {
  if (acc.task.length === 0 && acc.files.size === 0 && acc.commands.size === 0) {
    return Promise.resolve(false);
  }
  const now = Date.now();
  if (now - acc.lastWriteAt < MIN_WRITE_INTERVAL_MS) return Promise.resolve(false);

  const files = [...acc.files].slice(0, LIST_MAX);
  const commands = [...acc.commands].slice(0, LIST_MAX);
  const lines = [
    `[opencode session] task: ${acc.task || "(no task captured)"}`,
    `project: ${acc.dir}`,
    acc.worktree ? `worktree: ${acc.worktree}` : null,
    `turns: ${acc.turnCount}`,
    files.length ? `files: ${files.join(", ")}` : null,
    commands.length ? `commands: ${commands.join(", ")}` : null,
    acc.outcome ? `outcome: ${acc.outcome}` : null,
  ].filter((l): l is string => Boolean(l));

  return new Promise((resolve) => {
    const args = [
      SCRIPT,
      "--content",
      lines.join("\n"),
      "--session-id",
      acc.sessionID,
      "--turn-seq",
      String(acc.turnCount),
      "--metadata",
      JSON.stringify({
        session_id: acc.sessionID,
        project_dir: acc.dir,
        worktree: acc.worktree,
        files,
        commands,
      }),
    ];
    const child = spawn(PYTHON, args, {
      windowsHide: true,
      env: { ...process.env, PYTHONPATH: REPO, JEV_MEM_REPO: REPO },
    });
    const timer = setTimeout(() => {
      child.kill();
      resolve(false);
    }, SPAWN_TIMEOUT_MS);
    child.on("error", () => {
      clearTimeout(timer);
      resolve(false);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve(code === 0);
    });
  });
}

export default define({
  id: "mnemosyne-session-memory",
  effect: (ctx) =>
    Effect.gen(function* () {
      const sessions = new Map<string, Acc>();

      function accFor(id: string, init?: Partial<Acc>): Acc | undefined {
        let acc = sessions.get(id);
        if (!acc) {
          if (!init) return undefined;
          acc = {
            sessionID: id,
            dir: init.dir ?? ctx.project.directory ?? "",
            worktree: init.worktree ?? ctx.project.worktree ?? "",
            task: "",
            files: new Set<string>(),
            commands: new Set<string>(),
            outcome: "",
            turnCount: 0,
            lastWriteAt: 0,
            lastUserMessageID: "",
            dirty: false,
          };
          sessions.set(id, acc);
        }
        return acc;
      }

      // session.idle — flush accumulated session digest to JEV core
      yield* Stream.runForEach(
        ctx.event.subscribe("session.idle"),
        (ev) =>
          Effect.sync(() => {
            const acc = sessions.get(ev.properties.sessionID);
            if (!acc || !acc.dirty) return;
            void writeMemory(acc).then((ok) => {
              if (ok) {
                acc.lastWriteAt = Date.now();
                acc.dirty = false;
              }
            });
          }),
      );

      // session.created — pre-register session dir
      yield* Stream.runForEach(
        ctx.event.subscribe("session.created"),
        (ev) =>
          Effect.sync(() => {
            const info = ev.properties.info as {
              id: string;
              directory?: string;
            };
            accFor(info.id, { dir: info.directory });
          }),
      );

      // session.deleted — drop tracking
      yield* Stream.runForEach(
        ctx.event.subscribe("session.deleted"),
        (ev) =>
          Effect.sync(() => {
            sessions.delete((ev.properties.info as { id: string }).id);
          }),
      );

      // message.part.updated — capture task (first user text) and outcome (assistant text)
      yield* Stream.runForEach(
        ctx.event.subscribe("message.part.updated"),
        (ev) =>
          Effect.sync(() => {
            const acc = accFor(ev.properties.sessionID);
            if (!acc) return;
            const part = ev.properties.part as {
              type?: string;
              text?: string;
              messageID?: string;
              synthetic?: boolean;
            };
            if (part.type === "text" && part.text) {
              if (part.messageID === acc.lastUserMessageID) {
                if (!acc.task) acc.task = truncate(part.text, TASK_MAX);
              } else if (!part.synthetic) {
                acc.outcome = truncate(part.text, SNIPPET_MAX);
              }
            }
          }),
      );

      // tool.execute.after — remember bash commands and edited files
      yield* Stream.runForEach(
        ctx.event.subscribe("tool.execute.after"),
        (ev) =>
          Effect.sync(() => {
            const acc = accFor(
              (ev.properties as { sessionID: string }).sessionID,
            );
            if (!acc) return;
            const props = ev.properties as {
              tool: string;
              args?: Record<string, unknown>;
            };
            if (props.tool === "bash" && typeof props.args?.command === "string") {
              acc.commands.add(truncate(props.args.command, ENTRY_MAX));
              acc.dirty = true;
            } else if (
              (props.tool === "edit" || props.tool === "write") &&
              typeof props.args?.filePath === "string"
            ) {
              acc.files.add(props.args.filePath);
              acc.dirty = true;
            }
          }),
      );

      // P4: prefetch memory from JEV core, inject as a system prompt block
      // via the AI SDK language-model wrapper (v2 API has no message hook).
      // Runs for every model call; prefetch is cached per prompt so the
      // per-turn overhead is one core HTTP round-trip (≤2s, best-effort).
      const prefetchCache = new Map<string, string>();
      yield* ctx.aisdk.language((input) => {
        const base = input.language;
        if (!base) return;
        input.language = {
          ...base,
          async doGenerate(options: any) {
            const prompt: Array<any> = options?.prompt ?? [];
            const lastUser = [...prompt]
              .reverse()
              .find(
                (m) =>
                  m?.role === "user" &&
                  Array.isArray(m.content) &&
                  m.content.some(
                    (p: any) => typeof p?.text === "string" && p.text.trim().length >= 3,
                  ),
              );
            const userText = lastUser
              ? (
                  lastUser.content as Array<any>
                )
                  .filter((p: any) => typeof p?.text === "string")
                  .map((p: any) => p.text)
                  .join(" ")
                  .trim()
              : "";
            if (userText) {
              try {
                const key = userText.slice(0, 300);
                let ctxBlock = prefetchCache.get(key);
                if (ctxBlock === undefined) {
                  ctxBlock = await prefetch(
                    userText,
                    options?.sessionID ?? "",
                  );
                  prefetchCache.set(key, ctxBlock ?? "");
                }
                if (ctxBlock) {
                  const sysIdx = prompt.findIndex((m) => m?.role === "system");
                  if (sysIdx >= 0) {
                    const sys = prompt[sysIdx];
                    if (typeof sys.content === "string" && !sys.content.includes(ctxBlock)) {
                      prompt[sysIdx] = { ...sys, content: sys.content + "\n\n" + ctxBlock };
                    }
                  } else {
                    prompt.unshift({ role: "system", content: ctxBlock });
                  }
                  options = { ...options, prompt };
                }
              } catch {
                // best-effort; never block the model call
              }
            }
            return base.doGenerate(options);
          },
          async doStream(options: any) {
            const prompt: Array<any> = options?.prompt ?? [];
            const lastUser = [...prompt]
              .reverse()
              .find(
                (m) =>
                  m?.role === "user" &&
                  Array.isArray(m.content) &&
                  m.content.some(
                    (p: any) => typeof p?.text === "string" && p.text.trim().length >= 3,
                  ),
              );
            const userText = lastUser
              ? (
                  lastUser.content as Array<any>
                )
                  .filter((p: any) => typeof p?.text === "string")
                  .map((p: any) => p.text)
                  .join(" ")
                  .trim()
              : "";
            if (userText) {
              try {
                const key = userText.slice(0, 300);
                let ctxBlock = prefetchCache.get(key);
                if (ctxBlock === undefined) {
                  ctxBlock = await prefetch(
                    userText,
                    options?.sessionID ?? "",
                  );
                  prefetchCache.set(key, ctxBlock ?? "");
                }
                if (ctxBlock) {
                  const sysIdx = prompt.findIndex((m) => m?.role === "system");
                  if (sysIdx >= 0) {
                    const sys = prompt[sysIdx];
                    if (typeof sys.content === "string" && !sys.content.includes(ctxBlock)) {
                      prompt[sysIdx] = { ...sys, content: sys.content + "\n\n" + ctxBlock };
                    }
                  } else {
                    prompt.unshift({ role: "system", content: ctxBlock });
                  }
                  options = { ...options, prompt };
                }
              } catch {
                // best-effort; never block the model call
              }
            }
            return base.doStream(options);
          },
        };
      });
    }),
});