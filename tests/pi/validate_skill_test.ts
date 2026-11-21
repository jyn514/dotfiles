import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { EventEmitter } from "node:events";
import validateSkill, { createValidateSkillTool, validateSkillWorker } from "../../config/pi-agent/pi-extensions/validate-skill";

let cwd: string;
beforeEach(() => { cwd = mkdtempSync(join(tmpdir(), "validate-skill-test-")); });
afterEach(() => { rmSync(cwd, { recursive: true, force: true }); });

async function check(path = "SKILL.md") {
  const result = await createValidateSkillTool().execute("test", { path }, undefined, undefined, { cwd } as never);
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
    validateSkill({ registerTool: (tool: unknown) => tools.push(tool), events: new EventEmitter(), on() {} } as never);
    expect(tools).toHaveLength(1);
    expect((tools[0] as { name: string }).name).toBe("validate_skill");
  });

  test("worker uses its supplied Pi module and execution environment", async () => {
    const modulePath = join(cwd, "worker-pi.mjs");
    writeFileSync(modulePath, `
      export function loadSkills(options) {
        return { skills: [{ name: options.cwd + ':' + options.agentDir + ':' + options.skillPaths[0] }], diagnostics: [{ type: 'warning', message: 'worker diagnostic' }] };
      }
      export function truncateHead() { return { content: 'worker truncation', truncated: true }; }
    `);
    const result = await validateSkillWorker({ path: "@SKILL.md" }, {
      cwd, agentDir: "/guest-agent", piModule: modulePath, model: null, session: null,
      signal: new AbortController().signal, onUpdate() {},
    });
    expect(result.details).toEqual({ loaded: true, name: `${cwd}:/guest-agent:SKILL.md`, diagnostics: [{ type: "warning", message: "worker diagnostic" }] });
    expect(result.content[0].text).toBe("worker truncation\n[Output truncated; full diagnostics are in result details.]");
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
