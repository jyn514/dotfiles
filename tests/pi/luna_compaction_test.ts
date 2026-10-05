import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { discoverAndLoadExtensions, ModelRegistry, SessionManager } from "@earendil-works/pi-coding-agent";
import { describe, expect, test } from "bun:test";
import lunaCompaction, { COMPACTION_INSTRUCTIONS, COMPACTION_MODEL } from "../../config/pi-agent/pi-extensions/luna-compaction";

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

function snapshot(summary: string) {
  return JSON.parse(summary.slice(summary.lastIndexOf("\n\n{") + 2));
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

  test("preserves full status output rather than the tool-result serialization limit", async () => {
    const h = harness();
    const stdout = "M file.py\n".repeat(1000) + "Parent commit: complete tail\n";
    h.pi.exec = async () => ({ stdout, stderr: "status diagnostic", code: 0, killed: false });
    expect(snapshot((await h.run()).compaction.summary)).toMatchObject({ stdout, stderr: "status diagnostic" });
  });

  test.each([
    { stdout: "partial output", stderr: "Not a jj repository", code: 1, killed: false },
    { stdout: "partial output", stderr: "", code: 0, killed: true },
  ])("failed or killed status capture remains unknown without discarding a valid checkpoint: %j", async (status) => {
    const h = harness();
    h.pi.exec = async () => status;
    const result = (await h.run()).compaction;
    expect(result.summary).toContain(response().content[0].text);
    expect(snapshot(result.summary)).toMatchObject({ ...status, state: "unknown" });
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

  test.each([
    { ...response(), content: [] },
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

  test("native loader resolves installed symlinks, executes status after generation, and rebuilds parent context", async () => {
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
      symlinkSync(source, installed);
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
      const complete = h.ctx.modelRegistry.complete;
      const stdout = "M pending.py\n".repeat(1000) + "Complete final status row\n";
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
      const sessions = SessionManager.inMemory(project);
      sessions.appendMessage(message("Retained user message") as never);
      h.event.preparation.firstKeptEntryId = sessions.getLeafId();
      const result = (await callbacks[0](h.event, h.ctx) as any).compaction;
      expect(h.requests[0].context.systemPrompt).toBe(readFileSync(policy, "utf8"));
      const captured = snapshot(result.summary);
      expect(captured.state).toBe("observed");
      expect(captured.cwd).toBe(project);
      expect(captured.stdout === stdout).toBe(true);
      sessions.appendCompaction(result.summary, result.firstKeptEntryId, result.tokensBefore, result.details, true, result.usage);
      const parent = sessions.buildSessionContext().messages.find((message) => message.role === "compactionSummary");
      expect(parent).toMatchObject({ summary: result.summary });
      expect(sessions.buildSessionContext().messages.at(-1)).toMatchObject({ role: "user", content: [{ type: "text", text: "Retained user message" }] });

      writeFileSync(policy, "Changed authoritative compaction instructions.\n");
      h.event.preparation.previousSummary = result.summary;
      h.event.branchEntries = sessions.getBranch();
      await callbacks[0](h.event, h.ctx);
      expect(h.requests[1].context.systemPrompt).toBe(readFileSync(policy, "utf8"));
      expect(h.requests[1].context.messages[0].content[0].text).not.toContain("Complete final status row");
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
