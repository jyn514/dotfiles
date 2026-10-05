import { expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import sessionHandoff from "../../../config/pi-agent/pi-extensions/session-handoff.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

test("/cd validates before stopping Pi and records a saved-session handoff", async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "pi-session-handoff-")));
  const request = join(directory, "request.json");
  const session = join(directory, "session.jsonl");
  const home = join(directory, "home");
  const workspace = join(home, "src", "workspace");
  const invalid = join(directory, "not-a-workspace");
  const validator = join(directory, "validate-cd");
  const validatorFixture = join(root, "tools/codex-sandbox/tests/fixtures/session_handoff_validator.py");
  const previousCwd = process.cwd();
  const previousRequest = process.env.CODEX_SANDBOX_CD_REQUEST;
  const previousValidator = process.env.CODEX_SANDBOX_CD_VALIDATE;
  process.env.CODEX_SANDBOX_CD_REQUEST = request;
  process.env.CODEX_SANDBOX_CD_VALIDATE = validator;
  try {
    // The real validator maps HOME/src/workspace to /src/workspace. Own both
    // ends of that boundary rather than relying on a developer's HOME/src or
    // the checkout's writable Jujutsu metadata.
    mkdirSync(workspace, { recursive: true });
    mkdirSync(invalid);
    execFileSync(process.env.DOTFILES_TEST_JJ_REAL || "jj", ["git", "init", "--colocate", workspace], {
      cwd: directory, env: { ...process.env, HOME: home }, stdio: "pipe",
    });
    // Bun's default execFileSync environment does not observe process.env
    // mutations. Set HOME at the executable boundary, then exec the real
    // validator; do not replace its validation or destination with a stub.
    symlinkSync(validatorFixture, validator);
    process.chdir(workspace);
    writeFileSync(session, "saved session");
    let command: any;
    let startup: any;
    sessionHandoff({
      registerCommand: (_name: string, options: any) => { command = options.handler; },
      on: (_name: string, handler: any) => { startup = handler; },
    } as any);
    const events: string[] = [];
    const ctx = {
      cwd: workspace,
      abort: () => events.push("abort"),
      waitForIdle: async () => { events.push("idle"); },
      shutdown: () => events.push("shutdown"),
      sessionManager: { getSessionFile: () => session, getCwd: () => workspace },
      ui: { notify: (message: string) => events.push(`error:${message}`) },
    };

    await command(invalid, ctx);
    expect(events).toEqual([expect.stringMatching(/^error:/)]);
    expect(existsSync(request)).toBe(false);
    expect(existsSync(join(invalid, ".jj"))).toBe(false);
    await command(".", ctx);
    expect(events).toEqual([expect.stringMatching(/^error:/), "abort", "idle", "shutdown"]);
    expect(JSON.parse(readFileSync(request, "utf8"))).toEqual({ destination: workspace, session });

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
    expect(JSON.parse(readFileSync(request, "utf8"))).toEqual({ destination: workspace, session: null });

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
      sessionManager: { getSessionFile: () => session, getCwd: () => invalid },
    });
    expect(JSON.parse(readFileSync(request, "utf8"))).toEqual({
      destination: workspace, session,
    });
  } finally {
    process.chdir(previousCwd);
    if (previousRequest === undefined) delete process.env.CODEX_SANDBOX_CD_REQUEST;
    else process.env.CODEX_SANDBOX_CD_REQUEST = previousRequest;
    if (previousValidator === undefined) delete process.env.CODEX_SANDBOX_CD_VALIDATE;
    else process.env.CODEX_SANDBOX_CD_VALIDATE = previousValidator;
    rmSync(directory, { recursive: true, force: true });
  }
});
