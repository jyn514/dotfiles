import { expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { heldToolFiles, providerCallsFile } from "./held-tool-extension.ts";
import { jsonl, sourceRpc, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("ordinary held-tool completion returns to the real provider loop once", async () => {
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "held-roundtrip-"));
  const sessionFile = join(cwd, "child.jsonl");
  const path = join(cwd, "tool");
  const files = heldToolFiles(path);
  const rpc = sourceRpc(cwd, sessionFile);
  try {
    await rpc.request({ type: "prompt", message: `hold-tool:${path}` });
    await until(() => existsSync(files.started), "ordinary held tool starts");
    expect(jsonl(providerCallsFile(sessionFile))).toHaveLength(1);
    expect(jsonl(files.effects)).toHaveLength(0);
    writeFileSync(files.release, "release");
    await until(() => rpc.records.some(record => record.type === "agent_settled"), "ordinary tool result feeds next provider response");
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(sessionFile))).toHaveLength(2);
    expect(rpc.records.filter(record => record.type === "tool_execution_end")).toHaveLength(1);
    const assistants = rpc.records.filter(record => record.type === "message_end" && record.message.role === "assistant");
    expect(assistants).toHaveLength(2);
    expect(assistants[0].message.stopReason).toBe("toolUse");
    expect(assistants[1].message.stopReason).toBe("stop");
    expect(assistants[1].message.content[0].type).toBe("text");
  } finally {
    await rpc.close();
    rmSync(cwd, { recursive: true, force: true });
  }
}, 15000);
