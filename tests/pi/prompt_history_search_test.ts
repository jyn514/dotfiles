import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  collectPromptHistory,
  listPromptHistoryFiles,
  loadPromptHistoryFiles,
  loadPromptHistoryWithRipgrep,
  mergePromptHistories,
  searchPromptHistory,
} from "../../config/pi-agent/pi-extensions/prompt-history-search-core";

describe("prompt history collection", () => {
  test("returns newest unique user prompts and joins text blocks", () => {
    const entries = [
      { type: "message", message: { role: "user", content: "first", timestamp: 1 } },
      { type: "message", message: { role: "assistant", content: "ignored" } },
      {
        type: "message",
        message: {
          role: "user",
          content: [
            { type: "text", text: "second" },
            { type: "image", data: "ignored" },
            { type: "text", text: "line" },
          ],
          timestamp: 2,
        },
      },
      { type: "message", message: { role: "user", content: "first", timestamp: 3 } },
    ];

    expect(collectPromptHistory(entries)).toEqual([
      { text: "first", timestamp: 3 },
      { text: "second\nline", timestamp: 2 },
    ]);
  });

  test("ignores empty and malformed entries", () => {
    expect(collectPromptHistory([
      null,
      { type: "message", message: { role: "user", content: "  " } },
      { type: "custom", data: {} },
    ])).toEqual([]);
  });
});

describe("prompt history files", () => {
  test("scans each session once and ignores unrelated or damaged lines", async () => {
    const root = await mkdtemp(join(tmpdir(), "prompt-history-"));
    try {
      const project = join(root, "--project--");
      await mkdir(project);
      const first = join(project, "first.jsonl");
      const second = join(project, "second.jsonl");
      await writeFile(first, [
        JSON.stringify({ type: "session", version: 3, id: "one" }),
        JSON.stringify({ type: "message", message: { role: "assistant", content: "large ignored output" } }),
        JSON.stringify({ type: "message", message: { role: "user", content: "older", timestamp: 1 } }),
        "damaged line with \"role\":\"user\"",
      ].join("\n"));
      await writeFile(second, [
        JSON.stringify({ type: "session", version: 3, id: "two" }),
        JSON.stringify({ type: "message", message: { role: "user", content: "newer", timestamp: 2 } }),
      ].join("\n"));

      const files = await listPromptHistoryFiles(root);
      expect(files.sort()).toEqual([first, second]);
      expect(await loadPromptHistoryFiles(files, first)).toEqual([
        { text: "newer", timestamp: 2 },
      ]);
      expect(await loadPromptHistoryWithRipgrep(root, first)).toEqual([
        { text: "newer", timestamp: 2 },
      ]);
      expect(await loadPromptHistoryWithRipgrep(root)).toEqual([
        { text: "newer", timestamp: 2 },
        { text: "older", timestamp: 1 },
      ]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("ripgrep history transport", () => {
  test("returns no matches and rejects search errors for the caller's fallback", async () => {
    const root = await mkdtemp(join(tmpdir(), "prompt-history-rg-"));
    try {
      expect(await loadPromptHistoryWithRipgrep(root)).toEqual([]);
      await expect(loadPromptHistoryWithRipgrep(join(root, "missing"))).rejects.toThrow(
        "ripgrep exited with status 2",
      );
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("decodes ripgrep's base64 byte fields before comparing paths and parsing prompts", async () => {
    const root = await mkdtemp(join(tmpdir(), "prompt-history-rg-bytes-"));
    const previousPath = process.env.PATH;
    try {
      process.env.PATH = `${root}:${previousPath}`;
      const excludedPath = join(root, "line\nfeed.jsonl");
      const record = (path: string, text: string, timestamp: number) => JSON.stringify({
        type: "match", data: {
          path: { bytes: Buffer.from(path).toString("base64") },
          lines: { bytes: Buffer.from(JSON.stringify({
            type: "message", message: { role: "user", content: text, timestamp },
          }) + "\n").toString("base64") },
        },
      });
      const output = [
        record(excludedPath, "excluded", 20),
        record(join(root, "saved.jsonl"), "visible\nλ", 10),
      ].join("\n") + "\n";
      await writeFile(join(root, "rg"),
        `#!/usr/bin/env node\nprocess.stdout.write(${JSON.stringify(output)});\n`, { mode: 0o755 });
      expect(await loadPromptHistoryWithRipgrep(root, excludedPath)).toEqual([
        { text: "visible\nλ", timestamp: 10 },
      ]);
    } finally {
      if (previousPath === undefined) delete process.env.PATH;
      else process.env.PATH = previousPath;
      await rm(root, { recursive: true, force: true });
    }
  });

  test("rejects malformed ripgrep records instead of throwing from the line callback", async () => {
    const root = await mkdtemp(join(tmpdir(), "prompt-history-rg-output-"));
    const previousPath = process.env.PATH;
    try {
      process.env.PATH = `${root}:${previousPath}`;
      for (const output of ["not JSON\n", JSON.stringify({ type: "match", data: {} }) + "\n"]) {
        await writeFile(join(root, "rg"),
          `#!/usr/bin/env node\nprocess.stdout.write(${JSON.stringify(output)});\n`, { mode: 0o755 });
        await expect(loadPromptHistoryWithRipgrep(root)).rejects.toThrow();
      }
    } finally {
      if (previousPath === undefined) delete process.env.PATH;
      else process.env.PATH = previousPath;
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("prompt history merge", () => {
  test("deduplicates across sessions and keeps the newest occurrence", () => {
    expect(mergePromptHistories([
      [
        { text: "shared", timestamp: 10 },
        { text: "old", timestamp: 5 },
      ],
      [
        { text: "new", timestamp: 20 },
        { text: "shared", timestamp: 15 },
      ],
    ])).toEqual([
      { text: "new", timestamp: 20 },
      { text: "shared", timestamp: 15 },
      { text: "old", timestamp: 5 },
    ]);
  });
});

describe("prompt history search", () => {
  const prompts = [
    { text: "fix the parser tests" },
    { text: "document parser behavior" },
    { text: "review the shell script" },
  ];

  test("matches every case-insensitive query term", () => {
    expect(searchPromptHistory(prompts, "PARSER fix")).toEqual([
      { text: "fix the parser tests" },
    ]);
  });

  test("preserves newest-first order for an empty query", () => {
    expect(searchPromptHistory(prompts, "   ")).toEqual(prompts);
  });
});
