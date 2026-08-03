#!/usr/bin/env node

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  claudeShareId,
  extractClaudeTurns,
  formatTurns,
  loadTurns,
  parseArguments,
  readHtml,
  runSafariSnapshot,
} = require("../extract-chat-share");

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

test("recognizes canonical Claude share URLs", () => {
  assert.equal(
    claudeShareId(
      "https://claude.ai/share/334967a5-936b-4638-9e26-507b0c3b0210"
    ),
    "334967a5-936b-4638-9e26-507b0c3b0210"
  );
  assert.equal(
    claudeShareId(
      "https://claude.ai/chat/334967a5-936b-4638-9e26-507b0c3b0210"
    ),
    null
  );
  assert.equal(claudeShareId("https://claude.ai/share/not-a-uuid"), null);
  assert.equal(
    claudeShareId(
      "https://example.com/share/334967a5-936b-4638-9e26-507b0c3b0210"
    ),
    null
  );
});

test("extracts ordered Claude text turns and ignores tool blocks", () => {
  const turns = extractClaudeTurns({
    chat_messages: [
      {
        index: 2,
        sender: "assistant",
        content: [
          { type: "text", text: "Answer." },
          { type: "tool_use", name: "computer", input: {} },
        ],
      },
      {
        index: 1,
        sender: "human",
        content: [
          { type: "text", text: "First line." },
          { type: "text", text: "Second line." },
        ],
      },
      {
        index: 3,
        sender: "human",
        content: [{ type: "tool_result", content: "transport data" }],
      },
    ],
  });

  assert.deepEqual(turns, [
    { role: "user", text: "First line.\nSecond line." },
    { role: "assistant", text: "Answer." },
  ]);
});

test("loads Claude snapshots through Safari page context", async () => {
  const url =
    "https://claude.ai/share/334967a5-936b-4638-9e26-507b0c3b0210";
  const calls = [];
  const turns = await loadTurns(url, {
    runSafari: async (shareUrl, apiPath) => {
      calls.push({ shareUrl, apiPath });
      return JSON.stringify({
        ok: true,
        status: 200,
        body: JSON.stringify({
          chat_messages: [
            {
              index: 0,
              sender: "human",
              content: [{ type: "text", text: "Question." }],
            },
          ],
        }),
      });
    },
  });

  assert.deepEqual(turns, [{ role: "user", text: "Question." }]);
  assert.deepEqual(calls, [
    {
      shareUrl: url,
      apiPath:
        "/api/chat_snapshots/334967a5-936b-4638-9e26-507b0c3b0210" +
        "?rendering_mode=messages&render_all_tools=true",
    },
  ]);
});

test("rejects private Claude chat URLs", async () => {
  await assert.rejects(
    loadTurns(
      "https://claude.ai/chat/334967a5-936b-4638-9e26-507b0c3b0210",
      { runSafari: () => assert.fail("Private chat was opened") }
    ),
    /Expected a public Claude share URL/
  );
});

test("runs the Claude helper with bounded output buffering", async () => {
  const calls = [];
  const output = await runSafariSnapshot(
    "https://claude.ai/share/example",
    "/api/example",
    {
      platform: "darwin",
      execFile: (file, args, options, callback) => {
        calls.push({ file, args, options });
        callback(null, '{"ok":true}', "");
      },
    }
  );

  assert.equal(output, '{"ok":true}');
  assert.equal(calls[0].file, "/usr/bin/osascript");
  assert.match(calls[0].args[0], /extract-claude-share\.applescript$/);
  assert.deepEqual(calls[0].args.slice(1), [
    "https://claude.ai/share/example",
    "/api/example",
  ]);
  assert.equal(calls[0].options.maxBuffer, 64 * 1024 * 1024);
});

test("reports that Claude extraction requires macOS", async () => {
  await assert.rejects(
    runSafariSnapshot("https://claude.ai/share/example", "/api/example", {
      platform: "linux",
    }),
    /require Safari on macOS/
  );
});

test("reports Claude snapshot HTTP failures", async () => {
  await assert.rejects(
    loadTurns(
      "https://claude.ai/share/334967a5-936b-4638-9e26-507b0c3b0210",
      {
        runSafari: async () =>
          JSON.stringify({
            ok: false,
            status: 404,
            statusText: "Not Found",
            body: "",
          }),
      }
    ),
    /Could not fetch .*: 404 Not Found/
  );
});

test("rejects malformed Claude snapshot payloads", async () => {
  await assert.rejects(
    loadTurns(
      "https://claude.ai/share/334967a5-936b-4638-9e26-507b0c3b0210",
      {
        runSafari: async () =>
          JSON.stringify({ ok: true, status: 200, body: "{}" }),
      }
    ),
    /Could not find Claude share conversation messages/
  );
});
