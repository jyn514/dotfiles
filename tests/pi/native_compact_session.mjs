// Exercise installed Pi's actual boundary projection and persistence, not the locked SDK.
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { chmod, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const sdkEntry = resolve(packageDir, manifest.exports["."].import);
const sdk = await import(pathToFileURL(sdkEntry).href);
const installedRequire = createRequire(sdkEntry);
let ai;
for (const modulesDir of installedRequire.resolve.paths("@earendil-works/pi-ai")) {
  try {
    const directory = join(modulesDir, "@earendil-works/pi-ai");
    const metadata = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
    ai = await import(pathToFileURL(resolve(directory, metadata.exports["."].import)).href);
    break;
  } catch (error) { if (error.code !== "ENOENT") throw error; }
}
assert.ok(ai, "installed pi-ai public export is required");
const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const extension = join(repository, "config/pi-agent/pi-extensions/compact-session.ts");
const readerPackage = process.env.PI_SESSION_SEARCH_PACKAGE_DIR;
const report = "## Objective and authority\nContinue only the authorized disposable regression.\n\n## State\nExact checkpoint — Καλημέρα 🌱\nDo not infer new authority.\n";
const oldMarker = "PRE_COMPACTION_ONLY_867b42c5";
const correction = "QUEUED_CORRECTION_832eb1: use the corrected requirement, not the old one.";
const systemPrompt = "Keep this system instruction across self-compaction: SYSTEM_OWNER_8b732.";
const text = value => JSON.stringify(value);
const strings = value => typeof value === "string" ? value : value && typeof value === "object"
  ? Object.values(value).map(strings).join("\n") : "";

async function fixture(t, { queued = false } = {}) {
  const root = await mkdtemp(join(tmpdir(), "native-compact-session-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const cwd = join(root, "repo");
  const home = join(root, "home");
  const agentDir = join(home, ".pi/agent");
  const sessionRoot = join(agentDir, "sessions");
  const bin = join(root, "bin");
  const started = join(root, "capture-started");
  const release = join(root, "capture-release");
  await Promise.all([cwd, bin, sessionRoot].map(path => mkdir(path, { recursive: true })));
  // A real subprocess holds the repository-status capture open. Queue input only
  // after that subprocess starts, rather than racing a tool-start notification.
  await writeFile(join(bin, "jj"), `#!${process.execPath}
import { existsSync, writeFileSync } from 'node:fs';
writeFileSync(${JSON.stringify(started)}, 'started');
while (!existsSync(${JSON.stringify(release)})) await new Promise(resolve => setTimeout(resolve, 10));
console.log('Disposable repository status fixture');
`);
  // Node treats extensionless entrypoints as CommonJS unless syntax detection is
  // enabled; use an explicit module package, independent of the host's defaults.
  await writeFile(join(bin, "package.json"), '{"type":"module"}\n');
  await chmod(join(bin, "jj"), 0o755);
  if (!queued) await writeFile(release, "release\n");
  const updates = {
    HOME: home, USERPROFILE: home, CODEX_HOME: join(home, ".codex"),
    PI_SESSION_SEARCH_ROOT: sessionRoot,
    PI_SESSION_SEARCH_CODEX_ROOT: join(home, ".codex/sessions"),
    PATH: `${bin}:${process.env.PATH}`,
  };
  const prior = Object.fromEntries(Object.keys(updates).map(key => [key, process.env[key]]));
  Object.assign(process.env, updates);
  t.after(() => {
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  });
  const faux = ai.fauxProvider({ provider: "native-compact-session", api: "anthropic-messages" });
  const requests = [];
  const respond = message => context => { requests.push(structuredClone(context)); return message; };
  const settingsManager = sdk.SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const modelRuntime = await sdk.ModelRuntime.create({
    credentials: new ai.InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
  });
  const manager = sdk.SessionManager.create(cwd, join(sessionRoot, "--fixture--"));
  // Existing ordinary messages must disappear only from context, not history.
  const originalEntry = manager.appendMessage({ role: "user", content: oldMarker, timestamp: Date.now() });
  let settled = 0;
  let siblingExecutions = 0;
  const errors = [];
  const boundaryExtension = join(root, "other-boundary.mjs");
  await writeFile(boundaryExtension, `export default function (pi) {
  pi.on("turn_end", event => {
    if (!event.toolResults.some(result => result.toolName === "compact_session" && !result.isError)) return;
    return { entries: [...event.entries,
      { type: "custom", customType: "other-boundary-history", data: { retained: true } },
      { type: "custom_message", customType: "other-boundary-message", content: "OTHER_BOUNDARY_43a1", display: false }],
      continue: event.continue };
  });
}\n`);
  const makeSession = async sessionManager => {
    const loader = new sdk.DefaultResourceLoader({
      cwd, agentDir, settingsManager, noExtensions: true, noSkills: true,
      noPromptTemplates: true, noThemes: true, noContextFiles: true,
      // Load the competing handler first: compact_session must preserve drafts
      // already proposed by earlier handlers, not merely coexist with later ones.
      additionalExtensionPaths: [boundaryExtension, extension], systemPrompt,
      extensionFactories: [pi => {
        pi.registerProvider(faux.provider);
        pi.registerTool({ name: "sibling_probe", label: "Sibling probe", description: "Offline regression probe",
          parameters: { type: "object", properties: {} },
          execute: async () => { siblingExecutions++; return { content: [{ type: "text", text: "Sibling completed" }] }; } });
        pi.on("agent_settled", () => { settled++; });
      }],
    });
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    const result = await sdk.createAgentSession({ cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
      sessionManager, model: faux.getModel(), tools: ["compact_session", "sibling_probe"] });
    assert.deepEqual(result.extensionsResult.errors, []);
    const session = result.session;
    t.after(() => session.dispose());
    await session.bindExtensions({ onError: error => errors.push(error) });
    assert.equal(session.getActiveToolNames().filter(name => name === "compact_session").length, 1);
    return session;
  };
  const session = await makeSession(manager);
  return { root, cwd, agentDir, started, release, faux, requests, respond, manager, originalEntry, session, makeSession,
    errors, get settled() { return settled; }, get siblingExecutions() { return siblingExecutions; } };
}

async function recoverWithRealReader(t, f) {
  await t.test("real read_session recovers the pre-compaction message by session identity", {
    skip: !readerPackage && "unverified recovery integration: set PI_SESSION_SEARCH_PACKAGE_DIR to the real reader package",
  }, async () => {
    const loaded = await sdk.discoverAndLoadExtensions([resolve(readerPackage)], f.cwd, f.agentDir);
    assert.deepEqual(loaded.errors, []);
    const reader = loaded.extensions.find(extension => extension.tools.has("read_session"));
    assert.ok(reader, "the supplied real package must register read_session");
    const runner = new sdk.ExtensionRunner(loaded.extensions, loaded.runtime, f.cwd, f.manager, undefined);
    const params = { sessionId: f.manager.getSessionId(), aroundEntryId: f.originalEntry, contextMessages: 0, maxMessages: 1 };
    const actual = await reader.tools.get("read_session").definition.execute("recover-native-compaction", params,
      undefined, undefined, runner.createToolContext("recover-native-compaction", undefined));
    assert.notEqual(actual.isError, true, text(actual));
    assert.equal(actual.details.messages.length, 1);
    assert.equal(actual.details.messages[0].entryId, f.originalEntry);
    assert.match(text(actual.content), new RegExp(oldMarker));
    assert.equal(actual.details.sessionFile, f.manager.getSessionFile());
  });
}

for (const queued of [false, true]) {
  test(`self-compaction replaces actual provider context and survives reopen${queued ? " with queued correction during capture" : ""}`, { timeout: 30_000 }, async t => {
    const f = await fixture(t, { queued });
    f.faux.setResponses([
      f.respond(ai.fauxAssistantMessage(ai.fauxToolCall("compact_session", { report }), { stopReason: "toolUse" })),
      f.respond(ai.fauxAssistantMessage("Continued once with the checkpoint.")),
      f.respond(ai.fauxAssistantMessage("Reopened session continued.")),
    ]);
    const id = f.manager.getSessionId();
    const toolNames = f.session.getActiveToolNames();
    const run = f.session.prompt("Capture the checkpoint and continue in this session.");
    // Attach rejection immediately so a failed load/tool cannot be an unhandled
    // rejection while waiting for the deterministic capture interleaving.
    run.catch(() => {});
    if (queued) {
      try {
        for (let i = 0; i < 500 && !existsSync(f.started); i++) await new Promise(resolve => setTimeout(resolve, 10));
        assert.ok(existsSync(f.started), "repository capture must be in flight before queueing the correction");
        assert.equal(f.requests.length, 1, "no resumed provider request may precede capture completion");
        await f.session.prompt(correction, { streamingBehavior: "steer" });
      } finally { await writeFile(f.release, "release\n"); }
    }
    await run;
    assert.deepEqual(f.errors, []);
    assert.equal(f.requests.length, 2, "exactly one continuation and no summarizer request");
    assert.equal(f.settled, 1);
    assert.equal(f.manager.getSessionId(), id);
    assert.deepEqual(f.session.getActiveToolNames(), toolNames);
    assert.match(text(f.requests[0].messages), new RegExp(oldMarker));
    const entries = f.manager.getEntries();
    const compactions = entries.filter(entry => entry.type === "compaction");
    assert.equal(compactions.length, 1);
    const compact = compactions[0];
    // Pi persists a null-firstKept draft as a self-retaining boundary ID.
    assert.equal(compact.firstKeptEntryId, compact.id);
    assert.equal(compact.summary.slice(0, report.length), report, "checkpoint bytes must not be rewritten");
    assert.equal(compact.details.checkpointLength, report.length);
    assert.match(compact.summary.slice(report.length), /Captured context/);
    assert.ok(compact.summary.includes(id));
    assert.ok(compact.summary.includes(f.manager.getSessionFile()));
    assert.ok(compact.summary.includes(compact.details.captureId));
    assert.equal(entries.filter(entry => entry.customType === "other-boundary-history").length, 1);
    assert.equal(entries.filter(entry => entry.customType === "other-boundary-message").length, 1);
    const next = f.requests[1];
    assert.ok(strings(next.messages).includes(compact.summary), "the next real provider request must receive the exact checkpoint plus appendix");
    assert.doesNotMatch(text(next.messages), new RegExp(oldMarker));
    assert.equal(next.messages.filter(message => message.role === "toolResult").length, 0, "no orphaned compaction acknowledgement");
    const initialSystem = f.requests[0].messages.find(message => message.role === "system");
    const resumedSystem = next.messages.find(message => message.role === "system");
    assert.ok(initialSystem);
    assert.ok(resumedSystem);
    assert.equal(ai.getSystemMessageText(resumedSystem), ai.getSystemMessageText(initialSystem));
    assert.match(ai.getSystemMessageText(resumedSystem), /SYSTEM_OWNER_8b732/);
    assert.deepEqual(resumedSystem.toolsAdded, initialSystem.toolsAdded);
    assert.equal(resumedSystem.toolsAdded.filter(tool => tool.name === "compact_session").length, 1);
    if (queued) {
      assert.equal(text(next.messages).split(correction).length - 1, 1, "queued correction reaches resumed request exactly once");
      const correctionIndex = next.messages.findIndex(message => text(message).includes(correction));
      const checkpointIndex = next.messages.findIndex(message => strings(message).includes(compact.summary));
      assert.ok(correctionIndex > checkpointIndex, "native queue order places the new correction after the checkpoint");
    }
    const sessionFile = f.manager.getSessionFile();
    const raw = (await readFile(sessionFile, "utf8")).trim().split("\n").map(line => JSON.parse(line));
    assert.ok(text(raw).includes(oldMarker), "raw history preserves pre-compaction messages");
    const assistant = raw.find(entry => entry.type === "message" && entry.message.role === "assistant" &&
      entry.message.content.some(block => block.type === "toolCall" && block.name === "compact_session"));
    assert.ok(assistant, "completed tool call remains persisted");
    const call = assistant.message.content.find(block => block.type === "toolCall");
    assert.equal(raw.filter(entry => entry.type === "message" && entry.message.role === "toolResult" &&
      entry.message.toolCallId === call.id && !entry.message.isError).length, 1, "matching successful tool result remains persisted");
    const reopened = sdk.SessionManager.open(sessionFile);
    assert.ok(strings(reopened.buildSessionContext().messages).includes(compact.summary));
    assert.doesNotMatch(text(reopened.buildSessionContext().messages), new RegExp(oldMarker));
    f.session.dispose();
    const resumed = await f.makeSession(reopened);
    await resumed.prompt("Verify the persisted projection after reopening.");
    assert.equal(f.requests.length, 3, "reopen does not replay the staged compaction or trigger an extra continuation");
    assert.ok(strings(f.requests[2].messages).includes(compact.summary));
    assert.doesNotMatch(text(f.requests[2].messages), new RegExp(oldMarker));
    assert.equal(reopened.getEntries().filter(entry => entry.type === "compaction").length, 1);
    if (!queued) {
      await recoverWithRealReader(t, f);
      const secondReport = report + "\nSecond checkpoint after reopening — do not replay the first request.\n";
      f.faux.setResponses([
        f.respond(ai.fauxAssistantMessage(ai.fauxToolCall("compact_session", { report: secondReport }), { stopReason: "toolUse" })),
        f.respond(ai.fauxAssistantMessage("Second checkpoint continued exactly once.")),
      ]);
      await resumed.prompt("Compact again with the updated checkpoint.");
      assert.equal(f.requests.length, 5, "each successful request contributes exactly one continuation");
      const repeated = reopened.getEntries().filter(entry => entry.type === "compaction");
      assert.equal(repeated.length, 2);
      assert.equal(repeated[1].summary.slice(0, secondReport.length), secondReport);
      assert.ok(strings(f.requests[4].messages).includes(repeated[1].summary));
      assert.ok(!strings(f.requests[4].messages).includes(compact.summary), "the previous recovery appendix must not accumulate in context");
      assert.equal(reopened.getEntries().filter(entry => entry.customType === "other-boundary-history").length, 2);
      assert.equal(f.settled, 3, "initial run, reopened turn, and repeated compaction each settle only once");
      assert.deepEqual(f.errors, []);
    }
  });
}

test("the installed bundle registers one tool pointing to the source instructions through a symlink", async t => {
  const root = await mkdtemp(join(tmpdir(), "compact-session-bundle-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const agentDir = join(root, "agent");
  await mkdir(agentDir);
  const installed = join(agentDir, "pi-extensions");
  await symlink(join(repository, "config/pi-agent/pi-extensions"), installed, "dir");
  const prior = process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS;
  try {
    for (const guestRoot of [undefined, "/src/dotfiles", "/relocated/dotfiles"]) {
      if (guestRoot === undefined) delete process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS;
      else process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = JSON.stringify({ [repository]: guestRoot });
      const loaded = await sdk.discoverAndLoadExtensions([join(installed, "index.ts")], root, agentDir);
      assert.deepEqual(loaded.errors, []);
      const tools = loaded.extensions.flatMap(extension => [...extension.tools.values()]);
      const compaction = tools.filter(tool => tool.definition.name === "compact_session");
      assert.equal(compaction.length, 1);
      const expected = join(guestRoot ?? repository, "config/pi-agent/pi-extensions/compaction.md");
      assert.ok(compaction[0].definition.description.includes(`read ${expected}.`));
    }
  } finally {
    if (prior === undefined) delete process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS;
    else process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = prior;
  }
});

for (const [name, invalidReport, mixed] of [
  ["empty report", "", false],
  ["missing authority heading", "A checkpoint without the required heading", false],
  ["mixed tool-call batch", report, true],
]) {
  test(`${name} retains old provider context and never commits a compaction`, { timeout: 30_000 }, async t => {
    const f = await fixture(t);
    const calls = [ai.fauxToolCall("compact_session", { report: invalidReport })];
    if (mixed) calls.push(ai.fauxToolCall("sibling_probe", {}));
    f.faux.setResponses([
      f.respond(ai.fauxAssistantMessage(calls, { stopReason: "toolUse" })),
      f.respond(ai.fauxAssistantMessage("Rejected checkpoint acknowledged.")),
    ]);
    await f.session.prompt("Attempt the invalid checkpoint for this regression.");
    assert.equal(f.requests.length, 2);
    assert.match(text(f.requests[1].messages), new RegExp(oldMarker));
    assert.equal(f.manager.getEntries().filter(entry => entry.type === "compaction").length, 0);
    const results = f.manager.getEntries().filter(entry => entry.type === "message" && entry.message.role === "toolResult");
    const rejected = results.find(entry => entry.message.toolName === "compact_session").message;
    assert.equal(rejected.isError, true);
    assert.match(text(rejected.content), mixed ? /only|sole|alone|batch/i : /empty|fewer than 1 characters|Objective and authority|heading/i);
    assert.equal(f.siblingExecutions, mixed ? 1 : 0, "mixed-batch rejection must not cancel an unrelated sibling tool");
    assert.deepEqual(f.errors, []);
  });
}
