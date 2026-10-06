import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { discoverAndLoadExtensions } from "@earendil-works/pi-coding-agent";
import validateSkill, { validateSkillTool } from "../../config/pi-agent/pi-extensions/validate-skill";

let cwd: string;
beforeEach(() => { cwd = mkdtempSync(join(tmpdir(), "validate-skill-test-")); });
afterEach(() => { rmSync(cwd, { recursive: true, force: true }); });

async function check(path = "SKILL.md") {
  const result = await validateSkillTool.execute("test", { path }, undefined, undefined, { cwd } as never);
  expect(JSON.parse((result.content[0] as { text: string }).text)).toEqual(
    JSON.parse(JSON.stringify(result.details)),
  );
  return result.details;
}

function skill(contents = "---\nname: example\ndescription: An example skill.\n---\n\n# Example\n") {
  writeFileSync(join(cwd, "SKILL.md"), contents);
}

describe("validate_skill", () => {
  test("registers the tool", () => {
    const tools: unknown[] = [];
    validateSkill({ registerTool: (tool: unknown) => tools.push(tool) } as never);
    expect(tools).toEqual([validateSkillTool]);
  });

  test("Pi loads the bundle and exposes a working validate_skill tool", async () => {
    const loaded = await discoverAndLoadExtensions(
      [resolve("config/pi-agent/pi-extensions/index.ts")], cwd, join(cwd, "agent"),
    );
    expect(loaded.errors).toEqual([]);
    const tool = loaded.extensions[0]?.tools.get("validate_skill")?.definition;
    expect(tool).toBeDefined();
    skill();
    const result = await tool!.execute("test", { path: "SKILL.md" }, undefined, undefined, { cwd } as never);
    expect(result.details).toEqual({ loaded: true, name: "example", diagnostics: [] });
  });

  test("loads relative and absolute paths without changing the file", async () => {
    skill();
    const before = readFileSync(join(cwd, "SKILL.md"), "utf8");
    for (const path of ["SKILL.md", join(cwd, "SKILL.md"), "@SKILL.md"]) {
      expect(await check(path)).toEqual({ loaded: true, name: "example", diagnostics: [] });
    }
    expect(readFileSync(join(cwd, "SKILL.md"), "utf8")).toBe(before);
  });

  test("retains warnings when Pi still accepts the skill", async () => {
    skill("---\nname: InvalidName\ndescription: An example skill.\n---\n\n# Example\n");
    const result = await check();
    expect(result.loaded).toBe(true);
    expect(result.name).toBe("InvalidName");
    expect(result.diagnostics.length).toBeGreaterThan(0);
  });

  test("rejects missing descriptions and malformed frontmatter with diagnostics", async () => {
    for (const contents of ["---\nname: example\n---\n\n# Example\n", "---\nname: [\n---\n"]) {
      skill(contents);
      const result = await check();
      expect(result.loaded).toBe(false);
      expect(result.name).toBeUndefined();
      expect(result.diagnostics.length).toBeGreaterThan(0);
    }
  });

  test("does not load unrelated default skills when the target is missing", async () => {
    const defaults = join(cwd, ".pi", "skills", "other");
    mkdirSync(defaults, { recursive: true });
    writeFileSync(join(defaults, "SKILL.md"), "---\nname: other\ndescription: Another skill.\n---\n");
    const result = await check();
    expect(result.loaded).toBe(false);
    expect(result.name).toBeUndefined();
    expect(result.diagnostics).toEqual([
      { type: "warning", message: "skill path does not exist", path: join(cwd, "SKILL.md") },
    ]);
  });
});
