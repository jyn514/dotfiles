import { expect, test } from "bun:test";
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import sessionHandoff from "../../../config/pi-agent/pi-extensions/session-handoff.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

test("native Pi keeps the conversation usable after /cd image preparation fails", () => {
  const environment = { ...process.env };
  delete environment.PI_PACKAGE_DIR;
  const result = spawnSync("node", [join(root, "tools/codex-sandbox/tests/fixtures/session_handoff_native.mjs")], {
    encoding: "utf8", timeout: 30_000, env: environment,
  });
  if (result.status !== 0) throw new Error(`${result.stdout}\n${result.stderr}\n${result.error ?? ""}`);
  expect(result.stdout).toContain("accepts another turn");
}, 35_000);

test("/cd prepares images before stopping Pi and preserves the session on build failure", async () => {
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
    const events: string[] = [];
    const success = { code: 0, killed: false,
      stdout: `build output\n${JSON.stringify({ destination: workspace, repository: workspace })}\n`, stderr: "" };
    let preparation: Promise<any> = Promise.resolve(success);
    sessionHandoff({
      registerCommand: (_name: string, options: any) => { command = options.handler; },
      on: (_name: string, handler: any) => { startup = handler; },
      exec: async (program: string, args: string[], options: any) => {
        expect(program).toBe(validator);
        expect(args).toEqual(["prepare-cd", workspace]);
        expect(options.cwd).toBe(workspace);
        events.push("prepare");
        return await preparation;
      },
    } as any);
    const ctx = {
      cwd: workspace,
      abort: () => events.push("abort"),
      waitForIdle: async () => { events.push("idle"); },
      shutdown: () => events.push("shutdown"),
      sessionManager: { getSessionFile: () => session, getCwd: () => workspace },
      ui: { notify: (message: string, level: string) => {
        if (level === "error") events.push(`error:${message}`);
      } },
    };

    await command(invalid, ctx);
    expect(events).toEqual([expect.stringMatching(/^error:/)]);
    expect(existsSync(request)).toBe(false);
    expect(existsSync(join(invalid, ".jj"))).toBe(false);
    events.length = 0;
    preparation = Promise.resolve({ code: 1, killed: false, stdout: "", stderr: "Cannot find module './identity.js'" });
    await command(".", ctx);
    expect(events).toEqual(["prepare", "error:Cannot find module './identity.js'"]);
    expect(existsSync(request)).toBe(false);
    expect(readFileSync(session, "utf8")).toBe("saved session");

    for (const result of [
      { code: 1, killed: false, stdout: "", stderr: "TicGit bundle resolution failed: compiler failed" },
      { code: 130, killed: false, stdout: "", stderr: "TicGit build interrupted: KeyboardInterrupt" },
      { ...success, killed: true },
      { code: 0, killed: false, stdout: "TicGit build started\n", stderr: "" },
      { code: 0, killed: false, stdout: "{broken completion\n", stderr: "" },
    ]) {
      events.length = 0;
      preparation = Promise.resolve(result);
      await command(".", ctx);
      expect(events).toEqual(["prepare", expect.stringMatching(/^error:/)]);
      expect(existsSync(request)).toBe(false);
      expect(readFileSync(session, "utf8")).toBe("saved session");
    }
    events.length = 0;
    // Exec can reject too (for example an interrupted preparation invocation).
    // Reject inside the exec await, rather than creating an unhandled promise.
    preparation = { then: (_resolve: any, reject: any) => reject(new Error("TicGit preparation cancelled")) } as any;
    await command(".", ctx);
    expect(events).toEqual(["prepare", "error:TicGit preparation cancelled"]);
    expect(existsSync(request)).toBe(false);

    events.length = 0;
    let completeBuild: (result: any) => void;
    preparation = new Promise((resolve) => { completeBuild = resolve; });
    const pending = command(".", ctx);
    expect(events).toEqual(["prepare"]);
    expect(existsSync(request)).toBe(false);
    completeBuild!(success);
    await pending;
    expect(events).toEqual(["prepare", "abort", "idle", "shutdown"]);
    expect(JSON.parse(readFileSync(request, "utf8"))).toEqual({ destination: workspace, session });
    preparation = Promise.resolve(success);

    rmSync(session);
    rmSync(request);
    events.length = 0;
    await command(".", {
      ...ctx,
      sessionManager: { ...ctx.sessionManager, getEntries: () => [
        { type: "session" }, { type: "session_info" },
      ] },
    });
    expect(events).toEqual(["prepare", "abort", "idle", "shutdown"]);
    expect(JSON.parse(readFileSync(request, "utf8"))).toEqual({ destination: workspace, session: null });

    rmSync(request);
    events.length = 0;
    await command(".", {
      ...ctx,
      sessionManager: { ...ctx.sessionManager, getEntries: () => [
        { type: "session" }, { type: "message" },
      ] },
    });
    expect(events).toEqual(["prepare", "abort", "idle", expect.stringMatching(/^error:/)]);

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
