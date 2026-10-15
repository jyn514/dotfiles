import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, spyOn, test } from "bun:test";
import { DEFAULT_COMPACTION_SETTINGS } from "@earendil-works/pi-coding-agent";
import { listCuts, main, replayInput } from "../../dev/replay-compaction";
import { checkpointText, COMPACTION_INSTRUCTIONS, COMPACTION_MODEL } from "../../config/pi-agent/pi-extensions/luna-compaction";

const header = { type: "session", version: 3, id: "0537ee54-642f-4ce4-a67b-ff9b06b39104", timestamp: "2026-10-03T00:00:00Z", cwd: "/owned" };
const user = (id: string, parentId: string | null, text: string) => ({ type: "message", id, parentId, timestamp: header.timestamp, message: { role: "user", content: [{ type: "text", text }], timestamp: 1 } });
const checkpoint = (id: string, parentId: string, firstKeptEntryId: string, prose: string) => ({ type: "compaction", id, parentId, firstKeptEntryId, timestamp: header.timestamp, tokensBefore: 100, summary: prose + "\nCALLER STATUS", details: { checkpointLength: prose.length } });
const previous = checkpoint("first", "retained", "retained", "Previous checkpoint 🐟");
const current = checkpoint("second", "tail", "cut", "Original checkpoint 🐟");
const entries = [header, user("old", null, "Already summarized"), user("retained", "old", "Earlier retained input"), previous,
  user("new", "first", "New prefix input"), user("cut", "new", "Retained suffix"), user("tail", "cut", "Later suffix"), current];
const jsonl = (items: unknown[]) => items.map(item => JSON.stringify(item)).join("\n") + "\n";
const historicalFixture = (name: string) => readFileSync(new URL(`./fixtures/compaction-replay/${name}.jsonl`, import.meta.url), "utf8");

