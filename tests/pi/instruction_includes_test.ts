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
  test.each([false, true])("ROOT instructions are root-only (managed child=%s)", async (child) => {
    const agentDir = await fixture();
    const saved = { directory: process.env.PI_CODING_AGENT_DIR, child: process.env.PI_SUBAGENT_ID };
    process.env.PI_CODING_AGENT_DIR = agentDir;
    if (child) process.env.PI_SUBAGENT_ID = "managed-worker";
    else delete process.env.PI_SUBAGENT_ID;
    try {
      await writeFile(join(agentDir, "ROOT.md"), "Root role\n@root-detail.md\n");
      await writeFile(join(agentDir, "root-detail.md"), "Root detail");
      await writeFile(join(agentDir, "shared.md"), "Shared working rules");
      const event = {
        systemPromptOptions: {
          cwd: agentDir,
          contextFiles: [{ path: join(agentDir, "AGENTS.md"), content: "@shared.md" }],
          sections: {} as Record<string, string>,
        },
      };
      let handler!: (input: typeof event) => Promise<unknown>;
      instructionIncludes({ on(_name: string, callback: typeof handler) { handler = callback; } } as never);
      await handler(event);
      expect(event.systemPromptOptions.contextFiles.some((file) => file.content.includes("Root role"))).toBe(!child);
      const expanded = event.systemPromptOptions.sections.instruction_includes;
      expect(expanded).toContain("Shared working rules");
      expect(expanded.includes("Root detail")).toBe(!child);
      await handler(event);
      expect(event.systemPromptOptions.contextFiles.filter((file) => file.path === join(agentDir, "ROOT.md")))
        .toHaveLength(child ? 0 : 1);
    } finally {
      if (saved.directory === undefined) delete process.env.PI_CODING_AGENT_DIR;
      else process.env.PI_CODING_AGENT_DIR = saved.directory;
      if (saved.child === undefined) delete process.env.PI_SUBAGENT_ID;
      else process.env.PI_SUBAGENT_ID = saved.child;
    }
  });

  test("ROOT refreshes without duplicates and disappears when removed or running as a child", async () => {
    const agentDir = await fixture();
    const saved = { directory: process.env.PI_CODING_AGENT_DIR, child: process.env.PI_SUBAGENT_ID };
    process.env.PI_CODING_AGENT_DIR = agentDir;
    delete process.env.PI_SUBAGENT_ID;
    try {
      const rootFile = join(agentDir, "ROOT.md");
      const event = { systemPromptOptions: {
        cwd: agentDir, contextFiles: [] as { path: string; content: string }[], sections: {},
      } };
      let handler!: (input: typeof event) => Promise<unknown>;
      instructionIncludes({ on(_name: string, callback: typeof handler) { handler = callback; } } as never);
      await handler(event);
      expect(event.systemPromptOptions.contextFiles).toEqual([]);
      await initialGuidance(rootFile);
      await handler(event);
      expect(event.systemPromptOptions.contextFiles).toEqual([{ path: rootFile, content: "Old guidance" }]);
      await updateGuidance(rootFile, "in-place write");
      await handler(event);
      expect(event.systemPromptOptions.contextFiles).toEqual([{ path: rootFile, content: "New guidance" }]);
      process.env.PI_SUBAGENT_ID = "managed-worker";
      await handler(event);
      expect(event.systemPromptOptions.contextFiles).toEqual([]);
      delete process.env.PI_SUBAGENT_ID;
      await handler(event);
      expect(event.systemPromptOptions.contextFiles).toHaveLength(1);
      await rm(rootFile);
      await handler(event);
      expect(event.systemPromptOptions.contextFiles).toEqual([]);
    } finally {
      if (saved.directory === undefined) delete process.env.PI_CODING_AGENT_DIR;
      else process.env.PI_CODING_AGENT_DIR = saved.directory;
      if (saved.child === undefined) delete process.env.PI_SUBAGENT_ID;
      else process.env.PI_SUBAGENT_ID = saved.child;
    }
  });

  test("ROOT read errors other than absence remain visible", async () => {
    const agentDir = await fixture();
    const saved = { directory: process.env.PI_CODING_AGENT_DIR, child: process.env.PI_SUBAGENT_ID };
    process.env.PI_CODING_AGENT_DIR = agentDir;
    delete process.env.PI_SUBAGENT_ID;
    try {
      const rootFile = join(agentDir, "ROOT.md");
      const event = { systemPromptOptions: { cwd: agentDir, contextFiles: [], sections: {} } };
      let handler!: (input: typeof event) => Promise<unknown>;
      instructionIncludes({ on(_name: string, callback: typeof handler) { handler = callback; } } as never);
      await mkdir(rootFile);
      await expect(handler(event)).rejects.toThrow("not a file");
      await rm(rootFile, { recursive: true });
      await Bun.write(rootFile, new Uint8Array([0xff]));
      await expect(handler(event)).rejects.toThrow("not valid UTF-8");
    } finally {
      if (saved.directory === undefined) delete process.env.PI_CODING_AGENT_DIR;
      else process.env.PI_CODING_AGENT_DIR = saved.directory;
      if (saved.child === undefined) delete process.env.PI_SUBAGENT_ID;
      else process.env.PI_SUBAGENT_ID = saved.child;
    }
  });

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
