/** Native session_start barrier: tests own both marker files and explicitly release startup. */
import { existsSync, realpathSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function linkStartupExtension(pi: ExtensionAPI): void {
  pi.on("session_start", async (_event, ctx) => {
    const root = process.env.PI_TEST_OWNED_ROOT;
    if (!root) throw new Error("Startup barrier requires the disposable source-test bootstrap");
    const rel = relative(realpathSync(root), realpathSync(ctx.cwd));
    if (rel === ".." || rel.startsWith("../") || rel.startsWith("/")) throw new Error("Startup markers must be disposable");
    writeFileSync(join(ctx.cwd, "startup-started"), JSON.stringify({ pid: process.pid, sessionId: ctx.sessionManager.getSessionId() }));
    while (!existsSync(join(ctx.cwd, "startup-release"))) await delay(5);
  });
}
