import { readFileSync, readdirSync } from "node:fs";
import { buildContextEntries, convertToLlm, parseSessionEntries, sessionEntryToContextMessages } from "@earendil-works/pi-coding-agent";
import { describe, expect, test } from "bun:test";
import parentCompaction from "../../config/pi-agent/pi-extensions/luna-compaction";
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
      if (name === "session_before_compact") handler = callback;
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
      async complete(model: any, context: any, options: any) {
        requests.push({ model, context, options });
        return response();
      },
    },
    ui: { notify: (...args: any[]) => notifications.push(args) },
  };
  // These unit cases own checkpoint validation/capture, not SDK projection.
  // native_parent_compaction.mjs exercises the actual request and installation path.
  const projection = () => {
    const older = [
      ...(event.preparation.previousSummary ? [{ role: "user", content: event.preparation.previousSummary, timestamp: 1 }] : []),
      ...event.preparation.messagesToSummarize, ...event.preparation.turnPrefixMessages,
    ];
    const entries = older.map((msg, index) => ({ sourceEntry: { id: `old-${index}` }, messages: [msg] }));
    entries.push({ sourceEntry: { id: event.preparation.firstKeptEntryId }, messages: [message("Retained user message")] });
    return { entries, messages: entries.flatMap(entry => entry.messages) };
  };
  ctx.sessionManager.buildSessionProjection = projection;
  parentCompaction(pi, {
    async prepare() {
      const source = ctx.sessionManager.buildSessionProjection();
      return { model: ctx.model, context: { messages: convertToLlm(source.messages) }, options: {},
        current: source.messages, projection: source, prefixOffset: 0, mode: "rebuilt" };
    },
    async complete(_ctx: any, request: any, task: string, signal: AbortSignal) {
      signal.throwIfAborted();
      if (!request.model) throw new Error("No active parent model is available");
      return ctx.modelRegistry.complete(request.model, { ...request.context,
        messages: [...request.context.messages, message(task)] }, { signal });
    },
  } as any);
  return { pi, ctx, event, requests, executions, notifications, signal, run: () => handler(event, ctx) };
}

function capturedContext(summary: string) {
  return JSON.parse(summary.slice(summary.lastIndexOf("\n\n{") + 2));
}

function snapshot(summary: string) {
  return capturedContext(summary).repository;
}

