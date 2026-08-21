import { afterEach, describe, expect, test } from "bun:test";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
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

  test("rejects traversal and symlink escapes", async () => {
    const root = await fixture();
    const outside = await fixture();
    await writeFile(join(outside, "secret.md"), "secret");
    await symlink(join(outside, "secret.md"), join(root, "escape.md"));

    await expect(expandInstructionIncludes(
      [{ path: join(root, "AGENTS.md"), content: "@escape.md" }], root,
    )).rejects.toThrow("escapes allowed roots");
  });

  test("rejects invalid UTF-8", async () => {
    const root = await fixture();
    await Bun.write(join(root, "bad.md"), new Uint8Array([0xff]));
    await expect(expandInstructionIncludes(
      [{ path: join(root, "AGENTS.md"), content: "@bad.md" }], root,
    )).rejects.toThrow("not valid UTF-8");
  });
});
