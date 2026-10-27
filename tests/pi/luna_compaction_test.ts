import { chmodSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { buildContextEntries, discoverAndLoadExtensions, ModelRegistry, parseSessionEntries, sessionEntryToContextMessages, SessionManager } from "@earendil-works/pi-coding-agent";
import { describe, expect, test } from "bun:test";
import lunaCompaction, { COMPACTION_MODEL } from "../../config/pi-agent/pi-extensions/luna-compaction";
import { COMPACTION_INSTRUCTIONS } from "../../config/pi-agent/pi-extensions/checkpoint-capture";
import { listCuts, replayInput } from "../../dev/replay-compaction";

const usage = { input: 12, output: 8, cacheRead: 0, cacheWrite: 0, totalTokens: 20, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const message = (text: string) => ({ role: "user", content: [{ type: "text", text }], timestamp: 1 });
const response = (text = "## Objective and authority\nContinue the approved task 🐟") => ({ role: "assistant", content: [{ type: "text", text }], stopReason: "stop", usage });

function harness() {
  let handler: any;
  const requests: any[] = [];
  const executions: any[] = [];
  const notifications: any[] = [];
  const signal = new AbortController();
  const luna = { ...COMPACTION_MODEL, api: "openai-codex-responses", maxTokens: 8192 };
  const active = { provider: "openai-codex", id: "active", api: "openai-codex-responses", maxTokens: 8192 };
  const event: any = {
    preparation: {
      messagesToSummarize: [message("Earlier history")],
      turnPrefixMessages: [message("Latest split-turn prefix")],
      isSplitTurn: true,
      previousSummary: "Earlier checkpoint",
      tokensBefore: 12345,
      firstKeptEntryId: "retained-entry",
      fileOps: { read: new Set<string>(), written: new Set<string>(), edited: new Set<string>() },
      settings: { reserveTokens: 16384 },
    },
    branchEntries: [],
    customInstructions: "Preserve the named blocker",
    signal: signal.signal,
  };
  const pi: any = {
    on(name: string, callback: any) {
      expect(name).toBe("session_before_compact");
      handler = callback;
    },
    async exec(command: string, args: string[], options: any) {
      executions.push({ command, args, options, afterRequests: requests.length });
      return { stdout: "Working copy changes:\nM pending.py\n", stderr: "", code: 0, killed: false };
    },
  };
  const ctx: any = {
    cwd: "/owned/project with spaces",
    model: active,
    sessionManager: {
      getSessionId: () => "0537ee54-642f-4ce4-a67b-ff9b06b39104",
      getSessionFile: () => "/owned/sessions/current.jsonl",
    },
    modelRegistry: {
      find: () => luna,
      async complete(model: any, context: any, options: any) {
        requests.push({ model, context, options });
        return response();
      },
    },
    ui: { notify: (...args: any[]) => notifications.push(args) },
  };
  lunaCompaction(pi);
  return { pi, ctx, event, requests, executions, notifications, signal, run: () => handler(event, ctx) };
}

function capturedContext(summary: string) {
  return JSON.parse(summary.slice(summary.lastIndexOf("\n\n{") + 2));
}

function snapshot(summary: string) {
  return capturedContext(summary).repository;
}

describe("Luna compaction", () => {
  test("uses the moved instructions for one reconciled history and split-turn call, then captures status", async () => {
    const h = harness();
    h.event.preparation.fileOps.read.add("source.py");
    h.event.preparation.fileOps.edited.add("pending.py");
    const result = (await h.run()).compaction;
    expect(h.requests).toHaveLength(1);
    expect(h.requests[0].model.id).toBe(COMPACTION_MODEL.id);
    expect(h.requests[0].context.systemPrompt).toBe(readFileSync(COMPACTION_INSTRUCTIONS, "utf8"));
    const prompt = h.requests[0].context.messages[0].content[0].text;
    expect(prompt).toContain("Earlier checkpoint");
    expect(prompt.indexOf("Earlier history")).toBeLessThan(prompt.indexOf("Latest split-turn prefix"));
    expect(prompt).toContain(h.event.customInstructions);
    expect(prompt).not.toContain("Working copy changes:");
    expect(h.requests[0].options).toMatchObject({ signal: h.event.signal, cacheRetention: "none", reasoningEffort: "low", maxTokens: 8192 });
    expect(h.requests[0].options.sessionId).toBeTruthy();
    expect(h.executions).toHaveLength(1);
    expect(h.executions[0]).toMatchObject({ command: "jj", args: ["status", "--no-pager", "--color=never"], afterRequests: 1, options: { cwd: h.ctx.cwd, signal: h.event.signal } });
    expect(snapshot(result.summary)).toMatchObject({ cwd: h.ctx.cwd, state: "observed", code: 0, stdout: "Working copy changes:\nM pending.py\n" });
    expect(Number.isNaN(Date.parse(snapshot(result.summary).capturedAt))).toBe(false);
    expect(result).toMatchObject({ firstKeptEntryId: "retained-entry", tokensBefore: 12345, usage });
    expect(result.details).toMatchObject({ readFiles: ["source.py"], modifiedFiles: ["pending.py"], checkpointLength: response().content[0].text.length });
    expect(result.summary).not.toContain("Turn Context (split turn)");
  });

  test("the next compaction receives the checkpoint but not its injected repository snapshot", async () => {
    const h = harness();
    const first = (await h.run()).compaction;
    h.event.preparation.previousSummary = first.summary;
    h.event.branchEntries = [{ type: "compaction", summary: first.summary, details: first.details }];
    await h.run();
    const prompt = h.requests[1].context.messages[0].content[0].text;
    expect(prompt).toContain(response().content[0].text);
    expect(prompt).not.toContain("caller-captured");
    expect(prompt).not.toContain("pending.py");
    expect(prompt).not.toContain("capturedAt");
    expect(h.requests[1].options.sessionId).not.toBe(h.requests[0].options.sessionId);
  });

  test("preserves edit/write recovery pointers even when prose and status omit them, without changing generation", async () => {
    const control = harness();
    await control.run();
    const h = harness();
    const paths = [
      "tools/codex-sandbox/README.md",
      "tools/codex-sandbox/spec/proxy-design.typ",
      "tools/codex-sandbox/tests/repository_mounts_integration.py",
    ];
    for (const path of paths) h.event.preparation.fileOps.edited.add(path);
    h.event.preparation.fileOps.written.add(paths[0]);
    h.event.preparation.fileOps.read.add("read-only.py");
    h.pi.exec = async () => ({ stdout: "M observed-not-edited.py", stderr: "", code: 0, killed: false });
    const result = (await h.run()).compaction;
    expect(h.requests[0].context.systemPrompt).toBe(control.requests[0].context.systemPrompt);
    expect(h.requests[0].context.messages[0].content).toEqual(control.requests[0].context.messages[0].content);
    expect(result.summary.slice(0, result.details.checkpointLength)).toBe(response().content[0].text);
    for (const path of paths) expect(result.summary).not.toContain(JSON.stringify(path));
    expect(capturedContext(result.summary)).toMatchObject({
      recordedEditWriteTargets: paths.length,
      recovery: {
        sessionId: h.ctx.sessionManager.getSessionId(),
        sessionFile: h.ctx.sessionManager.getSessionFile(),
        captureId: result.details.captureId,
      },
    });
    expect(result.details.modifiedFiles).toEqual(paths);
    expect(control.requests[0].context.messages[0].content[0].text).not.toContain(paths[0]);
  });

  test("all retention fixtures keep the replay generation payload unchanged while adding caller-only pointers", async () => {
    const directory = new URL("./fixtures/compaction-replay/", import.meta.url);
    let checked = 0;
    for (const name of readdirSync(directory).filter(name => name.endsWith(".jsonl"))) {
      const source = readFileSync(new URL(name, directory), "utf8");
      const entries = parseSessionEntries(source).filter(entry => entry.type !== "session");
      for (const cut of listCuts(source)) {
        const { original, prompt } = replayInput(source, cut.id);
        const context = buildContextEntries(entries, original.parentId);
        const boundary = context.findIndex(entry => entry.id === original.firstKeptEntryId);
        const previous = context[0]?.type === "compaction" ? context[0] : undefined;
        const h = harness();
        h.event.preparation.messagesToSummarize = context.slice(previous ? 1 : 0, boundary).flatMap(sessionEntryToContextMessages);
        h.event.preparation.turnPrefixMessages = [];
        h.event.preparation.previousSummary = previous?.summary;
        h.event.branchEntries = context;
        h.event.customInstructions = undefined;
        h.event.preparation.fileOps.written.add("caller-only/recovery-pointer.ts");
        const result = (await h.run()).compaction;
        expect(h.requests[0].context.messages[0].content[0].text).toBe(prompt);
        expect(h.requests[0].context.systemPrompt).toBe(readFileSync(COMPACTION_INSTRUCTIONS, "utf8"));
        expect(result.details.modifiedFiles).toContain("caller-only/recovery-pointer.ts");
        expect(capturedContext(result.summary).recordedEditWriteTargets).toBe(result.details.modifiedFiles.length);
        expect(result.summary).not.toContain("caller-only/recovery-pointer.ts");
        expect(result.summary.slice(0, result.details.checkpointLength)).toBe(response().content[0].text);
        checked++;
      }
    }
    expect(checked).toBeGreaterThanOrEqual(9);
  });

  test("carries recorded targets through repeated hook compactions without feeding footers back to the model", async () => {
    const h = harness();
    const baseline = (await h.run()).compaction;
    const control = harness();
    expect(capturedContext(baseline.summary).recordedEditWriteTargets).toBe(0);
    const paths = ["--leading-option", 'quoted/"name".md', "line\nbreak.py", "λ/🐟.ts", "case.py", "CASE.py"];
    // Seed 17; bounded generated path strings plus forced escaping/identity cases.
    let seed = 17;
    for (let i = 0; i < 24; i++) {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      paths.push(`generated/${seed.toString(16)}/${i}.md`);
    }
    const seen: string[] = [];
    for (const [index, path] of paths.entries()) {
      h.event.preparation.fileOps = { edited: new Set([path]), written: new Set([path]), read: new Set([path, "only-read.py"]) };
      seen.push(path);
      const result = (await h.run()).compaction;
      expect(capturedContext(result.summary).recordedEditWriteTargets).toBe(seen.length);
      expect(result.details.modifiedFiles).toEqual([...seen].sort());
      for (const path of seen) expect(result.summary).not.toContain(JSON.stringify(path));
      expect(result.details.readFiles).toEqual(["only-read.py"]);
      expect(result.summary.match(/## Captured context/g)).toHaveLength(1);
      const request = h.requests[index + 1].context.messages[0].content[0].text;
      expect(request).not.toContain("caller-preserved");
      expect(request).not.toContain("recordedEditWriteTargets");
      expect(request).not.toContain(result.details.captureId);
      const controlResult = (await control.run()).compaction;
      expect(h.requests[index + 1].context.messages[0].content).toEqual(control.requests[index].context.messages[0].content);
      control.event.preparation.previousSummary = controlResult.summary;
      control.event.branchEntries = [{ type: "compaction", summary: controlResult.summary, details: controlResult.details, fromHook: true }];
      h.event.preparation.previousSummary = result.summary;
      h.event.branchEntries = [{ type: "compaction", summary: result.summary, details: result.details, fromHook: true }];
    }
    h.event.preparation.fileOps = { edited: new Set(), written: new Set(), read: new Set() };
    const repeated = (await h.run()).compaction;
    expect(capturedContext(repeated.summary).recordedEditWriteTargets).toBe(seen.length);
    expect(repeated.details.modifiedFiles).toEqual([...seen].sort());
  });

  test.each([true, false])("inherits only the active matching checkpoint's targets: match=%s", async (matching) => {
    const h = harness();
    h.event.branchEntries = [{ type: "compaction", summary: matching ? h.event.preparation.previousSummary : "another branch", details: { modifiedFiles: ["earlier.py", null, 42] } }];
    h.event.preparation.fileOps.written.add("current.py");
    const result = (await h.run()).compaction;
    const expected = matching ? ["current.py", "earlier.py"] : ["current.py"];
    expect(result.details.modifiedFiles).toEqual(expected);
    expect(capturedContext(result.summary).recordedEditWriteTargets).toBe(expected.length);
  });

  test.each([undefined, null, "not an array", { path: "not-a-list.py" }])("malformed legacy target metadata does not invent paths: %j", async (modifiedFiles) => {
    const h = harness();
    h.event.branchEntries = [{ type: "compaction", summary: h.event.preparation.previousSummary, details: { modifiedFiles } }];
    const result = (await h.run()).compaction;
    expect(result.details.modifiedFiles).toEqual([]);
    expect(capturedContext(result.summary).recordedEditWriteTargets).toBe(0);
  });

  test.each(["many", "oversized-first-path"])('visible context does not grow with the target inventory; keeps the full list across compactions: %s', async (mode) => {
    const h = harness();
    const paths = mode === "many"
      ? Array.from({ length: 1500 }, (_, index) => `docs/${String(index).padStart(4, "0")}/\"quoted\"-λ.md`)
      : ["a" + "\u0000".repeat(10000), "z/short.md"];
    for (const path of paths) h.event.preparation.fileOps.edited.add(path);
    for (let index = 0; index < 3; index++) {
      const result = (await h.run()).compaction;
      const visible = capturedContext(result.summary);
      expect(result.summary.length).toBeLessThan(3000);
      expect(visible.recordedEditWriteTargets).toBe(paths.length);
      for (const path of paths) expect(result.summary).not.toContain(JSON.stringify(path));
      expect(result.details.modifiedFiles).toEqual(paths);
      h.event.preparation.previousSummary = result.summary;
      h.event.branchEntries = [{ type: "compaction", summary: result.summary, details: result.details, fromHook: true }];
      h.event.preparation.fileOps = { edited: new Set(), written: new Set(), read: new Set() };
    }
  });

  test("in-memory captures do not invent a saved session file", async () => {
    const h = harness();
    h.ctx.sessionManager.getSessionFile = () => undefined;
    const result = (await h.run()).compaction;
    expect(capturedContext(result.summary).recovery).toEqual({
      sessionId: h.ctx.sessionManager.getSessionId(), sessionFile: null, captureId: result.details.captureId,
    });
    expect(result.details.repositoryState.state).toBe("observed");
  });

  test("normal turns use the same instructions and preserve the retained boundary", async () => {
    const h = harness();
    h.event.preparation.turnPrefixMessages = [];
    h.event.preparation.isSplitTurn = false;
    h.event.preparation.previousSummary = undefined;
    const result = (await h.run()).compaction;
    expect(h.requests).toHaveLength(1);
    expect(h.requests[0].context.messages[0].content[0].text).not.toContain("<previous-checkpoint>");
    expect(result.firstKeptEntryId).toBe("retained-entry");
  });

  test("bounds status in resumed context while retaining the complete capture in metadata", async () => {
    const h = harness();
    const stdout = "Working copy changes:\n" + "A dependency/file.py\n".repeat(70000) + "Parent commit: complete tail\n";
    const status = { stdout, stderr: "status diagnostic", code: 0, killed: false };
    h.pi.exec = async () => status;
    const result = (await h.run()).compaction;
    const captured = snapshot(result.summary);
    expect(JSON.stringify(captured, null, 2).length).toBeLessThan(2048);
    expect(captured).toMatchObject({ state: "observed", stderr: "status diagnostic", code: 0, killed: false, truncated: true });
    expect(captured.stdout).toStartWith("Working copy changes:\n");
    expect(captured.stdout).toEndWith("Parent commit: complete tail\n");
    expect(captured.stdout).toContain("characters omitted");
    expect(capturedContext(result.summary).recovery.captureId).toBe(result.details.captureId);
    expect(result.details.repositoryState).toMatchObject(status);
  });

  test("bounds serialized stdout and stderr even when JSON escaping expands them", async () => {
    const h = harness();
    const status = { stdout: "\u0000".repeat(10000), stderr: "\u0001".repeat(10000), code: 1, killed: false };
    h.pi.exec = async () => status;
    const result = (await h.run()).compaction;
    expect(JSON.stringify(snapshot(result.summary), null, 2).length).toBeLessThan(2048);
    expect(snapshot(result.summary)).toMatchObject({ state: "unknown", code: 1, truncated: true });
    expect(result.details.repositoryState).toMatchObject(status);
  });

  test("repeated compaction never reinjects an oversized status into model input or resumed context", async () => {
    const h = harness();
    const stdout = "Working copy changes:\n" + "A dependency/file.py\n".repeat(70000) + "Parent commit: complete tail\n";
    h.pi.exec = async () => ({ stdout, stderr: "", code: 0, killed: false });
    for (let index = 0; index < 7; index++) {
      const result = (await h.run()).compaction;
      expect(result.summary.length).toBeLessThan(3000);
      expect(result.details.repositoryState.stdout).toBe(stdout);
      const prompt = h.requests[index].context.messages[0].content[0].text;
      expect(prompt.length).toBeLessThan(1000);
      expect(prompt).not.toContain("Parent commit:");
      expect(prompt).not.toContain("dependency/file.py");
      h.event.preparation.previousSummary = result.summary;
      h.event.branchEntries = [{ type: "compaction", summary: result.summary, details: result.details }];
    }
  });

  test("small status captures remain complete without an omission notice", async () => {
    const h = harness();
    const result = (await h.run()).compaction;
    expect(snapshot(result.summary)).toEqual(result.details.repositoryState);
    expect(snapshot(result.summary)).not.toHaveProperty("truncated");
  });

  test.each([
    { stdout: "partial output", stderr: "Not a jj repository", code: 1, killed: false },
    { stdout: "partial output", stderr: "", code: 0, killed: true },
  ])("failed or killed status capture remains unknown without discarding a valid checkpoint: %j", async (status) => {
    const h = harness();
    h.pi.exec = async () => status;
    h.event.preparation.fileOps.edited.add("recorded-before-status-failed.md");
    const result = (await h.run()).compaction;
    expect(result.summary).toContain(response().content[0].text);
    expect(snapshot(result.summary)).toMatchObject({ ...status, state: "unknown" });
    expect(result.details.modifiedFiles).toEqual(["recorded-before-status-failed.md"]);
    expect(capturedContext(result.summary).recordedEditWriteTargets).toBe(1);
  });

  test("status launch exceptions become explicit unknown state", async () => {
    const h = harness();
    h.pi.exec = async () => { throw new Error("jj could not start"); };
    expect(snapshot((await h.run()).compaction.summary)).toMatchObject({ state: "unknown", error: "jj could not start" });
  });

  test("unavailable Luna uses the active model with the same custom prompt and status capture", async () => {
    const h = harness();
    h.ctx.modelRegistry.find = () => undefined;
    const result = (await h.run()).compaction;
    expect(h.requests[0].model.id).toBe("active");
    expect(h.requests[0].context.systemPrompt).toBe(readFileSync(COMPACTION_INSTRUCTIONS, "utf8"));
    expect(snapshot(result.summary).state).toBe("observed");
  });

  test("a failed Luna request falls back without reverting to stock split-turn instructions", async () => {
    const h = harness();
    const complete = h.ctx.modelRegistry.complete;
    h.ctx.modelRegistry.complete = async (...args: any[]) => {
      const result = await complete(...args);
      return args[0].id === COMPACTION_MODEL.id ? { ...result, stopReason: "error", errorMessage: "Luna unavailable" } : result;
    };
    const result = (await h.run()).compaction;
    expect(h.requests.map((request) => request.model.id)).toEqual([COMPACTION_MODEL.id, "active"]);
    expect(h.requests[0].context.systemPrompt).toBe(h.requests[1].context.systemPrompt);
    expect(h.requests[0].context.messages[0].content).toEqual(h.requests[1].context.messages[0].content);
    expect(h.executions[0].afterRequests).toBe(2);
    expect(result.summary).toContain(response().content[0].text);
    expect(h.notifications[0][0]).toContain("using the active model");
  });

  test("a missing required header uses the existing active-model fallback", async () => {
    const h = harness();
    h.ctx.modelRegistry.complete = async (model: any, context: any, options: any) => {
      h.requests.push({ model, context, options });
      return response(model.id === COMPACTION_MODEL.id
        ? "I’ll narrow only the skill’s trigger wording; no workflow changes."
        : "## Objective and authority\nContinue the approved task");
    };
    const result = (await h.run()).compaction;
    expect(h.requests.map(request => request.model.id)).toEqual([COMPACTION_MODEL.id, "active"]);
    expect(h.requests[0].context.systemPrompt).toBe(h.requests[1].context.systemPrompt);
    expect(h.requests[0].context.messages[0].content).toEqual(h.requests[1].context.messages[0].content);
    expect(h.executions[0].afterRequests).toBe(2);
    expect(result.summary).toStartWith("## Objective and authority");
    expect(h.notifications[0][0]).toContain("missing the Objective and authority header");
  });

  test("checks only the header, not the meaning or style of checkpoint prose", async () => {
    const h = harness();
    const text = "Preface\n## Objective and authority\t\r\nI’ll narrow only the skill’s trigger wording; no workflow changes.";
    h.ctx.modelRegistry.complete = async () => response(text);
    expect((await h.run()).compaction.summary).toStartWith(text);
    expect(h.notifications).toHaveLength(0);
  });

  test.each(["#", "##", "###", "####", "#####", "######"])("accepts the required heading at Markdown level %s", async (heading) => {
    const h = harness();
    const text = `${heading} Objective and authority\nContinue the approved task`;
    h.ctx.modelRegistry.complete = async () => response(text);
    expect((await h.run()).compaction.summary).toStartWith(text);
  });

  test.each([
    { ...response(), content: [] },
    response("I’ll narrow only the skill’s trigger wording; no workflow changes."),
    response("The required heading is ## Objective and authority, but this is not a heading."),
    { ...response(), stopReason: "length" },
    { ...response(), content: [{ type: "toolCall", name: "bash", arguments: {} }] },
  ])("invalid summaries preserve history and never launch status: %j", async (invalid) => {
    const h = harness();
    h.ctx.model = undefined;
    h.ctx.modelRegistry.complete = async () => invalid;
    expect(await h.run()).toEqual({ cancel: true });
    expect(h.executions).toHaveLength(0);
    expect(h.notifications[0][0]).toContain("keeping session history");
  });

  test("native loader resolves installed symlinks, captures status, and preserves pointers through persisted context rebuilds", async () => {
    const root = mkdtempSync(join(tmpdir(), "pi compaction-"));
    const source = join(root, "checkout/config/pi-agent/pi-extensions/luna-compaction.ts");
    const policy = join(root, "checkout/config/pi-agent/pi-extensions/compaction.md");
    const installed = join(root, "agent/pi-extensions/luna-compaction.ts");
    const project = join(root, "project");
    const bin = join(root, "bin");
    const oldPath = process.env.PATH;
    try {
      for (const directory of [dirname(source), dirname(installed), project, bin]) mkdirSync(directory, { recursive: true });
      const original = resolve("config/pi-agent/pi-extensions/luna-compaction.ts");
      expect(Bun.spawnSync(["cp", original, source]).exitCode).toBe(0);
      expect(Bun.spawnSync(["cmp", original, source]).exitCode).toBe(0);
      const helper = resolve("config/pi-agent/pi-extensions/checkpoint-capture.ts");
      const copiedHelper = join(dirname(source), "checkpoint-capture.ts");
      expect(Bun.spawnSync(["cp", helper, copiedHelper]).exitCode).toBe(0);
      expect(Bun.spawnSync(["cmp", helper, copiedHelper]).exitCode).toBe(0);
      symlinkSync(source, installed);
      symlinkSync(copiedHelper, join(dirname(installed), "checkpoint-capture.ts"));
      const fixture = join(bin, "jj");
      expect(Bun.spawnSync(["cp", resolve("tests/pi/fixtures/jj-status.sh"), fixture]).exitCode).toBe(0);
      expect(Bun.spawnSync(["cmp", resolve("tests/pi/fixtures/jj-status.sh"), fixture]).exitCode).toBe(0);
      chmodSync(fixture, 0o755);
      process.env.PATH = `${bin}:${oldPath}`;
      writeFileSync(policy, "Preserve the approved goal and conditional permission.\n");
      const loaded = await discoverAndLoadExtensions([installed], project, join(root, "agent"));
      expect(loaded.errors).toEqual([]);
      expect(loaded.extensions).toHaveLength(1);
      const callbacks = loaded.extensions[0].handlers.get("session_before_compact")!;
      expect(callbacks).toHaveLength(1);
      const h = harness();
      h.ctx.cwd = project;
      h.event.preparation.fileOps.edited.add("native docs/README.md");
      const complete = h.ctx.modelRegistry.complete;
      const stdout = "Working copy changes:\n" + "M pending.py\n".repeat(100000) + "Complete final status row\n";
      h.ctx.modelRegistry = new ModelRegistry({
        getModel: () => ({ ...COMPACTION_MODEL, api: "openai-codex-responses", maxTokens: 8192 }),
        async complete(...args: any[]) {
          // A premature status capture fails: these files exist only after generation.
          writeFileSync(join(project, "jj-status.stdout"), stdout);
          writeFileSync(join(project, "jj-status.stderr"), "");
          writeFileSync(join(project, "jj-status.code"), "0");
          return complete(...args);
        },
      } as never);
      const sessions = SessionManager.create(project, join(root, "sessions"));
      h.ctx.sessionManager = sessions;
      // Pi flushes a new session after its first assistant message.
      sessions.appendMessage(response("Initial native fixture response") as never);
      sessions.appendMessage(message("Retained user message") as never);
      h.event.preparation.firstKeptEntryId = sessions.getLeafId();
      const result = (await callbacks[0](h.event, h.ctx) as any).compaction;
      expect(h.requests[0].context.systemPrompt).toBe(readFileSync(policy, "utf8"));
      const captured = snapshot(result.summary);
      expect(captured.state).toBe("observed");
      expect(captured.cwd).toBe(project);
      expect(captured.truncated).toBe(true);
      expect(captured.stdout).toStartWith("Working copy changes:\n");
      expect(captured.stdout).toEndWith("Complete final status row\n");
      expect(result.summary.length).toBeLessThan(3000);
      sessions.appendCompaction(result.summary, result.firstKeptEntryId, result.tokensBefore, result.details, true, result.usage);
      const restored = SessionManager.open(sessions.getSessionFile()!);
      const saved = restored.getEntries().find(entry => entry.type === "compaction");
      expect((saved?.details as any).repositoryState.stdout === stdout).toBe(true);
      const parent = restored.buildSessionContext().messages.find((message) => message.role === "compactionSummary");
      expect(parent).toMatchObject({ summary: result.summary });
      const recovery = capturedContext((parent as any).summary).recovery;
      expect(recovery).toMatchObject({ sessionId: restored.getSessionId(), sessionFile: restored.getSessionFile() });
      expect(capturedContext((parent as any).summary).recordedEditWriteTargets).toBe(1);
      // Use the documented raw-JSONL recovery route, not the model's prose or
      // read_session (which deliberately omits compaction records).
      const recover = (locator: typeof recovery) => {
        const result = Bun.spawnSync(["jq", "--arg", "capture", locator.captureId,
          'select(.type == "compaction" and .details.captureId == $capture) | .details', locator.sessionFile]);
        expect(result.exitCode).toBe(0);
        return JSON.parse(result.stdout.toString());
      };
      expect(recover(recovery)).toMatchObject({
        captureId: recovery.captureId, modifiedFiles: ["native docs/README.md"], repositoryState: { stdout },
      });
      expect(JSON.stringify(parent).length).toBeLessThan(3500);
      expect(restored.buildSessionContext().messages.at(-1)).toMatchObject({ role: "user", content: [{ type: "text", text: "Retained user message" }] });

      writeFileSync(policy, "Changed authoritative compaction instructions.\n");
      h.event.preparation.previousSummary = result.summary;
      h.event.branchEntries = restored.getBranch();
      h.event.preparation.fileOps = { edited: new Set(), written: new Set(), read: new Set() };
      const second = (await callbacks[0](h.event, h.ctx) as any).compaction;
      expect(h.requests[1].context.systemPrompt).toBe(readFileSync(policy, "utf8"));
      expect(h.requests[1].context.messages[0].content[0].text).not.toContain("Complete final status row");
      expect(h.requests[1].context.messages[0].content[0].text).not.toContain("native docs/README.md");
      restored.appendCompaction(second.summary, second.firstKeptEntryId, second.tokensBefore, second.details, true, second.usage);
      const reopened = SessionManager.open(restored.getSessionFile()!);
      const resumed = reopened.buildSessionContext().messages.find(message => message.role === "compactionSummary");
      const nextRecovery = capturedContext((resumed as any).summary).recovery;
      expect(nextRecovery.captureId).not.toBe(recovery.captureId);
      expect(recover(nextRecovery)).toMatchObject({
        captureId: nextRecovery.captureId, modifiedFiles: ["native docs/README.md"], repositoryState: { stdout },
      });
      // An older locator must still select its own capture after another save.
      expect(recover(recovery).captureId).toBe(recovery.captureId);
      expect(capturedContext((resumed as any).summary).recordedEditWriteTargets).toBe(1);
    } finally {
      if (oldPath === undefined) delete process.env.PATH;
      else process.env.PATH = oldPath;
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("cancellation during status capture discards the checkpoint without fallback", async () => {
    const h = harness();
    h.pi.exec = async () => {
      h.signal.abort();
      return { stdout: "partial status", stderr: "", code: 0, killed: true };
    };
    expect(await h.run()).toEqual({ cancel: true });
    expect(h.requests).toHaveLength(1);
    expect(h.notifications).toHaveLength(0);
  });

  test("cancellation after generation prevents status capture and fallback", async () => {
    const h = harness();
    h.ctx.modelRegistry.complete = async () => { h.signal.abort(); return response(); };
    expect(await h.run()).toEqual({ cancel: true });
    expect(h.executions).toHaveLength(0);
    expect(h.notifications).toHaveLength(0);
  });
});
