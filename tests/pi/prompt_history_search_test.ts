import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  collectPromptHistory,
  listPromptHistoryFiles,
  loadPromptHistoryFiles,
  mergePromptHistories,
  searchPromptHistory,
} from "../../config/pi-extensions/prompt-history-search-core";

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
    } finally {
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
