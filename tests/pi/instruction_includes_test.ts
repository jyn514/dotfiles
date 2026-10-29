import { afterEach, describe, expect, test } from "bun:test";
import { mkdtemp, mkdir, readFile, rename, rm, stat, symlink, utimes, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import instructionIncludes, { expandInstructionIncludes } from "../../config/pi-agent/pi-extensions/pi-instruction-includes";

const temporaryDirectories: string[] = [];

async function fixture(): Promise<string> {
  const path = await mkdtemp(join(tmpdir(), "pi-includes-"));
  temporaryDirectories.push(path);
  return path;
}

const updates = ["atomic replacement", "in-place write"] as const;
type Update = typeof updates[number];

async function initialGuidance(path: string): Promise<void> {
  await writeFile(path, "Old guidance");
  // Use an exactly representable time so restoring it does not round filesystem precision.
  await utimes(path, 1_700_000_000, 1_700_000_000);
}

async function updateGuidance(path: string, update: Update): Promise<void> {
  const before = await stat(path);
  const destination = update === "atomic replacement" ? `${path}.replacement` : path;
  await writeFile(destination, "New guidance");
  await utimes(destination, before.atime, before.mtime);
  if (update === "atomic replacement") await rename(destination, path);

  const after = await stat(path);
  expect(after.size).toBe(before.size);
  expect(after.mtimeMs).toBe(before.mtimeMs);
  if (update === "atomic replacement") expect(after.ino).not.toBe(before.ino);
  else expect(after.ino).toBe(before.ino);
}

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true })));
});

