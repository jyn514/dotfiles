import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, test } from "bun:test";
import { replayInput } from "../../dev/replay-compaction";
import { checkpointText } from "../../config/pi-agent/pi-extensions/luna-compaction";

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
      name: "investigation-only", target: "bc29caa4",
      required: [
        "look at the code, how would you design this?",
        "separate persistent clone acceptable",
        "investigate",
        'your "client" is just the proxy, rebuilt in-process. assume we keep the model proxy.',
        "could it be as simple as running on docker-compose or does codex-sandbox still provide value?",
      ],
    },
  ])("reconstructs source corrections and authority for $name without a model request", ({ name, target, required }) => {
    const { original, prompt } = replayInput(historicalFixture(name));
    expect(original.id).toBe(target);
    for (const text of required) expect(prompt).toContain(text);
    expect(prompt).not.toContain("Retained suffix (fixture scaffolding, not historical evidence).");
    expect(prompt).not.toContain("<previous-checkpoint>");
    expect(prompt).not.toContain(checkpointText(original));
  });

  test("repeated historical replays inherit the saved checkpoint while keeping later task authority at its recorded cut", () => {
    const source = historicalFixture("paused-repeated-compaction");
    const second = replayInput(source, "bf746f62");
    const third = replayInput(source);
    expect(third.original.id).toBe("e0fbef33");
    const first = replayInput(source, "8e424df8");
    expect(second.prompt).toContain(`<previous-checkpoint>\n${checkpointText(first.original)}\n</previous-checkpoint>`);
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
    expect(third.prompt).not.toContain("i was intending for the agent to be able to fork from *arbitrarily* far back");
    expect(third.prompt).not.toContain("Retained suffix (fixture scaffolding, not historical evidence).");
    expect(third.prompt).not.toContain("Implement the approved JJ dispatch plan:");
    expect(third.prompt).not.toContain("Repository state (caller-captured after summary)");
  });

  test("defaults to the latest compaction on the active branch, with explicit selection of another branch", () => {
    const branched = jsonl([...entries, user("resumed", "first", "Resumed another branch")]);
    expect(replayInput(branched).original.id).toBe("first");
    expect(replayInput(branched).prompt).toContain("Already summarized");
    expect(replayInput(branched).prompt).not.toContain("<previous-checkpoint>");
    expect(replayInput(branched, "second").original.id).toBe("second");
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
      const result = Bun.spawnSync([command, path]);
      expect(result.exitCode).toBe(1);
      expect(result.stderr.toString()).toContain("Replay failed: No compaction on the active branch");
      expect(result.stdout.toString()).toBe("");
      expect(readFileSync(path, "utf8")).toBe(source);
    } finally { rmSync(temporary, { recursive: true, force: true }); }
  }, 30000); // Two fresh Pi SDK imports exceed Bun's default five-second test budget.
});
