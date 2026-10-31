import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";

type UsageRow = { label: string; value: string };
type JsonObject = Record<string, unknown>;

class UsageError extends Error {}

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new UsageError("Invalid Codex account-usage response");
  }
  return value as JsonObject;
}

function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new UsageError("Invalid Codex account-usage response");
  }
  return value;
}

function windowLabel(minutes: number): string {
  if (minutes === 10080) return "Weekly";
  if (minutes % 1440 === 0) return `${minutes / 1440} day`;
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

function resetTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  if (!Number.isFinite(date.getTime())) throw new UsageError("Invalid account-usage reset time");
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return `${time} on ${day}`;
}

function bucketRows(value: unknown, prefix: string): UsageRow[] {
  const bucket = object(value);
  const rows: UsageRow[] = [];
  for (const key of ["primary", "secondary"]) {
    if (bucket[key] == null) continue;
    const window = object(bucket[key]);
    let label = key === "primary" ? "Primary" : "Secondary";
    if (window.windowDurationMins != null) {
      const minutes = number(window.windowDurationMins);
      if (minutes === 0) throw new UsageError("Invalid account-usage window duration");
      label = windowLabel(minutes);
    }
    const left = Math.max(0, 100 - number(window.usedPercent));
    const filled = Math.round(left / 5);
    const bar = "█".repeat(filled) + "░".repeat(20 - filled);
    const reset = window.resetsAt == null ? "reset time unavailable" : `resets ${resetTime(number(window.resetsAt))}`;
    rows.push({ label: `${prefix}${label} limit:`, value: `[${bar}] ${Math.round(left)}% left (${reset})` });
  }
  if (bucket.credits != null) {
    const credits = object(bucket.credits);
    let balance: string;
    if (credits.unlimited === true) balance = "Unlimited";
    else if (typeof credits.balance === "string" && /^\d+(\.\d+)?$/.test(credits.balance)) {
      balance = `${credits.balance} credits`;
    } else if (credits.balance != null) throw new UsageError("Invalid account-usage credit balance");
    else if (credits.hasCredits === true) balance = "Available (balance not reported)";
    else if (credits.hasCredits === false) balance = "None";
    else throw new UsageError("Invalid account-usage credits");
    rows.push({ label: `${prefix}Credits:`, value: balance });
  }
  return rows;
}

/** Format Codex app-server's account/rateLimits/read result, not its raw backend payload. */
export function formatSubscriptionUsage(payload: unknown): string {
  const usage = object(payload);
  const main = object(usage.rateLimits);
  const multiple = usage.rateLimitsByLimitId == null ? [] : Object.entries(object(usage.rateLimitsByLimitId));
  // The single-bucket view mirrors an entry in the map. Prefer the complete
  // map when available, rather than adding the primary quota a second time.
  const buckets = multiple.length ? multiple : [["codex", main]] as const;
  const rows: UsageRow[] = [];
  for (const [id, value] of buckets) {
    const bucket = object(value);
    const name = bucket.limitName ?? id;
    if (typeof name !== "string" || !name.trim()) throw new UsageError("Invalid account-limit name");
    const display = ["gpt-reserve", "codex_reserve"].includes(name.toLowerCase())
      ? "Luna Reserve" : name.replace(/[\x00-\x1f\x7f]/g, "");
    rows.push(...bucketRows(bucket, id === "codex" ? "" : `${display} `));
  }
  if (!rows.length) return "No subscription limits or credit balance reported for this Codex account.";
  const width = Math.max(...rows.map((row) => row.label.length));
  return rows.map((row) => `  ${row.label.padEnd(width)}  ${row.value}`).join("\n");
}

/**
 * Ask a short-lived host Codex app-server for usage. Codex owns login and refresh.
 * No model turn, credential-file access, Reserve opt-in, or persistent server.
 * Resolves only after the subprocess closes; timeout and every failure also stop it.
 */
