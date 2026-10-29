import { readFileSync } from "node:fs";
import { dirname, basename } from "node:path";
import { expect, test } from "bun:test";
import compactSession from "../../config/pi-agent/pi-extensions/compact-session.ts";
import lunaCompaction from "../../config/pi-agent/pi-extensions/luna-compaction.ts";
import { checkpointText, COMPACTION_INSTRUCTIONS } from "../../config/pi-agent/pi-extensions/checkpoint-capture.ts";
import { parsePiResourcePaths } from "../../config/pi-agent/pi-extensions/guest-tools-core.ts";

// Text protection only: this does not establish summarizer compliance.
test("compaction instructions preserve the local assignment rather than another session's inherited goal", () => {
  const instructions = readFileSync(COMPACTION_INSTRUCTIONS, "utf8");
  expect(instructions).toContain("State this conversation's governing objective, its source and goal status, and latest request separately.");
  expect(instructions).toContain("In split or observer sessions, preserve this conversation's actual assignment as governing; inherited goals owned by another session are background, not this session's active assignment or authority.");
  expect(instructions).toContain("Start with the current local task, then relevant background activities.");
  expect(instructions).toContain("Name each activity's owning session or agent when established, distinguishing this conversation's work from work owned elsewhere.");
});

const report = "## Objective and authority\nContinue the approved task 🐟.\n\n## Current work\nVerification is still pending.\n";
const status = { stdout: "Working copy changes:\nM unrelated.txt\n", stderr: "", code: 0, killed: false };
const call = { type: "toolCall", id: "compact-call", name: "compact_session", arguments: { report } };

function harness() {
  const hooks = new Map<string, Function[]>();
  const tools = new Map<string, any>();
  const executions: any[] = [];
  const notifications: any[] = [];
  const branch: any[] = [
    { type: "message", id: "old-user", message: { role: "user", content: "Old history" } },
    { type: "message", id: "assistant-entry", message: { role: "assistant", content: [{ ...call }] } },
  ];
  let session = "session-a";
  let file: string | undefined = "/private/sessions/current.jsonl";
  const controller = new AbortController();
  const pi: any = {
    registerTool(tool: any) { tools.set(tool.name, tool); },
    on(name: string, handler: Function) { hooks.set(name, [...(hooks.get(name) ?? []), handler]); },
    async exec(...args: any[]) { executions.push(args); return status; },
  };
  const ctx: any = {
    cwd: "/private/project",
    sessionManager: {
      getBranch: () => branch,
      getSessionId: () => session,
      getSessionFile: () => file,
    },
    ui: { notify: (...args: any[]) => notifications.push(args) },
  };
  compactSession(pi);
  async function emit(name: string, event: any = {}) {
    let result;
    for (const handler of hooks.get(name) ?? []) result = await handler(event, ctx);
    return result;
  }
  return {
    pi, ctx, tools, branch, controller, executions, notifications, emit,
    session: (value: string) => { session = value; },
    file: (value: string | undefined) => { file = value; },
    execute: (text = report, id = "compact-call") => tools.get("compact_session").execute(id, { report: text }, controller.signal, undefined, ctx),
    complete(overrides: any = {}) {
      const result = { role: "toolResult", toolCallId: "compact-call", toolName: "compact_session", content: [], isError: false };
      branch.push({ type: "message", id: "tool-result", message: result });
      return emit("turn_end", {
        entries: [], continue: false, context: {}, outcome: "completed", messageEntryId: "assistant-entry",
        message: branch.find(entry => entry.id === "assistant-entry")?.message,
        toolResults: [result], toolResultEntryIds: ["tool-result"], ...overrides,
      });
    },
  };
}

function visibleCapture(summary: string) {
  return JSON.parse(summary.slice(summary.lastIndexOf("\n\n{") + 2));
}

test("stages an exact report and consumes it once only after its successful persisted result", async () => {
  const h = harness();
  expect(await h.emit("turn_end")).toBeUndefined();
  const ack = await h.execute();
  expect(ack.details).toEqual({ pending: true });
  expect(ack.content[0].text).toContain("after this turn's tool result is saved");
  expect(h.executions[0]).toMatchObject(["jj", ["status", "--no-pager", "--color=never"], { cwd: h.ctx.cwd, timeout: 10000 }]);
  const proposed = [{ type: "custom", customType: "another-owner", data: { preserved: true } }];
  const result = await h.complete({ entries: proposed });
  expect(result.continue).toBe(true);
  expect(proposed).toHaveLength(1);
  expect(result.entries[0]).toBe(proposed[0]);
  const compact = result.entries[1];
  expect(compact).toMatchObject({ type: "compaction", firstKeptEntryId: null });
  expect(checkpointText(compact)).toBe(report);
  expect(compact.details.checkpointLength).toBe(report.length);
  expect(visibleCapture(compact.summary).recovery).toEqual({ sessionId: "session-a", sessionFile: "/private/sessions/current.jsonl", captureId: compact.details.captureId });
  expect(visibleCapture(compact.summary)).not.toHaveProperty("recordedEditWriteTargets");
  expect(compact.details).not.toHaveProperty("modifiedFiles");
  expect(await h.complete()).toBeUndefined();
  expect(h.notifications).toEqual([]);
});

