import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import sessionHandoff from "../../../config/agents/pi/pi-extensions/session-handoff.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

test("/cd validates before stopping Pi and records a saved-session handoff", async () => {
  const directory = mkdtempSync(join(tmpdir(), "pi-session-handoff-"));
  const request = join(directory, "request.json");
  const session = join(directory, "session.jsonl");
  writeFileSync(session, "saved session");
  const previousRequest = process.env.CODEX_SANDBOX_CD_REQUEST;
  const previousValidator = process.env.CODEX_SANDBOX_CD_VALIDATE;
  process.env.CODEX_SANDBOX_CD_REQUEST = request;
  process.env.CODEX_SANDBOX_CD_VALIDATE = join(root, "tools/codex-sandbox/codex-sandbox");
  try {
    let command: any;
    let startup: any;
    sessionHandoff({
      registerCommand: (_name: string, options: any) => { command = options.handler; },
      on: (_name: string, handler: any) => { startup = handler; },
    } as any);
    const events: string[] = [];
    const ctx = {
      cwd: root,
      abort: () => events.push("abort"),
      waitForIdle: async () => { events.push("idle"); },
      shutdown: () => events.push("shutdown"),
      sessionManager: { getSessionFile: () => session, getCwd: () => root },
      ui: { notify: (message: string) => events.push(`error:${message}`) },
    };

    await command("/private/tmp", ctx);
    expect(events.some((event) => event === "shutdown")).toBe(false);
    await command(".", ctx);
    expect(events).toEqual([expect.stringMatching(/^error:/), "abort", "idle", "shutdown"]);
    expect(JSON.parse(readFileSync(request, "utf8"))).toEqual({ destination: root, session });

    rmSync(session);
    rmSync(request);
    events.length = 0;
    await command(".", {
      ...ctx,
      sessionManager: { ...ctx.sessionManager, getEntries: () => [
        { type: "session" }, { type: "session_info" },
      ] },
    });
    expect(events).toEqual(["abort", "idle", "shutdown"]);
    expect(JSON.parse(readFileSync(request, "utf8"))).toEqual({ destination: root, session: null });

    rmSync(request);
    events.length = 0;
    await command(".", {
      ...ctx,
      sessionManager: { ...ctx.sessionManager, getEntries: () => [
        { type: "session" }, { type: "message" },
      ] },
    });
    expect(events).toEqual(["abort", "idle", expect.stringMatching(/^error:/)]);

    writeFileSync(session, "saved session");
    startup({ reason: "startup" }, {
      ...ctx,
      sessionManager: { getSessionFile: () => session, getCwd: () => "/private/tmp" },
    });
    expect(JSON.parse(readFileSync(request, "utf8"))).toEqual({
      destination: process.cwd(), session,
    });
  } finally {
    if (previousRequest === undefined) delete process.env.CODEX_SANDBOX_CD_REQUEST;
    else process.env.CODEX_SANDBOX_CD_REQUEST = previousRequest;
    if (previousValidator === undefined) delete process.env.CODEX_SANDBOX_CD_VALIDATE;
    else process.env.CODEX_SANDBOX_CD_VALIDATE = previousValidator;
    rmSync(directory, { recursive: true, force: true });
  }
});