export async function readCodexUsage(
  launch = () => spawn("codex", ["app-server"], { stdio: "pipe" }),
  timeoutMs = 30000,
): Promise<unknown> {
  const child = launch();
  // Diagnostics may contain backend bodies or credentials. Never publish them.
  child.stderr.resume();
  let lines: ReturnType<typeof createInterface> | undefined;
  const closed = new Promise<void>((resolve) => child.once("close", () => resolve()));
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await new Promise<unknown>((resolve, reject) => {
      let expectedId = 1;
      let bytes = 0;
      let finished = false;
      const fail = (message: string) => {
        if (finished) return;
        finished = true;
        reject(new UsageError(message));
      };
      const send = (message: JsonObject) => child.stdin.write(`${JSON.stringify(message)}\n`);
      timer = setTimeout(() => fail("Codex account-usage request timed out. Try /usage again later."), timeoutMs);
      child.once("error", (error: NodeJS.ErrnoException) => {
        fail(error.code === "ENOENT"
          ? "Codex CLI not found on the host PATH. Install Codex on the host to use /usage."
          : "Could not start the host Codex app-server.");
      });
      child.once("close", () => fail("Codex app-server exited before returning account usage."));
      child.stdin.on("error", () => fail("Could not communicate with the host Codex app-server."));
      child.stdout.on("data", (chunk: Buffer | string) => {
        bytes += Buffer.byteLength(chunk);
        if (bytes > 1024 * 1024) fail("Codex account-usage response exceeded the size limit.");
      });
      lines = createInterface({ input: child.stdout, crlfDelay: Infinity });
      lines.on("line", (line) => {
        if (finished) return;
        try {
          const message = object(JSON.parse(line));
          // Notifications and unrelated responses can arrive between replies.
          if ("method" in message || message.id !== expectedId) return;
          if (message.error != null) {
            const error = object(message.error);
            if (error.code === -32601) {
              fail("Installed Codex does not support this app-server request. Update Codex on the host.");
            } else if (["codex account authentication required to read rate limits",
              "chatgpt authentication required to read rate limits"].includes(String(error.message))) {
              fail("Codex ChatGPT login required. Run codex login on the host, then retry /usage.");
            } else {
              fail("Codex could not read account usage. Check the host Codex login and connection, then retry /usage.");
            }
            return;
          }
          if (!("result" in message)) throw new UsageError("Invalid Codex app-server response");
          if (expectedId === 1) {
            expectedId = 2;
            send({ method: "initialized" });
            // Passive readers must not opt into Luna Reserve fallback exposure.
            send({ id: 2, method: "account/rateLimits/read", params: { excludeResetCreditDetails: true } });
          } else {
            finished = true;
            resolve(message.result);
          }
        } catch {
          fail("Invalid Codex app-server response");
        }
      });
      send({ id: 1, method: "initialize", params: {
        clientInfo: { name: "pi_subscription_usage", version: "1.0.0" },
      } });
    });
  } finally {
    clearTimeout(timer);
    lines?.close();
    child.stdin.destroy();
    child.stdout.destroy();
    if (child.exitCode == null && child.signalCode == null) child.kill("SIGTERM");
    const forceKill = setTimeout(() => child.kill("SIGKILL"), 250);
    await closed;
    clearTimeout(forceKill);
  }
}

export async function showSubscriptionUsage(
  ctx: ExtensionCommandContext,
  readUsage: () => Promise<unknown> = readCodexUsage,
): Promise<void> {
  if (ctx.mode !== "tui") {
    ctx.ui.notify("Subscription usage is available only in interactive mode", "warning");
    return;
  }
  try {
    const message = formatSubscriptionUsage(await readUsage());
    // Resolve ctx.ui after awaiting: Pi rejects outgoing session contexts here.
    ctx.ui.notify(`Codex-account usage\n${message}`, "info");
  } catch (error) {
    const message = error instanceof UsageError
      ? error.message : "Could not read Codex account usage. Check the host Codex login and connection, then retry /usage.";
    ctx.ui.notify(message, "error");
  }
}

export default function subscriptionUsage(pi: ExtensionAPI): void {
  pi.registerCommand("usage", {
    description: "Show the host Codex account's subscription limits, credits, and reset times",
    handler: async (args, ctx) => {
      if (args.trim()) {
        ctx.ui.notify("Usage: /usage (no arguments)", "warning");
        return;
      }
      await showSubscriptionUsage(ctx);
    },
  });
}