test.each(["", "  \n", "No required heading", "The phrase ## Objective and authority is not a heading"])("rejects malformed reports before status capture: %j", async text => {
  const h = harness();
  await expect(h.execute(text)).rejects.toThrow(/empty|missing the Objective and authority header/);
  expect(h.executions).toHaveLength(0);
  expect(await h.complete()).toBeUndefined();
});

test("checks structure, not the report's claims or Markdown heading level", async () => {
  const h = harness();
  const text = "Preface\n###### Objective and authority\t\r\nAn unverified assertion.\n";
  await h.execute(text);
  expect(checkpointText((await h.complete()).entries[0])).toBe(text);
});

test("rejects mixed and nested calls without capturing or compacting", async () => {
  const h = harness();
  h.branch.at(-1).message.content.push({ type: "toolCall", id: "read-call", name: "read", arguments: { path: "x" } });
  await expect(h.execute()).rejects.toThrow("Call compact_session alone");
  h.branch.at(-1).message.content.pop();
  await expect(h.execute(report, "parent/1")).rejects.toThrow("Call compact_session alone");
  expect(h.executions).toHaveLength(0);
  expect(await h.complete()).toBeUndefined();
});

test("a request cannot replace an already staged report", async () => {
  const h = harness();
  await h.execute();
  await expect(h.execute()).rejects.toThrow("already pending");
  expect(h.executions).toHaveLength(1);
  expect(checkpointText((await h.complete()).entries[0])).toBe(report);
});

for (const overrides of [
  { outcome: "aborted" },
  { outcome: "error" },
  { messageEntryId: "other-assistant" },
  { toolResults: [{ toolCallId: "different-call", isError: false }] },
  { toolResults: [{ toolCallId: "compact-call", isError: true }] },
  { toolResultEntryIds: ["not-on-branch"] },
]) {
  test(`an unsuccessful or unrelated turn cannot compact: ${JSON.stringify(overrides)}`, async () => {
    const h = harness();
    await h.execute();
    expect(await h.complete(overrides)).toBeUndefined();
    expect(await h.complete()).toBeUndefined();
  });
}

for (const event of ["session_start", "session_switch", "session_fork", "session_tree", "session_shutdown", "agent_settled"]) {
  test(`${event} clears a pending request without preventing a later explicit request`, async () => {
    const h = harness();
    await h.execute();
    await h.emit(event);
    expect(await h.complete()).toBeUndefined();
    await h.execute();
    expect((await h.complete()).entries).toHaveLength(1);
  });
}

test.each(["session", "branch", "abort"])("a staged request cannot follow a changed %s", async change => {
  const h = harness();
  await h.execute();
  if (change === "session") h.session("session-b");
  if (change === "branch") h.branch.splice(1);
  if (change === "abort") h.controller.abort();
  expect(await h.complete()).toBeUndefined();
});

test("aborting before execution does not probe repository state", async () => {
  const h = harness();
  h.controller.abort();
  await expect(h.execute()).rejects.toThrow();
  expect(h.executions).toHaveLength(0);
});

test.each(["session_tree", "session_shutdown"])("%s cancels a suspended capture and cannot stage its late completion", async event => {
  const h = harness();
  let release!: (value: typeof status) => void;
  h.pi.exec = async () => new Promise(resolve => { release = resolve; });
  const execution = h.execute();
  await h.emit(event);
  release(status);
  await expect(execution).rejects.toThrow();
  expect(await h.complete()).toBeUndefined();
});

test("session replacement during capture is rejected even without a lifecycle notification", async () => {
  const h = harness();
  h.pi.exec = async () => { h.session("other-session"); return status; };
  await expect(h.execute()).rejects.toThrow("Session or branch changed");
  expect(await h.complete()).toBeUndefined();
});

test("status failure records unknown state and an in-memory session does not invent a recovery file", async () => {
  const h = harness();
  h.file(undefined);
  h.pi.exec = async () => { throw new Error("jj unavailable"); };
  await h.execute();
  const compact = (await h.complete()).entries[0];
  expect(checkpointText(compact)).toBe(report);
  expect(visibleCapture(compact.summary)).toMatchObject({ repository: { state: "unknown", error: "jj unavailable" }, recovery: { sessionFile: null } });
});