describe("Parent compaction capture", () => {
  test("uses the moved instructions for one reconciled history and split-turn call, then captures status", async () => {
    const h = harness();
    h.event.preparation.fileOps.read.add("source.py");
    h.event.preparation.fileOps.edited.add("pending.py");
    const result = (await h.run()).compaction;
    expect(h.requests).toHaveLength(1);
    expect(h.requests[0].model.id).toBe("active");
    expect(h.requests[0].context.messages.at(-1).content[0].text).toContain(readFileSync(COMPACTION_INSTRUCTIONS, "utf8"));
    const prompt = h.requests[0].context.messages.at(-1).content[0].text;
    const transcript = JSON.stringify(h.requests[0].context.messages.slice(0, -1));
    expect(transcript).toContain("Earlier checkpoint");
    expect(transcript.indexOf("Earlier history")).toBeLessThan(transcript.indexOf("Latest split-turn prefix"));
    expect(prompt).toContain(h.event.customInstructions);
    expect(prompt).not.toContain("Working copy changes:");
    expect(h.requests[0].options.signal).toBe(h.event.signal);
    expect(h.executions).toHaveLength(1);
    expect(h.executions[0]).toMatchObject({ command: "jj", args: ["status", "--no-pager", "--color=never"], afterRequests: 1, options: { cwd: h.ctx.cwd, signal: h.event.signal } });
    expect(snapshot(result.summary)).toMatchObject({ cwd: h.ctx.cwd, state: "observed", code: 0, stdout: "Working copy changes:\nM pending.py\n" });
    expect(Number.isNaN(Date.parse(snapshot(result.summary).capturedAt))).toBe(false);
    expect(result).toMatchObject({ firstKeptEntryId: "retained-entry", tokensBefore: 12345, usage });
    expect(result.details).toMatchObject({ readFiles: ["source.py"], modifiedFiles: ["pending.py"], checkpointLength: response().content[0].text.length });
    expect(result.summary).not.toContain("Turn Context (split turn)");
  });

  test("the next compaction preserves the prior parent prefix including its injected capture", async () => {
    const h = harness();
    const first = (await h.run()).compaction;
    h.event.preparation.previousSummary = first.summary;
    h.event.branchEntries = [{ type: "compaction", summary: first.summary, details: first.details }];
    await h.run();
    const transcript = JSON.stringify(h.requests[1].context.messages.slice(0, -1));
    expect(transcript).toContain("Continue the approved task 🐟");
    expect(transcript).toContain("pending.py");
    expect(transcript).toContain("capturedAt");
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
    expect(h.requests[0].context.messages).toEqual(control.requests[0].context.messages);
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
    expect(control.requests[0].context.messages.at(-1).content[0].text).not.toContain(paths[0]);
  });

  test("all retention fixtures preserve the full original prefix and boundary while adding caller-only pointers", async () => {
    const directory = new URL("./fixtures/compaction-replay/", import.meta.url);
    let checked = 0;
    for (const name of readdirSync(directory).filter(name => name.endsWith(".jsonl"))) {
      const source = readFileSync(new URL(name, directory), "utf8");
      const entries = parseSessionEntries(source).filter(entry => entry.type !== "session");
      for (const cut of listCuts(source)) {
        const { original } = replayInput(source, cut.id);
        const context = buildContextEntries(entries, original.parentId);
        const boundary = context.findIndex(entry => entry.id === original.firstKeptEntryId);
        const previous = context[0]?.type === "compaction" ? context[0] : undefined;
        const h = harness();
        h.event.preparation.messagesToSummarize = context.slice(previous ? 1 : 0, boundary).flatMap(sessionEntryToContextMessages);
        h.event.preparation.turnPrefixMessages = [];
        h.event.preparation.previousSummary = previous?.summary;
        h.event.branchEntries = context;
        h.event.customInstructions = undefined;
        h.event.preparation.firstKeptEntryId = original.firstKeptEntryId;
        const projected = context.map(entry => ({ sourceEntry: entry, messages: sessionEntryToContextMessages(entry) }));
        h.ctx.sessionManager.buildSessionProjection = () => ({ entries: projected, messages: projected.flatMap(entry => entry.messages) });
        h.event.preparation.fileOps.written.add("caller-only/recovery-pointer.ts");
        const result = (await h.run()).compaction;
        expect(h.requests[0].context.messages.slice(0, -1)).toEqual(convertToLlm(context.flatMap(sessionEntryToContextMessages)));
        expect(h.requests[0].context.messages.at(-1).content[0].text).toContain(readFileSync(COMPACTION_INSTRUCTIONS, "utf8"));
        expect(result.details.modifiedFiles).toContain("caller-only/recovery-pointer.ts");
        expect(capturedContext(result.summary).recordedEditWriteTargets).toBe(result.details.modifiedFiles.length);
        expect(result.summary).not.toContain("caller-only/recovery-pointer.ts");
        expect(result.summary.slice(0, result.details.checkpointLength)).toBe(response().content[0].text);
        checked++;
      }
    }
    expect(checked).toBeGreaterThanOrEqual(9);
  });

  test("carries recorded targets through repeated hook compactions without duplicating footers in new tasks", async () => {
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
      const request = h.requests[index + 1].context.messages.at(-1).content[0].text;
      expect(request).not.toContain("caller-preserved");
      expect(request).not.toContain("recordedEditWriteTargets");
      expect(request).not.toContain(result.details.captureId);
      const controlResult = (await control.run()).compaction;
      expect(h.requests[index + 1].context.messages.at(-1).content).toEqual(control.requests[index].context.messages.at(-1).content);
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

  test("repeated compaction keeps newly captured status compact and does not duplicate it in appended task", async () => {
    const h = harness();
    const stdout = "Working copy changes:\n" + "A dependency/file.py\n".repeat(70000) + "Parent commit: complete tail\n";
    h.pi.exec = async () => ({ stdout, stderr: "", code: 0, killed: false });
    for (let index = 0; index < 7; index++) {
      const result = (await h.run()).compaction;
      expect(result.summary.length).toBeLessThan(3000);
      expect(result.details.repositoryState.stdout).toBe(stdout);
      const prompt = h.requests[index].context.messages.at(-1).content[0].text;
      expect(prompt.length).toBeLessThan(readFileSync(COMPACTION_INSTRUCTIONS, "utf8").length + 2000);
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

  test("uses only the active parent model", async () => {
    const h = harness();
    const result = (await h.run()).compaction;
    expect(h.requests.map(request => request.model.id)).toEqual(["active"]);
    expect(snapshot(result.summary).state).toBe("observed");
  });

  test("a failed parent request cancels without changing model or launching status", async () => {
    const h = harness();
    const complete = h.ctx.modelRegistry.complete;
    h.ctx.modelRegistry.complete = async (...args: any[]) => ({ ...await complete(...args), stopReason: "error", errorMessage: "Parent unavailable" });
    expect(await h.run()).toEqual({ cancel: true });
    expect(h.requests.map(request => request.model.id)).toEqual(["active"]);
    expect(h.executions).toHaveLength(0);
    expect(h.notifications[0][0]).toContain("keeping session history");
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
    h.ctx.modelRegistry.complete = async () => invalid;
    expect(await h.run()).toEqual({ cancel: true });
    expect(h.executions).toHaveLength(0);
    expect(h.notifications[0][0]).toContain("keeping session history");
  });

  // Installed symlink loading, consumer installation and saved recovery pointers
  // run against the actual SDK in native_parent_compaction.mjs.

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
