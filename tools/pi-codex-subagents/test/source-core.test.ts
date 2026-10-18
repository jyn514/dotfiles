import { expect, test } from "bun:test";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { AgentSession, createAgentSession, runRpcMode } from "@earendil-works/pi-coding-agent";

// This suite is deliberately opt-in: ordinary repository discovery reports skips,
// rather than accidentally claiming that stale installed Pi was exercised.
const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);

sourceTest("source aliases select changed core public APIs, including compat", () => {
  const root = process.env.PI_TEST_CORE_ROOT;
  expect(root).toBeTruthy();
  expect(import.meta.resolve("@earendil-works/pi-coding-agent")).toBe(`file://${root}/packages/coding-agent/src/index.ts`);
  expect(import.meta.resolve("@earendil-works/pi-agent-core")).toBe(`file://${root}/packages/agent/src/index.ts`);
  expect(import.meta.resolve("@earendil-works/pi-ai/compat")).toBe(`file://${root}/packages/ai/src/compat.ts`);
  expect(typeof AgentSession.prototype.requestPause).toBe("function");
  expect(typeof createAgentSession).toBe("function");
  expect(typeof runRpcMode).toBe("function");
});

sourceTest("wrapper runs real AgentSession through shipped RPC with a local faux provider", async () => {
  if (!process.env.PI_TEST_OWNED_ROOT || !process.env.PI_SUBAGENT_PI_BIN) throw new Error("Use test/run-source-tests.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT, "rpc-"));
  const sessionFile = join(cwd, "child.jsonl");
  const child = spawn(process.env.PI_SUBAGENT_PI_BIN, ["--mode", "rpc", "--session", sessionFile], {
    cwd, env: process.env, stdio: ["pipe", "pipe", "pipe"],
  });
  const records: any[] = [];
  let stderr = "";
  let buffered = "";
  let timeout: ReturnType<typeof setTimeout>;
  try {
    const exited = new Promise<number | null>((resolve, reject) => {
      child.on("error", reject);
      child.on("exit", resolve);
    });
    const settled = new Promise<void>((resolve, reject) => {
      timeout = setTimeout(() => reject(new Error(`RPC did not settle; stderr=${stderr}; records=${JSON.stringify(records)}`)), 10000);
      child.stdout.setEncoding("utf8");
      child.stdout.on("data", (data: string) => {
        buffered += data;
        for (let i; (i = buffered.indexOf("\n")) >= 0;) {
          const line = buffered.slice(0, i); buffered = buffered.slice(i + 1);
          const record = JSON.parse(line); records.push(record);
          if (record.type === "agent_settled") resolve();
        }
      });
      child.on("exit", (code) => reject(new Error(`RPC exited ${code}; stderr=${stderr}`)));
    });
    child.stderr.on("data", (data) => { stderr += data; });
    child.stdin.write(`${JSON.stringify({ type: "get_state", id: "state" })}\n`);
    child.stdin.write(`${JSON.stringify({ type: "prompt", id: "prompt", message: "hello-source" })}\n`);
    await settled;
    child.stdin.end();
    expect(await exited).toBe(0);
    expect(records.find((r) => r.id === "state")?.success).toBe(true);
    expect(records.find((r) => r.id === "prompt")?.success).toBe(true);
    const message = records.find((r) => r.type === "message_end" && r.message.role === "assistant")?.message;
    expect(JSON.stringify(message.content)).toContain("hello-source");
    expect(message.provider).toBe("faux");
    expect(message.stopReason).toBe("stop");
    expect(existsSync(sessionFile)).toBe(true);
  } finally {
    clearTimeout(timeout!);
    if (child.exitCode === null) child.kill("SIGKILL");
    rmSync(cwd, { recursive: true, force: true });
  }
}, 15000);
