#!/usr/bin/env node
// Offline Codex app-server fixture. Invoked directly by unit tests, or copied
// onto an isolated PATH as `codex` by installed-Pi tests. Never uses credentials.
import assert from "node:assert/strict";
import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { createInterface } from "node:readline";

const scenario = process.env.USAGE_FIXTURE_SCENARIO ?? "success";
const trace = process.env.USAGE_FIXTURE_TRACE;
const payload = JSON.parse(readFileSync(process.env.USAGE_FIXTURE_PAYLOAD ?? new URL("./subscription-usage.json", import.meta.url)));
const record = (value) => { if (trace) appendFileSync(trace, JSON.stringify(value) + "\n"); };
record({ pid: process.pid, args: process.argv.slice(2) });
if (scenario === "timeout-ignore-term") process.on("SIGTERM", () => record({ signal: "SIGTERM" }));
else process.on("SIGTERM", () => { record({ signal: "SIGTERM" }); process.exit(0); });
process.stderr.write("private-fixture-diagnostic-token\n");
const reply = (id, result) => process.stdout.write(JSON.stringify({ id, result }) + "\n");
let initialized = false;
let greeted = false;

for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
  const message = JSON.parse(line);
  record(message);
  if (message.method === "initialize") {
    assert.equal(greeted, false);
    assert.equal(typeof message.params.clientInfo.name, "string");
    assert.equal(typeof message.params.clientInfo.version, "string");
    greeted = true;
    if (scenario === "early-exit") process.exit(3);
    if (scenario === "stdin-close") { process.stdin.destroy(); process.stdout.destroy(); continue; }
    if (scenario === "timeout" || scenario === "timeout-ignore-term") continue;
    if (scenario === "invalid-json") { process.stdout.write("private-invalid-json\n"); continue; }
    if (scenario === "oversize") { process.stdout.write("x".repeat(1024 * 1024 + 1)); continue; }
    reply(message.id, {});
  } else if (message.method === "initialized") {
    assert.equal(greeted, true);
    initialized = true;
  } else {
    assert.equal(initialized, true);
    assert.equal(message.method, "account/rateLimits/read", "no login, model, or redemption requests");
    assert.deepEqual(message.params, { excludeResetCreditDetails: true }, "no Reserve opt-in");
    if (scenario === "rpc-auth" || scenario === "rpc-method" || scenario === "rpc-private") {
      process.stdout.write(JSON.stringify({ id: message.id, error: {
        code: scenario === "rpc-method" ? -32601 : -32600,
        message: scenario === "rpc-auth" ? "codex account authentication required to read rate limits" : "private-fixture-error-token",
      } }) + "\n");
      continue;
    }
    // Both interleaved notifications and unrelated responses must be ignored.
    process.stdout.write(JSON.stringify({ method: "account/updated", params: {} }) + "\n");
    reply(999, { private: "unrelated-response" });
    if (scenario === "missing-result") { process.stdout.write(JSON.stringify({ id: message.id }) + "\n"); continue; }
    if (scenario === "hold") {
      const release = process.env.USAGE_FIXTURE_RELEASE;
      while (!existsSync(release)) await new Promise((resolve) => setTimeout(resolve, 5));
    }
    if (scenario === "chunked") {
      const wire = Buffer.from(JSON.stringify({ id: message.id, result: { ...payload, ignored: "🦀" } }) + "\n");
      for (let i = 0; i < wire.length; i += 3) {
        process.stdout.write(wire.subarray(i, i + 3));
        await new Promise((resolve) => setTimeout(resolve, 1));
      }
    } else reply(message.id, payload);
  }
}
if (scenario === "timeout-ignore-term") setInterval(() => {}, 1000);
