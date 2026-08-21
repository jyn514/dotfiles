import { describe, expect, test } from "bun:test";
import {
  collectPromptHistory,
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