describe("instruction includes", () => {
  test.each(updates)("refreshes guidance after %s without forcing the prompt and clears absent includes", async (update) => {
    const root = await fixture();
    const rules = join(root, "rules.md");
    await initialGuidance(rules);
    const event = {
      systemPrompt: "Base instructions.",
      systemPromptOptions: {
        cwd: root,
        contextFiles: [{ path: join(root, "AGENTS.md"), content: "@rules.md" }],
        sections: { other: "other guidance", instruction_includes: "stale" },
      },
    };
    let handler: (input: typeof event) => Promise<unknown>;
    instructionIncludes({
      on(name: string, callback: typeof handler) {
        expect(name).toBe("before_agent_start");
        handler = callback;
      },
    } as never);
    for (let turn = 0; turn < 2; turn++) {
      expect(await handler!(event)).toBeUndefined();
      expect(event.systemPrompt).toBe("Base instructions.");
      expect(event.systemPromptOptions.sections).toEqual({
        other: "other guidance",
        instruction_includes: expect.stringContaining("## Expanded instruction includes\n\n"),
      });
      expect(event.systemPromptOptions.sections.instruction_includes).toContain(turn === 0 ? "Old guidance" : "New guidance");
      expect(event.systemPromptOptions.sections.instruction_includes).not.toContain(turn === 0 ? "New guidance" : "Old guidance");
      if (turn === 0) await updateGuidance(rules, update);
    }
    event.systemPromptOptions.contextFiles = [];
    expect(await handler!(event)).toBeUndefined();
    expect(event.systemPrompt).toBe("Base instructions.");
    expect(event.systemPromptOptions.sections).toEqual({ other: "other guidance" });
  });

  test.each(updates)("reads current include content after %s with unchanged size and mtime", async (update) => {
    const root = await fixture();
    const rules = join(root, "rules.md");
    await initialGuidance(rules);
    const context = [{ path: join(root, "AGENTS.md"), content: "@rules.md" }];

    expect(await expandInstructionIncludes(context, root)).toEqual([expect.stringContaining("Old guidance")]);
    await updateGuidance(rules, update);
    const expanded = await expandInstructionIncludes(context, root);
    expect(expanded).toEqual([expect.stringContaining("New guidance")]);
    expect(expanded[0]).not.toContain("Old guidance");
  });

  test("expands nested relative includes in declaration order", async () => {
    const root = await fixture();
    await mkdir(join(root, "rules"));
    await writeFile(join(root, "rules", "first.md"), "first\n@nested.md\n");
    await writeFile(join(root, "rules", "nested.md"), "nested\n");
    await writeFile(join(root, "rules", "second.md"), "second\n");

    const result = await expandInstructionIncludes(
      [{ path: join(root, "AGENTS.md"), content: "@rules/first.md\n@rules/second.md" }],
      root,
    );

    expect(result).toHaveLength(2);
    expect(result[0]).toContain("first\n@nested.md");
    expect(result[0]).toContain("nested");
    expect(result[0].indexOf("first")).toBeLessThan(result[0].indexOf("nested"));
    expect(result[1]).toContain("second");
  });

  test("expands host Pi's shared instruction route", async () => {
    const home = await fixture();
    const agent = join(home, ".pi", "agent");
    const shared = join(home, ".agents");
    await mkdir(agent, { recursive: true });
    await mkdir(shared, { recursive: true });
    await writeFile(join(shared, "shared.md"), "Shared");
    const content = await readFile(join(import.meta.dir, "../../config/pi-agent/AGENTS.md"), "utf8");
    expect(content.split(/\r?\n/)).toContain("@../../.agents/shared.md");

    const result = await expandInstructionIncludes(
      [{ path: join(agent, "AGENTS.md"), content }],
      agent,
    );

    expect(result).toEqual([expect.stringContaining("Shared")]);
  });

  test("ignores directives inside fenced code blocks", async () => {
    const root = await fixture();
    const result = await expandInstructionIncludes(
      [{ path: join(root, "AGENTS.md"), content: "```md\n@missing.md\n```" }],
      root,
    );
    expect(result).toEqual([]);
  });

  test("fails on missing includes", async () => {
    const root = await fixture();
    await expect(expandInstructionIncludes(
      [{ path: join(root, "AGENTS.md"), content: "@missing.md" }], root,
    )).rejects.toThrow("does not exist");
  });

  test("fails with the complete cycle", async () => {
    const root = await fixture();
    await writeFile(join(root, "a.md"), "@b.md\n");
    await writeFile(join(root, "b.md"), "@a.md\n");
    await expect(expandInstructionIncludes(
      [{ path: join(root, "AGENTS.md"), content: "@a.md" }], root,
    )).rejects.toThrow(/a\.md -> .*b\.md -> .*a\.md/);
  });

  test("allows sibling includes through a symlinked context tree", async () => {
    const visible = await fixture();
    const source = await fixture();
    await writeFile(join(source, "AGENTS.md"), "@breq.md\n");
    await writeFile(join(source, "breq.md"), "Breq\n");
    await symlink(join(source, "AGENTS.md"), join(visible, "AGENTS.md"));
    await symlink(join(source, "breq.md"), join(visible, "breq.md"));

    const result = await expandInstructionIncludes(
      [{ path: join(visible, "AGENTS.md"), content: "@breq.md" }],
      visible,
    );

    expect(result).toHaveLength(1);
    expect(result[0]).toContain("Breq");
  });

  test("allows includes outside the context tree", async () => {
    const root = await fixture();
    const outside = await fixture();
    await writeFile(join(outside, "shared.md"), "shared");

    const result = await expandInstructionIncludes(
      [{ path: join(root, "AGENTS.md"), content: `@${join(outside, "shared.md")}` }],
      root,
    );

    expect(result).toHaveLength(1);
    expect(result[0]).toContain("shared");
  });

  test("rejects invalid UTF-8", async () => {
    const root = await fixture();
    await Bun.write(join(root, "bad.md"), new Uint8Array([0xff]));
    await expect(expandInstructionIncludes(
      [{ path: join(root, "AGENTS.md"), content: "@bad.md" }], root,
    )).rejects.toThrow("not valid UTF-8");
  });
});
