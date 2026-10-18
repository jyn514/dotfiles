import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const testDir = dirname(fileURLToPath(import.meta.url));
export const childHelper = join(testDir, "../child-helper.ts");
export const heldExtension = join(testDir, "held-tool-extension.ts");
export const productionIndex = join(testDir, "../index.ts");
export function jsonl(path: string): any[] {
  return existsSync(path) ? readFileSync(path, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)) : [];
}
export async function until(predicate: () => boolean | Promise<boolean>, description: string, timeout = 10000): Promise<void> {
  const deadline = Date.now() + timeout;
  while (!await predicate()) {
    if (Date.now() >= deadline) throw new Error(`Timed out: ${description}`);
    await delay(10);
  }
}

/** Test-side JSONL peer; does not implement agent/session behavior. */
export function sourceRpc(cwd: string, sessionFile: string, hold = false, extensions = [childHelper, heldExtension]) {
  if (!process.env.PI_TEST_OWNED_ROOT || !process.env.PI_SUBAGENT_PI_BIN) throw new Error("Use run-source-tests.ts");
  const child = spawn(process.env.PI_SUBAGENT_PI_BIN, ["--mode", "rpc", "--session", sessionFile,
    ...extensions.flatMap(path => ["--extension", path])], {
    cwd, env: { ...process.env, ...(hold ? { PI_SUBAGENT_HOLD: "1" } : {}) }, stdio: ["pipe", "pipe", "pipe"],
  });
  const records: any[] = [];
  let stderr = "";
  let buffered = "";
  let sequence = 0;
  const pending = new Map<string, { resolve(value: any): void; reject(error: Error): void; timer: ReturnType<typeof setTimeout> }>();
  child.stderr.on("data", data => { stderr += data; });
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (data: string) => {
    buffered += data;
    for (let index; (index = buffered.indexOf("\n")) >= 0;) {
      const record = JSON.parse(buffered.slice(0, index)); buffered = buffered.slice(index + 1);
      records.push(record);
      const request = pending.get(record.id);
      if (!request || record.type !== "response") continue;
      clearTimeout(request.timer); pending.delete(record.id);
      record.success ? request.resolve(record.data) : request.reject(new Error(record.error));
    }
  });
  const rejectPending = (error: Error) => {
    for (const request of pending.values()) { clearTimeout(request.timer); request.reject(error); }
    pending.clear();
  };
  child.on("error", rejectPending);
  child.stdin.on("error", rejectPending);
  const exited = new Promise<number | null>(resolve => child.once("exit", (code) => {
    rejectPending(new Error(`RPC exited ${code}: ${stderr}`)); resolve(code);
  }));
  return {
    child, records, exited,
    stderr: () => stderr,
    request(command: Record<string, unknown>): Promise<any> {
      const id = `test-${++sequence}`;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => { pending.delete(id); reject(new Error(`RPC timeout ${JSON.stringify(command)}: ${stderr}`)); }, 10000);
        pending.set(id, { resolve, reject, timer });
        child.stdin.write(`${JSON.stringify({ ...command, id })}\n`);
      });
    },
    async close() {
      child.stdin.end();
      const watchdog = setTimeout(() => child.kill("SIGKILL"), 2000);
      try { return await exited; } finally { clearTimeout(watchdog); }
    },
  };
}
