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
