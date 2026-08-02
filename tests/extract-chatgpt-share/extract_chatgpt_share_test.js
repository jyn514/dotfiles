#!/usr/bin/env node

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  formatTurns,
  parseArguments,
  readHtml,
} = require("../../bin/extract-chatgpt-share");

test("customizes user and assistant headings", () => {
  const command = parseArguments([
    "--user-heading",
    "Question",
    "saved-chat.html",
    "--assistant-heading=Answer",
  ]);

  assert.deepEqual(command, {
    input: "saved-chat.html",
    headings: { user: "Question", assistant: "Answer" },
  });
  assert.equal(
    formatTurns(
      [
        { role: "user", text: "Why?" },
        { role: "assistant", text: "Because." },
      ],
      command.headings
    ),
    "## Question\n\nWhy?\n\n## Answer\n\nBecause.\n\n"
  );
});

test("readHtml fetches HTTP URLs", async () => {
  const calls = [];
  const html = await readHtml("https://chatgpt.com/share/example", {
    fetch: async (url) => {
      calls.push(url);
      return { ok: true, text: async () => "<html>shared chat</html>" };
    },
    readFile: () => assert.fail("URL was read as a local file"),
  });

  assert.equal(html, "<html>shared chat</html>");
  assert.deepEqual(calls, ["https://chatgpt.com/share/example"]);
});

test("readHtml reports unsuccessful HTTP responses", async () => {
  await assert.rejects(
    readHtml("https://chatgpt.com/share/missing", {
      fetch: async () => ({ ok: false, status: 404, statusText: "Not Found" }),
      readFile: () => assert.fail("URL was read as a local file"),
    }),
    /Could not fetch https:\/\/chatgpt\.com\/share\/missing: 404 Not Found/
  );
});

test("readHtml retains local file input", async () => {
  const html = await readHtml("saved-chat.html", {
    fetch: () => assert.fail("Local file was fetched"),
    readFile: (file, encoding) => {
      assert.equal(file, "saved-chat.html");
      assert.equal(encoding, "utf8");
      return "<html>saved chat</html>";
    },
  });

  assert.equal(html, "<html>saved chat</html>");
});
