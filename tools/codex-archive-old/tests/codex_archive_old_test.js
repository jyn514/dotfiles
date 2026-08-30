#!/usr/bin/env node

const assert = require("node:assert/strict");
const path = require("node:path");
const tool = require(path.join(__dirname, "..", "codex-archive-old"));

assert.deepEqual(tool.parseArgs([]), { days: 7, apply: false });
assert.deepEqual(tool.parseArgs(["--days", "30", "--apply"]), { days: 30, apply: true });
assert.throws(() => tool.parseArgs(["--days", "0"]), /positive whole number/);
assert.throws(() => tool.parseArgs(["--unknown"]), /unknown argument/);

(async () => {
  const requests = [];
  const pages = [
    { data: [{ id: "old-1", updatedAt: 10 }, { id: "old-2", updatedAt: 20 }], nextCursor: "next" },
    { data: [{ id: "new", updatedAt: 100 }], nextCursor: "ignored" },
  ];
  const client = { request: async (method, params) => { requests.push([method, params]); return pages.shift(); } };
  assert.deepEqual(await tool.listOldThreads(client, 50), [
    { id: "old-1", updatedAt: 10 },
    { id: "old-2", updatedAt: 20 },
  ]);
  assert.equal(requests.length, 2);
  assert.equal(requests[1][1].cursor, "next");

  const pending = new Map();
  let resolved = null;
  pending.set(1, { resolve: value => { resolved = value; }, reject: assert.fail });
  tool.AppServerClient.prototype.receive.call({ pending }, JSON.stringify({ method: "server/request", id: 1 }));
  assert.equal(resolved, null);
  assert.equal(pending.has(1), true);
  tool.AppServerClient.prototype.receive.call({ pending }, JSON.stringify({ id: 1, result: "ok" }));
  assert.equal(resolved, "ok");
  assert.equal(pending.has(1), false);
})().catch(error => { console.error(error); process.exitCode = 1; });
