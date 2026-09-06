import { afterEach, describe, expect, test } from "bun:test";
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { expandInstructionIncludes } from "../../config/pi-extensions/pi-instruction-includes";

const temporaryDirectories: string[] = [];

async function fixture(): Promise<string> {
  const path = await mkdtemp(join(tmpdir(), "pi-includes-"));
  temporaryDirectories.push(path);
  return path;
}

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true })));
});

describe("instruction includes", () => {
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

  test("expands the sandboxed Pi instruction layout", async () => {
    const home = await fixture();
    const agent = join(home, ".pi", "agent");
    const shared = join(home, ".agents");
    await mkdir(agent, { recursive: true });
    await mkdir(shared, { recursive: true });
    await writeFile(join(agent, "breq.md"), "Breq");
    await writeFile(join(agent, "coordination-dialect.md"), "Coordination");
    await writeFile(join(shared, "shared.md"), "Shared");
    const content = await readFile(join(import.meta.dir, "../../config/pi-AGENTS.md"), "utf8");

    const result = await expandInstructionIncludes(
      [{ path: join(agent, "AGENTS.md"), content }],
      agent,
    );

    expect(result).toHaveLength(3);
    expect(result[2]).toContain("Shared");
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