test("inherited targets survive self-compaction and a later Luna checkpoint without replaying the capture footer", async () => {
  const h = harness();
  h.branch.unshift({ type: "compaction", id: "previous", summary: "Earlier checkpoint", details: { modifiedFiles: ["prior.ts", null, "prior.ts", "β.ts"] } });
  await h.execute();
  const compact = (await h.complete()).entries[0];
  expect(compact.details.modifiedFiles).toEqual(["prior.ts", "β.ts"]);
  expect(visibleCapture(compact.summary).recordedEditWriteTargets).toBe(2);
  expect(compact.summary).not.toContain('"prior.ts"');
  h.branch.push({ ...compact, id: "self-checkpoint" });
  const requests: any[] = [];
  h.ctx.model = { provider: "local", id: "active", maxTokens: 2048 };
  h.ctx.modelRegistry = {
    find: () => undefined,
    async complete(_model: any, context: any) {
      requests.push(context);
      return { content: [{ type: "text", text: "## Objective and authority\nReconciled checkpoint" }], stopReason: "stop" };
    },
  };
  lunaCompaction(h.pi);
  const result = await h.emit("session_before_compact", {
    signal: h.controller.signal, branchEntries: h.branch,
    preparation: { previousSummary: compact.summary, messagesToSummarize: [], turnPrefixMessages: [], tokensBefore: 1234,
      firstKeptEntryId: "retained", settings: { reserveTokens: 2048 },
      fileOps: { read: new Set(["read-only.ts"]), edited: new Set(["new.ts"]), written: new Set() } },
  });
  expect(requests[0].systemPrompt).toBe(readFileSync(COMPACTION_INSTRUCTIONS, "utf8"));
  expect(requests[0].messages[0].content[0].text).toContain(report);
  expect(requests[0].messages[0].content[0].text).not.toContain("caller-preserved");
  expect(requests[0].messages[0].content[0].text).not.toContain(compact.details.captureId);
  expect(result.compaction.details.modifiedFiles).toEqual(["new.ts", "prior.ts", "β.ts"]);
});

test.each([undefined, "/src/dotfiles/config/pi-agent/pi-extensions", "/relocated/resources/pi"])( 
  "registered instruction path follows the agent resource mapping: %j", async guestDirectory => {
    const previous = process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS;
    try {
      if (guestDirectory === undefined) delete process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS;
      else process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = JSON.stringify({
        [dirname(COMPACTION_INSTRUCTIONS)]: guestDirectory,
      });
      const h = harness();
      const tool = h.tools.get("compact_session");
      const expected = guestDirectory ? `${guestDirectory}/${basename(COMPACTION_INSTRUCTIONS)}` : COMPACTION_INSTRUCTIONS;
      expect(h.tools.size).toBe(1);
      expect(tool.description).toContain(`read ${expected}.`);
      expect(tool.description).toContain("read_session");
      if (expected !== COMPACTION_INSTRUCTIONS) expect(tool.description).not.toContain(COMPACTION_INSTRUCTIONS);

      // Luna runs on the host even when the agent reads resources in the guest.
      const requests: any[] = [];
      h.ctx.model = { provider: "local", id: "active", maxTokens: 2048 };
      h.ctx.modelRegistry = {
        find: () => undefined,
        async complete(_model: any, context: any) {
          requests.push(context);
          return { content: [{ type: "text", text: report }], stopReason: "stop" };
        },
      };
      lunaCompaction(h.pi);
      await h.emit("session_before_compact", {
        signal: h.controller.signal, branchEntries: h.branch,
        preparation: { messagesToSummarize: [], turnPrefixMessages: [], tokensBefore: 1234,
          firstKeptEntryId: "retained", settings: { reserveTokens: 2048 },
          fileOps: { read: new Set(), edited: new Set(), written: new Set() } },
      });
      expect(requests).toHaveLength(1);
      expect(requests[0].systemPrompt).toBe(readFileSync(COMPACTION_INSTRUCTIONS, "utf8"));
    } finally {
      if (previous === undefined) delete process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS;
      else process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = previous;
    }
  },
);

test.each(["null", "[]", "42", '{"relative":"/guest"}', '{"/host":"relative"}', '{"/host":null}'])(
  "resource mapping rejects invalid shapes: %s", raw => {
    expect(() => parsePiResourcePaths(raw)).toThrow("Pi resource path mapping is invalid");
  },
);
