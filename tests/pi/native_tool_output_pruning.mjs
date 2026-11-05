// Run against installed Pi: the locked unit-test SDK predates boundary edits.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test, { describe } from "node:test";

const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
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
assert.ok(ai);
const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const extension = process.env.PI_PRUNING_TEST_EXTENSION || join(repository, "config/pi-agent/pi-extensions/luna-compaction.ts");
const compactExtension = process.env.PI_PRUNING_TEST_COMPACT_EXTENSION || join(repository, "config/pi-agent/pi-extensions/compact-session.ts");
const oldOutput = "OLD_OUTPUT_7d1c " + "o".repeat(56000);
const latestOutput = "LATEST_UNSEEN_OUTPUT_4e19";
const checkpoint = "## Objective and authority\nContinue the disposable pruning test.\n";
const text = value => JSON.stringify(value);
const strings = value => typeof value === "string" ? value : value && typeof value === "object"
  ? Object.values(value).map(strings).join("\n") : "";
const calls = content => ai.fauxAssistantMessage(content, { stopReason: "toolUse" });

async function fixture(t, { worker = false, enabled = true, systemPrompt = "Preserve SYSTEM_OWNER_45ca", overrides,
  extensionPaths = [extension], old = oldOutput, latest = latestOutput, inMemory = false,
  priorEntries, toolNames = ["probe"] } = {}) {
  const root = await mkdtemp(join(tmpdir(), "tool-output-pruning-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const prior = process.env.PI_SUBAGENT_ID;
  if (worker) process.env.PI_SUBAGENT_ID = "pruning-regression";
  else delete process.env.PI_SUBAGENT_ID;
  t.after(() => {
    if (prior === undefined) delete process.env.PI_SUBAGENT_ID; else process.env.PI_SUBAGENT_ID = prior;
  });
  const faux = ai.fauxProvider({ provider: "pruning-test", api: "anthropic-messages",
    models: [{ id: "worker", contextWindow: 20000, maxTokens: 4096 }] });
  const settingsManager = sdk.SettingsManager.inMemory({ retry: { enabled: false },
    compaction: { enabled, reserveTokens: 5000, keepRecentTokens: 1000, ...overrides } });
  const modelRuntime = await sdk.ModelRuntime.create({ credentials: new ai.InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(root, "models.json"), allowModelNetwork: false, refreshOnCreate: false });
  const manager = inMemory ? sdk.SessionManager.inMemory(root) : sdk.SessionManager.create(root, join(root, "sessions"));
  const requests = [];
  const summaries = [];
  const boundaries = [];
  const errors = [];
  if (priorEntries) {
    const earlierExtension = join(root, "earlier-boundary.mjs");
    await writeFile(earlierExtension, `export default function(pi) {
      pi.on("turn_end", event => event.turnIndex === 1
        ? { entries: [...event.entries, ...${JSON.stringify(priorEntries)}], continue: event.continue } : undefined);
    }`);
    extensionPaths = [earlierExtension, ...extensionPaths];
  }
  const makeSession = async manager => {
    const loader = new sdk.DefaultResourceLoader({ cwd: root, agentDir: join(root, "agent"), settingsManager,
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: extensionPaths, systemPrompt,
      extensionFactories: [pi => {
        pi.registerProvider(faux.provider);
        pi.registerTool({ name: "probe", label: "Probe", description: "Disposable output fixture",
          parameters: { type: "object", properties: { which: { type: "string" } }, required: ["which"] },
          execute: async (_id, { which }) => ({ content: [{ type: "text", text: which === "old" ? old : latest }],
            details: { retained: which }, isError: which === "old" }) });
        pi.on("session_start", (_event, ctx) => {
          // Only summary generation uses complete(); real worker requests use the
          // registered faux provider. Never contact a live summarization model.
          ctx.modelRegistry.complete = async (model, context, options) => {
            summaries.push({ model, context: structuredClone(context), options });
            return ai.fauxAssistantMessage(checkpoint);
          };
        });
        pi.on("turn_end", event => boundaries.push(structuredClone(event)));
      }],
    });
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    const result = await sdk.createAgentSession({ cwd: root, agentDir: join(root, "agent"), resourceLoader: loader,
      settingsManager, modelRuntime, sessionManager: manager, model: faux.getModel(), tools: toolNames });
    assert.deepEqual(result.extensionsResult.errors, []);
    t.after(() => result.session.dispose());
    await result.session.bindExtensions({ onError: error => errors.push(error) });
    return result.session;
  };
  const session = await makeSession(manager);
  const respond = message => context => { requests.push(structuredClone(context)); return message; };
  const run = async (middle = "a".repeat(6000), pending) => {
    const second = respond(calls([ai.fauxText(middle), ai.fauxToolCall("probe", { which: "latest" })]));
    faux.setResponses([
      respond(calls(ai.fauxToolCall("probe", { which: "old" }))),
      async context => {
        if (pending) await session.prompt(pending, { streamingBehavior: "steer" });
        return second(context);
      },
      respond(ai.fauxAssistantMessage("Done.")),
    ]);
    await session.prompt("Run the disposable probe twice, then finish.");
    assert.deepEqual(errors, []);
    assert.equal(requests.length, 3, "pruning must not add a provider continuation");
  };
  return { root, faux, session, manager, requests, summaries, boundaries, makeSession, respond, run, errors, settingsManager };
}

describe("tool-output-pruning", () => {
  for (const worker of [false, true]) {
    test(`${worker ? "worker" : "root"}: old output reaches the model once, then only its body changes in actual provider context and after reopen`, async t => {
      const f = await fixture(t, { worker });
      await f.run();
      assert.equal(f.summaries.length, 0, "successful pruning makes no Luna or fallback-model request");
      assert.ok(text(f.requests[1]).includes(oldOutput), "the model sees the complete output before it becomes eligible");
      const original = f.manager.getEntries().find(entry => entry.type === "message" &&
        entry.message.role === "toolResult" && entry.message.details?.retained === "old");
      const edits = f.manager.getEntries().filter(entry => entry.type === "context_edit");
      assert.equal(edits.length, 1);
      assert.equal(edits[0].targetId, original.id);
      const marker = edits[0].replacement.content[0].text;
      assert.ok(marker.includes(`aroundEntryId: ${JSON.stringify(original.id)}`));
      const next = f.requests[2].messages;
      assert.ok(strings(next).includes(marker));
      assert.ok(!text(next).includes(oldOutput));
      assert.ok(text(next).includes(latestOutput), "the newest, unseen batch remains intact");
      assert.ok(text(next).includes("a".repeat(6000)), "assistant text is not pruned");
      assert.ok(text(next).includes("Run the disposable probe twice"), "the governing user message is intact");
      assert.ok(text(next).includes("SYSTEM_OWNER_45ca"));
      assert.equal(ai.getCurrentTools(next).filter(tool => tool.name === "probe").length, 1);
      const projected = f.manager.buildSessionProjection().entries.find(entry => entry.sourceEntry.id === original.id).messages[0];
      assert.deepEqual({ ...projected, content: original.message.content }, original.message,
        "call identity, tool name, error state, details and all other metadata survive");
      const raw = await readFile(f.manager.getSessionFile(), "utf8");
      assert.ok(raw.includes(oldOutput), "raw history is never rewritten");
      const reopened = sdk.SessionManager.open(f.manager.getSessionFile());
      assert.ok(strings(reopened.buildSessionContext()).includes(marker));
      assert.ok(!text(reopened.buildSessionContext()).includes(oldOutput));
      f.session.dispose();
      const resumed = await f.makeSession(reopened);
      f.faux.setResponses([f.respond(ai.fauxAssistantMessage("Resumed."))]);
      await resumed.prompt("Resume with the persisted projection.");
      assert.ok(strings(f.requests[3]).includes(marker));
      assert.ok(!text(f.requests[3]).includes(oldOutput));
      assert.equal(reopened.getEntries().filter(entry => entry.type === "context_edit").length, 1);

      // Use the repository's actual independent reader, not Pi's edited projection.
      const loaded = await sdk.discoverAndLoadExtensions([join(repository, "tools/pi-session-search")], f.root, join(f.root, "reader"));
      assert.deepEqual(loaded.errors, []);
      const reader = loaded.extensions.find(extension => extension.tools.has("read_session"));
      assert.ok(reader);
      const runner = new sdk.ExtensionRunner(loaded.extensions, loaded.runtime, f.root, reopened, undefined);
      const params = { sessionFile: reopened.getSessionFile(), aroundEntryId: original.id, contextMessages: 0, maxMessages: 1 };
      const recovered = await reader.tools.get("read_session").definition.execute("recover-pruned-output", params,
        undefined, undefined, runner.createToolContext("recover-pruned-output", undefined));
      assert.notEqual(recovered.isError, true, text(recovered));
      assert.equal(recovered.details.messages[0].entryId, original.id);
      // Reader display truncation is independent of preservation of the full raw record.
      assert.ok(text(recovered.content).includes("OLD_OUTPUT_7d1c"));
    });
  }

  for (const { name, options, middle, pending, summaries, laterPruning = false } of [
    { name: "disabled auto-compaction never prunes", options: { enabled: false }, summaries: 0 },
    { name: "below-threshold context is untouched", middle: "a".repeat(100), summaries: 0 },
    { name: "per-model reserve override controls the pruning threshold",
      options: { overrides: { modelOverrides: { "pruning-test/worker": { reserveTokens: 0 } } } }, summaries: 0 },
    { name: "an oversized retained assistant response falls back with original tool output",
      middle: "a".repeat(18000), summaries: 1 },
    { name: "the newest batch cannot be removed to meet the target",
      options: { latest: oldOutput }, summaries: 1, laterPruning: true },
    { name: "system prompt and tool declarations count toward the 20% target",
      options: { systemPrompt: "SYSTEM_OWNER_45ca " + "s".repeat(14000), old: "OLD_OUTPUT_7d1c " + "o".repeat(43000) }, summaries: 1 },
    { name: "queued steering counts toward the 20% target",
      pending: "PENDING_CORRECTION " + "q".repeat(12000), summaries: 1 },
    { name: "prior boundary proposals count toward the target",
      options: { priorEntries: [{ type: "custom_message", customType: "earlier-handler", content: "p".repeat(12000), display: false }] },
      summaries: 1 },
    { name: "unsaved in-memory sessions do not promise recovery from omitted output",
      options: { inMemory: true }, summaries: 1 },
  ]) {
    test(name, async t => {
      const f = await fixture(t, options);
      await f.run(middle, pending);
      assert.equal(f.boundaries[1].entries.filter(entry => entry.type === "context_edit").length, 0,
        "the boundary that rejects pruning proposes no edits");
      assert.equal(f.manager.getEntries().filter(entry => entry.type === "context_edit").length, laterPruning ? 1 : 0);
      assert.equal(f.summaries.length, summaries);
      if (summaries) {
        assert.ok(text(f.summaries[0].context).includes("OLD_OUTPUT_7d1c"), "Luna receives originals, not speculative omission markers");
        assert.ok(!text(f.summaries[0].context).includes("[Output omitted."));
        assert.ok(text(f.requests[2]).includes(checkpoint.trim().replaceAll("\n", "\\n")));
      } else {
        assert.ok(text(f.requests[2]).includes("OLD_OUTPUT_7d1c"), "no pruning or summarization changes the context");
      }
    });
  }

  test("manual compaction still summarizes below-threshold history", async t => {
    const f = await fixture(t);
    await f.run("small response");
    assert.equal(f.summaries.length, 0);
    await f.session.compact("Preserve the explicit manual request.");
    assert.equal(f.summaries.length, 1);
    assert.ok(strings(f.summaries[0].context).includes("OLD_OUTPUT_7d1c"));
    assert.ok(strings(f.summaries[0].context).includes("Preserve the explicit manual request."));
    assert.equal(f.manager.getEntries().filter(entry => entry.type === "context_edit").length, 0);
  });

  for (const stopReason of ["error", "aborted"]) {
    test(`${stopReason} boundaries keep old outputs intact`, async t => {
      const f = await fixture(t);
      f.faux.setResponses([
        f.respond(calls(ai.fauxToolCall("probe", { which: "old" }))),
        f.respond(ai.fauxAssistantMessage("a".repeat(6000), { stopReason, errorMessage: "Synthetic non-overflow failure" })),
      ]);
      await f.session.prompt("Exercise the failed boundary.");
      assert.equal(f.requests.length, 2);
      assert.equal(f.manager.getEntries().filter(entry => entry.type === "context_edit").length, 0);
      assert.ok(strings(f.manager.getEntries()).includes(oldOutput));
      // Core may still summarize a failed over-threshold run after turn_end.
      assert.equal(f.summaries.length, stopReason === "error" ? 1 : 0);
      if (f.summaries.length) assert.ok(strings(f.summaries[0].context).includes("OLD_OUTPUT_7d1c"));
    });
  }

  test("successful pruning preserves an earlier handler's drafts and continuation decision", async t => {
    const f = await fixture(t, { priorEntries: [
      { type: "custom", customType: "other-boundary-state", data: { retained: true } },
      { type: "custom_message", customType: "other-boundary-message", content: "OTHER_BOUNDARY_5ca2", display: false },
    ] });
    await f.run();
    assert.equal(f.summaries.length, 0);
    assert.equal(f.manager.getEntries().filter(entry => entry.type === "context_edit").length, 1);
    assert.equal(f.manager.getEntries().filter(entry => entry.customType === "other-boundary-state").length, 1);
    assert.ok(strings(f.requests[2]).includes("OTHER_BOUNDARY_5ca2"));
  });

  for (const worker of [false, true]) {
    for (const enabled of [false, true]) {
      test(`tool_output_only in ${worker ? "worker" : "root"}, automatic compaction ${enabled ? "enabled" : "disabled"}`, async t => {
        const retained = "ASSISTANT_RETAINED " + "a".repeat(18000);
        const f = await fixture(t, { worker, enabled, old: "OLD_OUTPUT_7d1c " + "o".repeat(16000),
          extensionPaths: [extension, compactExtension],
          toolNames: ["probe", "compact_session"],
          priorEntries: [{ type: "custom_message", customType: "other-boundary-message", content: "OTHER_BOUNDARY_5ca2", display: false }],
        });
        f.faux.setResponses([
          f.respond(calls(ai.fauxToolCall("probe", { which: "old" }))),
          f.respond(calls([ai.fauxText(retained), ai.fauxToolCall("compact_session", { tool_output_only: true })])),
          f.respond(ai.fauxAssistantMessage("Continued after removing only tool output.")),
        ]);
        await f.session.prompt("Preserve USER_RETAINED_325a; remove tool output only.");
        assert.deepEqual(f.errors, []);
        assert.equal(f.requests.length, 3);
        assert.equal(f.summaries.length, 0);
        const entries = f.manager.getEntries();
        assert.equal(entries.filter(entry => entry.type === "compaction").length, 0);
        const original = entries.find(entry => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "probe");
        const edits = entries.filter(entry => entry.type === "context_edit");
        assert.equal(edits.length, 1);
        assert.equal(edits[0].targetId, original.id);
        const next = strings(f.requests[2]);
        assert.ok(!next.includes("OLD_OUTPUT_7d1c"));
        for (const kept of [retained, "USER_RETAINED_325a", "SYSTEM_OWNER_45ca", "OTHER_BOUNDARY_5ca2", "Tool-output pruning queued."]) {
          assert.ok(next.includes(kept), `preserve ${kept.slice(0, 40)}`);
        }
        assert.ok(next.includes(original.id), "marker identifies the raw original for recovery");
        assert.ok((await readFile(f.manager.getSessionFile(), "utf8")).includes("OLD_OUTPUT_7d1c"));
        const reopened = sdk.SessionManager.open(f.manager.getSessionFile());
        assert.ok(!strings(reopened.buildSessionContext()).includes("OLD_OUTPUT_7d1c"));
        assert.ok(strings(reopened.buildSessionContext()).includes(retained));
        // Assistant text alone exceeds 20% of the fixture's 20k-token window;
        // explicit pruning must still happen, unlike the automatic policy.
        assert.ok(retained.length / 4 > 4000);
      });
    }
  }

  for (const { name, args, inMemory = false, mixed = false } of [
    { name: "missing both modes", args: {} },
    { name: "conflicting modes", args: { tool_output_only: true, report: checkpoint } },
    { name: "no saved transcript", args: { tool_output_only: true }, inMemory: true },
    { name: "mixed tool-call batch", args: { tool_output_only: true }, mixed: true },
  ]) {
    test(`tool_output_only rejects ${name} without changing context`, async t => {
      const f = await fixture(t, { enabled: false, inMemory,
        extensionPaths: [extension, compactExtension],
        toolNames: ["probe", "compact_session"],
      });
      const request = ai.fauxToolCall("compact_session", args);
      f.faux.setResponses([
        f.respond(calls(ai.fauxToolCall("probe", { which: "old" }))),
        f.respond(calls(mixed ? [request, ai.fauxToolCall("probe", { which: "latest" })] : request)),
        f.respond(ai.fauxAssistantMessage("Rejected without losing history.")),
      ]);
      await f.session.prompt("Reject the invalid pruning request.");
      assert.deepEqual(f.errors, []);
      assert.equal(f.requests.length, 3);
      assert.equal(f.summaries.length, 0);
      assert.equal(f.manager.getEntries().filter(entry => ["compaction", "context_edit"].includes(entry.type)).length, 0);
      assert.ok(strings(f.requests[2]).includes(oldOutput));
      const result = f.manager.getEntries().find(entry => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "compact_session");
      assert.equal(result.message.isError, true);
      if (mixed) assert.ok(strings(f.requests[2]).includes(latestOutput), "unrelated sibling tool still executes");
    });
  }

  test("tool_output_only continues once when there is no eligible output", async t => {
    const f = await fixture(t, { enabled: false,
      extensionPaths: [extension, compactExtension],
      toolNames: ["compact_session"],
    });
    f.faux.setResponses([
      f.respond(calls(ai.fauxToolCall("compact_session", { tool_output_only: true }))),
      f.respond(ai.fauxAssistantMessage("No older output to remove.")),
    ]);
    await f.session.prompt("Remove only tool output if any exists.");
    assert.deepEqual(f.errors, []);
    assert.equal(f.requests.length, 2);
    assert.equal(f.summaries.length, 0);
    assert.equal(f.manager.getEntries().filter(entry => ["compaction", "context_edit"].includes(entry.type)).length, 0);
  });

  test("explicit self-compaction wins even when its turn_end handler runs after pruning", async t => {
    const f = await fixture(t, {
      extensionPaths: [extension, compactExtension],
      toolNames: ["probe", "compact_session"],
    });
    f.faux.setResponses([
      f.respond(calls(ai.fauxToolCall("probe", { which: "old" }))),
      f.respond(calls([ai.fauxText("a".repeat(6000)), ai.fauxToolCall("compact_session", { report: checkpoint })])),
      f.respond(ai.fauxAssistantMessage("Continued from the explicit checkpoint.")),
    ]);
    await f.session.prompt("Read the probe, then compact explicitly.");
    assert.deepEqual(f.errors, []);
    assert.equal(f.requests.length, 3);
    assert.equal(f.summaries.length, 0);
    assert.equal(f.manager.getEntries().filter(entry => entry.type === "context_edit").length, 0);
    assert.equal(f.manager.getEntries().filter(entry => entry.type === "compaction").length, 1);
    assert.ok(strings(f.requests[2]).includes(checkpoint));
    assert.ok(!strings(f.requests[2]).includes(oldOutput));
  });

});
