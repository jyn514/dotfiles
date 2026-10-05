import { execFileSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type ValidatedDirectory = { destination: string; repository: string };

export default function sessionHandoff(pi: ExtensionAPI): void {
  const requestPath = process.env.CODEX_SANDBOX_CD_REQUEST;
  const validator = process.env.CODEX_SANDBOX_CD_VALIDATE;
  if (!requestPath || !validator) return;

  pi.on("session_start", (event, ctx) => {
    if (event.reason !== "startup") return;
    if (ctx.sessionManager.getCwd() === process.cwd()) return;
    const session = ctx.sessionManager.getSessionFile();
    if (!session) return;
    writeFileSync(requestPath, JSON.stringify({ destination: process.cwd(), session }), {
      mode: 0o600,
    });
    ctx.shutdown();
  });

  pi.registerCommand("cd", {
    description: "Continue this conversation in another sandbox directory",
    handler: async (argument, ctx) => {
      const target = argument.trim();
      if (!target) {
        ctx.ui.notify("Usage: /cd DIRECTORY", "warning");
        return;
      }
      try {
        const output = execFileSync(validator, ["validate-cd", target], {
          cwd: ctx.cwd, encoding: "utf8", timeout: 15000,
          stdio: ["ignore", "pipe", "pipe"],
        });
        const validated = JSON.parse(output) as ValidatedDirectory;
        if (!validated.destination || !validated.repository) {
          throw new Error("directory validation returned no destination");
        }
        ctx.abort();
        await ctx.waitForIdle();
        const session = ctx.sessionManager.getSessionFile();
        if (!session) throw new Error("/cd requires a saved Pi session");
        const saved = existsSync(session);
        if (!saved && ctx.sessionManager.getEntries().some((entry) => entry.type === "message")) {
          throw new Error("/cd requires the conversation to be saved first");
        }
        writeFileSync(requestPath, JSON.stringify({
          destination: validated.destination, session: saved ? session : null,
        }), {
          mode: 0o600,
        });
        ctx.shutdown();
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
      }
    },
  });
}