describe("compaction replay", () => {
  test("uses the recorded prefix and shared checkpoint offset, not today's retention settings", () => {
    const { original, prompt } = replayInput(jsonl(entries), "second");
    expect(checkpointText(original)).toBe("Original checkpoint 🐟");
    expect(prompt).toContain("Previous checkpoint 🐟");
    expect(prompt).toContain("Earlier retained input");
    expect(prompt).toContain("New prefix input");
    for (const excluded of ["Already summarized", "Retained suffix", "Later suffix", "CALLER STATUS", "Original checkpoint"]) expect(prompt).not.toContain(excluded);
    const changedOffset = { ...previous, summary: "Different authority\nSNAPSHOT", details: { checkpointLength: "Different authority".length } };
    expect(replayInput(jsonl(entries.map(entry => entry === previous ? changedOffset : entry)), "second").prompt).toContain("Different authority");
    expect(replayInput(jsonl(entries.map(entry => entry === previous ? changedOffset : entry)), "second").prompt).not.toContain("SNAPSHOT");
  });

  // These assertions protect the historical INPUT supplied to a replay. They do
  // not score generated replies or prove that a model retains these facts.
  test.each([
    {
      name: "persistent-corrections", target: "42d6f5af",
      required: [
        "using the session history that preceeded the summaries and your new instructions",
        "you were supposed to do a blind test. you gave them access to the past summary, that's not right",
        "get rid of this whole evaluation criteria thing, just read and judge the summaries yourself",
      ],
    },
    {
      name: "conditional-permission", target: "20e73b8a",
      required: [
        "you may not edit the product requirements or product brief.",
        "if you implement the feasibility boundary and its gate fails, you may edit the implementation spec to try and remove the blocker.",
        "if you find a product design choice that has not been specified, record that as a TODO in the impl spec and continue implementing around it.",
        "if you have no remaining work that you can do without a product decision, commit your changes so far, then make a reasonable choice, document it in the impl spec, clearly distinguished as needing product review, and implement based on that decision.",
        "another agent is editing the spec in parallel, check to make sure there are no uncommitted changes before editing the spec",
      ],
    },
    {
      name: "accepted-evidence-newer-experiment", target: "28049f46",
      required: [
        "PASS INTEGRATED PROVISIONAL RESEARCH; NOT ADOPTION",
        '"bindings": 100775',
        "target/research/ordinary-gap-parent-acceptance-v1/results.json",
        "Batch complete, local-only",
        "target/research/ordinary-gap-followup-v2-complete/",
        "138 branch/phase/key proofs",
        "Global namespace and native/public checks remain the next required integration step.",
        "OwnNEWbatchnamespaceproducer+freshoutputs conditionalnotparentacceptance",
        "Spawned /ordinary-gap-batch-namespace.",
        "suggest concrete improvements to /owned/dotfiles/config/pi-agent/pi-extensions/compaction.md",
      ],
      excluded: ["ordinary-gap-v2-owning-full-closure-v1-fresh3", "STAT: done", "more characters truncated"],
    },
    {
      name: "investigation-only", target: "bc29caa4",
      required: [
        "look at the code, how would you design this?",
        "separate persistent clone acceptable",
        "the remaining investigation is whether direct ChatGPT OAuth can replace the model translator.",
        "investigate",
        "ok stop. what are you doing, why, and what have you discovered so far",
        "An in-process adaptation worked in a local prototype",
        'your "client" is just the proxy, rebuilt in-process. assume we keep the model proxy.',
        "Agreed: I moved the translation into the client rather than removing it.",
        "Model OAuth stays with the existing proxy outside the guest",
        "No model-client adaptation, external Git-management patch, JJ bridge, or trusted publisher.",
        "could it be as simple as running on docker-compose or does codex-sandbox still provide value?",
      ],
    },
  ])("reconstructs source corrections and authority for $name without a model request", ({ name, target, required, excluded = [] }) => {
    const { original, prompt } = replayInput(historicalFixture(name));
    expect(original.id).toBe(target);
    for (const text of required) expect(prompt).toContain(text);
    for (const text of excluded) expect(prompt).not.toContain(text);
    expect(prompt).not.toContain("Retained suffix (fixture scaffolding, not historical evidence).");
    expect(prompt).not.toContain("<previous-checkpoint>");
    expect(prompt).not.toContain(checkpointText(original));
  });

  test("investigation replay keeps the proposal, report, correction, and acknowledgment in speaker order", () => {
    const { prompt } = replayInput(historicalFixture("investigation-only"));
    const exchange = [
      "[Assistant]: Then the guest owns the persistent clone",
      "[User]: investigate",
      "[User]: ok stop. what are you doing",
      "[Assistant]: Stopped. I was checking whether Strix can use ChatGPT OAuth directly",
      '[User]: your "client" is just the proxy, rebuilt in-process.',
      "[Assistant]: Agreed: I moved the translation into the client rather than removing it.",
      "[User]: cool, so this is basically just a normal docker container",
    ];
    let preceding = -1;
    for (const clause of exchange) {
      const position = prompt.indexOf(clause);
      expect(position).toBeGreaterThan(preceding);
      preceding = position;
    }
  });

  test("repeated historical replays inherit the saved checkpoint while keeping later task authority at its recorded cut", () => {
    const source = historicalFixture("paused-repeated-compaction");
    const second = replayInput(source, "bf746f62");
    const third = replayInput(source);
    expect(third.original.id).toBe("e0fbef33");
    const first = replayInput(source, "8e424df8");
    expect(second.prompt).toContain(`<previous-checkpoint>\n${checkpointText(first.original)}\n</previous-checkpoint>`);
    const savedPlan = "[Assistant]: Saved `tools/jj-proxy/native-dispatch-implementation-plan.md`.";
    expect(second.prompt).toContain(savedPlan);
    expect(second.prompt).toContain("No implementation files changed.");
    expect(second.prompt.indexOf(savedPlan)).toBeLessThan(second.prompt.indexOf("[User]: review your plan"));
    expect(second.prompt).toContain("review your plan");
    expect(second.prompt).toContain("/skill:implementation-plan");
    expect(second.prompt).not.toContain("fix your findings");
    expect(third.prompt).toContain(`<previous-checkpoint>\n${checkpointText(second.original)}\n</previous-checkpoint>`);
    expect(third.prompt).toContain("implementation is paused.");
    expect(third.prompt).toContain("Do not implement the existing narrow `fork_context` draft before design resolution.");
    expect(third.prompt).toContain("Current local task: reviewing `tools/jj-proxy/native-dispatch-implementation-plan.md`; no implementation has been authorized.");
    expect(third.prompt).toContain("fix your findings");
    expect(third.prompt).toContain("[User]: implement");
    // The old raw corrections are absent at this cut; saved prose, not a fake
    // successful generation, supplies the historical authority for human review.
    expect(first.prompt).toContain("i was intending for the agent to be able to fork from *arbitrarily* far back");
    expect(first.prompt).not.toContain(savedPlan);
    expect(third.prompt).not.toContain(savedPlan);
    expect(third.prompt).not.toContain("i was intending for the agent to be able to fork from *arbitrarily* far back");
    expect(third.prompt).not.toContain("Retained suffix (fixture scaffolding, not historical evidence).");
    expect(third.prompt).not.toContain("Implement the approved JJ dispatch plan:");
    expect(third.prompt).not.toContain("Repository state (caller-captured after summary)");
  });

  test("ownership replay supplies the parent's complete successful edit calls beside competing worker and concurrent work", () => {
    const source = historicalFixture("ownership-and-commit-coverage");
    const { prompt } = replayInput(source, "41e76fdb");
    const records = source.trim().split("\n").map(line => JSON.parse(line));
    const edits = [
      { id: "c273b2d2", result: "01d5376c", path: "tools/codex-sandbox/spec/proxy-design.typ", blocks: 4,
        hunks: ["available-channel-list framed operations", "GET /api/v1/streams?include_can_access_content=true", "does not fall back to an unfiltered listing", "all three route families", "three upstream request families", "only the three typed-adapter route families"] },
      { id: "fad102af", result: "da0b4a3d", path: "tools/codex-sandbox/README.md", blocks: 3,
        hunks: ["mkdirat .../.git: invalid argument", "argument-level tests alone do not establish support", "generated-shell PATH limitation", "this incorporation leaves authentication unchanged"] },
      { id: "f23b575d", result: "064f9c8d", path: "tools/codex-sandbox/tests/repository_mounts_integration.py", blocks: 3,
        hunks: ['("missing", False, "common")', "originally_missing = not entry.exists() and not entry.is_symlink()", 'assert not entry.exists() and not entry.is_symlink(), "host .git entry was created"'] },
      { id: "0719d987", result: "02334d8b", path: "tools/codex-sandbox/README.md", blocks: 1,
        hunks: ["--state STATE_DIRECTORY --image AGENT_IMAGE", "A failure is not a passing compatibility check.", "Do not create a synthetic `.git` directory"] },
    ];
    for (const { id, result, path, blocks, hunks } of edits) {
      const call = records.find(entry => entry.id === id)?.message.content.find(block => block.type === "toolCall");
      expect(call?.name).toBe("edit");
      expect(call.arguments.path).toBe(path);
      expect(call.arguments.edits).toHaveLength(blocks);
      // Check complete native call serialization, not just a path mention or a
      // worker's report. The fixed excerpts also detect accidental fixture loss.
      expect(prompt).toContain(`path=${JSON.stringify(path)}`);
      expect(prompt).toContain(`edits=${JSON.stringify(call.arguments.edits)}`);
      for (const hunk of hunks) expect(call.arguments.edits.some(edit => edit.newText.includes(hunk))).toBe(true);
      const returned = records.find(entry => entry.id === result)?.message;
      expect(returned?.isError).toBe(false);
      expect(returned.toolCallId).toBe(call.id);
      expect(prompt).toContain(`[Tool result]: Successfully replaced ${blocks} block(s) in ${path}.`);
    }
    for (const text of [
      "[User]: incorporate your suggested materials into the repo",
      "Add separate changes; preserve and exclude existing work from commits",
      "Preserve proposal; leave authentication unchanged",
      "Parent owns README + proxy-design.typ Zulip route corrections + repository_mounts_integration fixture addition",
      "[Assistant tool calls]: spawn_agent(", 'task_name="incorporate-replay"', "Spawned /incorporate-replay.",
      '"agent_name": "/incorporate-replay"', "**Owned diff:** only `dev/replay-compaction`",
      "diff --git a/tools/codex-sandbox/owned_images.py", "+        )] + ['config/mise.lock']",
    ]) expect(prompt).toContain(text);
    expect(prompt).not.toContain("Integration is complete");
    expect(prompt).not.toContain("The remaining dirty tree is concurrent work");
    expect(prompt).not.toContain("talk to me about logging");
  });

  test("later ownership replay inherits deficient saved prose, not the missing raw proof or a regenerated checkpoint", () => {
    const source = historicalFixture("ownership-and-commit-coverage");
    const first = replayInput(source, "41e76fdb");
    const later = replayInput(source, "4ea2bda0");
    expect(later.prompt).toContain(`<previous-checkpoint>\n${checkpointText(first.original)}\n</previous-checkpoint>`);
    expect(later.prompt).toContain("Resolver/bake worker changes remain uncommitted.");
    expect(later.prompt).toContain("[Assistant]: Integration is complete; concurrent work remains separate.");
    expect(later.prompt).toContain("These are committed. The remaining dirty tree is concurrent work deliberately left separate.");
    expect(later.prompt).toContain("[User]: talk to me about logging");
    const records = source.trim().split("\n").map(line => JSON.parse(line));
    const command = records.find(entry => entry.id === "2768065c").message.content.find(block => block.type === "toolCall").arguments.command;
    expect(later.prompt).toContain(`command=${JSON.stringify(command)}`);
    const checked = command.split("jj diff --name-only -- ")[1].split(" ");
    expect(checked).toContain("tools/codex-sandbox/image_resolver.py");
    expect(checked).toContain("tools/codex-sandbox/sandbox-proxies.py");
    for (const path of ["tools/codex-sandbox/spec/proxy-design.typ", "tools/codex-sandbox/README.md", "tools/codex-sandbox/tests/repository_mounts_integration.py"]) {
      expect(checked).not.toContain(path);
      expect(later.prompt).toContain(`M ${path}`);
    }
    for (const text of [
      "[Assistant tool calls]: edit(", "available-channel-list framed operations",
      "originally_missing =", "mkdirat .../.git: invalid argument",
      "Successfully replaced", "Parent owns README + proxy-design.typ",
      "numeric channels are ok", "k, use a subagent to fix the spec",
      "The original transcript confirms I authored the three-route/channel-listing edits.",
    ]) expect(later.prompt).not.toContain(text);
  });

  test("ownership fixture has two valid native cuts, a latest active default, and no private paths or boundary leaks", () => {
    const source = historicalFixture("ownership-and-commit-coverage");
    const cuts = listCuts(source);
    expect(cuts.map(cut => cut.id)).toEqual(["41e76fdb", "4ea2bda0"]);
    expect(cuts.map(cut => cut.previous)).toEqual([false, true]);
    expect(cuts.every(cut => !cut.error)).toBe(true);
    expect(replayInput(source).original.id).toBe("4ea2bda0");
    expect(source).not.toMatch(/\/(?:home|Users)\//);
    expect(source).not.toContain("thinkingSignature");
    for (const cut of cuts) {
      const { original, prompt } = replayInput(source, cut.id);
      expect(prompt.length).toBe(cut.characters);
      expect(prompt).not.toMatch(/\/(?:home|Users)\//);
      expect(prompt).not.toContain(checkpointText(original));
      expect(prompt).not.toContain("Retained suffix (fixture scaffolding, not historical evidence).");
      expect(prompt).not.toContain("Repository state (caller-captured after summary)");
    }
  });

  test("defaults to the latest compaction on the active branch, with explicit selection of another branch", () => {
    const branched = jsonl([...entries, user("resumed", "first", "Resumed another branch")]);
    expect(replayInput(branched).original.id).toBe("first");
    expect(replayInput(branched).prompt).toContain("Already summarized");
    expect(replayInput(branched).prompt).not.toContain("<previous-checkpoint>");
    expect(replayInput(branched, "second").original.id).toBe("second");
  });

  test("lists every recorded cut, including inactive branches and damaged boundaries", () => {
    const broken = { ...current, id: "broken", parentId: "tail", firstKeptEntryId: "missing" };
    const source = jsonl([...entries, broken, user("resumed", "first", "Other branch")]);
    expect(replayInput(source).original.id).toBe("first");
    const cuts = listCuts(source);
    expect(cuts.map(cut => cut.id)).toEqual(["first", "second", "broken"]);
    expect(cuts[0]).toMatchObject({ parentId: "retained", firstKeptEntryId: "retained", previous: false });
    expect(cuts[1]).toMatchObject({ parentId: "tail", firstKeptEntryId: "cut", previous: true, characters: replayInput(source, "second").prompt.length });
    expect(cuts[2].error).toContain("Recorded boundary missing");
    expect(listCuts(jsonl([header, user("only", null, "Hello")]))).toEqual([]);
  });

  test("SDK replay serialization keeps only the first 2000 tool-result characters, not the tail", () => {
    const head = "SOURCE HEAD " + "x".repeat(1988);
    const tail = "TAIL-ONLY AUTHORITY";
    const tool = { type: "message", id: "tool", parentId: "new", timestamp: header.timestamp,
      message: { role: "toolResult", toolCallId: "call", toolName: "read", content: [{ type: "text", text: head + tail }], isError: false, timestamp: 1 } };
    const source = jsonl([...entries.slice(0, 6), tool, user("cut", "tool", "Retained suffix"), { ...current, parentId: "cut" }]);
    const { prompt } = replayInput(source);
    expect(prompt).toContain(`[Tool result]: ${head}\n\n[... ${tail.length} more characters truncated]`);
    expect(prompt).not.toContain(tail);
    expect(source).toContain(tail);
  });

  test("offline listing returns before runtime creation and emits JSON lines without modifying the session", async () => {
    const temporary = mkdtempSync(join(tmpdir(), "replay-list-test-"));
    const log = spyOn(console, "log").mockImplementation(() => {});
    try {
      const path = join(temporary, "session.jsonl");
      const source = jsonl(entries);
      writeFileSync(path, source);
      await main(["--list-cuts", path], async () => { throw new Error("runtime creation forbidden"); });
      expect(log.mock.calls.map(([line]) => JSON.parse(line).id)).toEqual(["first", "second"]);
      expect(readFileSync(path, "utf8")).toBe(source);
    } finally { log.mockRestore(); rmSync(temporary, { recursive: true, force: true }); }
  });

  test.each(["default", "supplied"])("%s instructions reach the existing generation path with reproducible cut metadata", async mode => {
    const temporary = mkdtempSync(join(tmpdir(), "replay-instructions-test-"));
    const log = spyOn(console, "log").mockImplementation(() => {});
    const error = spyOn(console, "error").mockImplementation(() => {});
    let output;
    try {
      const path = join(temporary, "session with spaces.jsonl");
      const source = jsonl(entries);
      writeFileSync(path, source);
      const instructionsPath = join(temporary, "candidate instructions.md");
      const supplied = "Candidate instructions 🐟\nKeep these exact bytes.\n";
      writeFileSync(instructionsPath, supplied);
      const expected = mode === "default" ? readFileSync(COMPACTION_INSTRUCTIONS, "utf8") : supplied;
      const args = mode === "default" ? [path, "second"] : ["--instructions", instructionsPath, path, "second"];
      let request;
      let options;
      const modelLimit = mode === "default" ? 999999 : 123;
      output = await main(args, async () => ({
        find(provider, id) {
          expect({ provider, id }).toEqual(COMPACTION_MODEL);
          return { provider, id, maxTokens: modelLimit };
        },
        async complete(model, context, settings) {
          request = context;
          options = settings;
          return { stopReason: "stop", content: [{ type: "text", text: "## Objective and authority\nTest checkpoint" }], usage: { input: 12, output: 3 } };
        },
      }));
      expect(request.systemPrompt).toBe(expected);
      expect(request.messages[0].content[0].text).toBe(replayInput(source, "second").prompt);
      expect(options).toMatchObject({
        maxTokens: Math.min(Math.floor(0.8 * DEFAULT_COMPACTION_SETTINGS.reserveTokens), modelLimit),
        reasoningEffort: "low", cacheRetention: "none",
      });
      expect(readFileSync(join(output, "instructions.md"), "utf8")).toBe(expected);
      expect(readFileSync(join(output, "new.md"), "utf8")).toBe("## Objective and authority\nTest checkpoint");
      const metadata = JSON.parse(readFileSync(join(output, "replay.json"), "utf8"));
      const digest = text => createHash("sha256").update(text).digest("hex");
      expect(metadata.source).toEqual({ path, sha256: digest(source) });
      expect(metadata.cut).toEqual({ id: "second", timestamp: header.timestamp, parentId: "tail", firstKeptEntryId: "cut" });
      expect(metadata.input.sha256).toBe(digest(readFileSync(join(output, "input.txt"), "utf8")));
      expect(metadata.instructions).toEqual({ path: mode === "default" ? COMPACTION_INSTRUCTIONS : instructionsPath, sha256: digest(expected) });
      expect(metadata.settings).toEqual({ maxTokens: options.maxTokens, reasoningEffort: options.reasoningEffort, cacheRetention: options.cacheRetention, timeoutMs: 180000 });
      expect(readFileSync(path, "utf8")).toBe(source);
    } finally {
      log.mockRestore(); error.mockRestore();
      if (output) rmSync(output, { recursive: true, force: true });
      rmSync(temporary, { recursive: true, force: true });
    }
  });

  test("parseArgs rejects ambiguous listing modes, unknown options, and missing instruction values before a request", async () => {
    for (const args of [[], ["--list-cuts"], ["--list-cuts", "session", "cut"], ["--list-cuts", "--instructions", "candidate", "session"], ["--instructions"], ["--unknown", "session"], ["one", "two", "three"]]) {
      let requested = false;
      await expect(main(args, async () => { requested = true; throw new Error("unexpected runtime"); })).rejects.toThrow();
      expect(requested).toBe(false);
    }
  });

  test("rejects absent compactions and broken saved boundaries before requesting a model", () => {
    expect(() => replayInput(jsonl(entries), "new")).toThrow("No compaction entry new");
    expect(() => replayInput(jsonl([header, user("only", null, "Hello")]))).toThrow("No compaction on the active branch");
    expect(() => replayInput(jsonl([...entries.slice(0, -1), { ...current, firstKeptEntryId: "missing" }]))).toThrow("Recorded boundary missing");
  });

  test("keeps legacy checkpoint prose intact when no saved offset is available", () => {
    expect(checkpointText({ summary: "Legacy checkpoint" })).toBe("Legacy checkpoint");
    expect(checkpointText({ summary: "Legacy checkpoint", details: { checkpointLength: 999 } })).toBe("Legacy checkpoint");
  });

  test("direct invocation shows help and rejects a non-compacted session without changing its bytes", () => {
    const command = resolve("dev/replay-compaction");
    const help = Bun.spawnSync([command, "--help"]);
    expect(help.exitCode).toBe(0);
    expect(help.stdout.toString()).toContain("SESSION.jsonl [COMPACTION_ID]");
    const temporary = mkdtempSync(join(tmpdir(), "replay-test-"));
    try {
      const path = join(temporary, "session with spaces.jsonl");
      const source = jsonl([header, user("only", null, "No compaction yet")]);
      writeFileSync(path, source);
      const listed = Bun.spawnSync([command, "--list-cuts", path]);
      expect(listed.exitCode).toBe(0);
      expect(listed.stdout.toString()).toBe("");
      expect(listed.stderr.toString()).toBe("");
      writeFileSync(path, jsonl(entries));
      const cuts = Bun.spawnSync([command, "--list-cuts", path]);
      expect(cuts.exitCode).toBe(0);
      expect(cuts.stdout.toString().trim().split("\n").map(line => JSON.parse(line).id)).toEqual(["first", "second"]);
      expect(cuts.stderr.toString()).toBe("");
      expect(readFileSync(path, "utf8")).toBe(jsonl(entries));
      const missingInstructions = Bun.spawnSync([command, "--instructions", join(temporary, "missing.md"), path, "second"]);
      expect(missingInstructions.exitCode).toBe(1);
      expect(missingInstructions.stderr.toString()).toContain("missing.md");
      expect(missingInstructions.stderr.toString()).not.toContain("requesting");
      writeFileSync(path, source);
      const result = Bun.spawnSync([command, path]);
      expect(result.exitCode).toBe(1);
      expect(result.stderr.toString()).toContain("Replay failed: No compaction on the active branch");
      expect(result.stdout.toString()).toBe("");
      expect(readFileSync(path, "utf8")).toBe(source);
    } finally { rmSync(temporary, { recursive: true, force: true }); }
  }, 60000); // Fresh Pi SDK imports exceed Bun's default five-second test budget.
});
