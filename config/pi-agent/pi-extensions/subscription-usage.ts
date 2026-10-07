import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";

const PROVIDER = "openai-codex";
const USAGE_URL = "https://chatgpt.com/backend-api/wham/usage";

type UsageRow = { label: string; value: string };
type JsonObject = Record<string, unknown>;

class UsageError extends Error {}

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new UsageError("Invalid account-usage response");
  }
  return value as JsonObject;
}

function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new UsageError("Invalid account-usage response");
  }
  return value;
}

function windowLabel(seconds: number): string {
  if (seconds === 604800) return "Weekly";
  if (seconds % 86400 === 0) return `${seconds / 86400} day`;
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  return `${seconds / 60}m`;
}

function resetTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  if (!Number.isFinite(date.getTime())) throw new UsageError("Invalid account-usage reset time");
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return `${time} on ${day}`;
}

function limitRows(value: unknown, prefix = ""): UsageRow[] {
  if (value == null) return [];
  const limit = object(value);
  const rows: UsageRow[] = [];
  for (const key of ["primary_window", "secondary_window"]) {
    if (limit[key] == null) continue;
    const window = object(limit[key]);
    const seconds = number(window.limit_window_seconds);
    if (seconds === 0) throw new UsageError("Invalid account-usage window duration");
    const left = Math.max(0, 100 - number(window.used_percent));
    const filled = Math.round(left / 5);
    const bar = "█".repeat(filled) + "░".repeat(20 - filled);
    rows.push({
      label: `${prefix}${windowLabel(seconds)} limit:`,
      value: `[${bar}] ${Math.round(left)}% left (resets ${resetTime(number(window.reset_at))})`,
    });
  }
  return rows;
}

/** The Codex account-usage wire format, not model-response token usage. */
export function formatSubscriptionUsage(payload: unknown): string {
  const usage = object(payload);
  if (!["rate_limit", "credits", "additional_rate_limits"].some((key) => key in usage)) {
    throw new UsageError("Invalid account-usage response");
  }
  const rows = limitRows(usage.rate_limit);
  if (usage.credits != null) {
    const credits = object(usage.credits);
    let balance: string;
    if (credits.unlimited === true) balance = "Unlimited";
    else if (typeof credits.balance === "string" && /^\d+(\.\d+)?$/.test(credits.balance)) {
      balance = `${credits.balance} credits`;
    } else if (credits.balance != null) throw new UsageError("Invalid account-usage credit balance");
    else if (credits.has_credits === true) balance = "Available (balance not reported)";
    else if (credits.has_credits === false) balance = "None";
    else throw new UsageError("Invalid account-usage credits");
    rows.push({ label: "Credits:", value: balance });
  }
  if (usage.additional_rate_limits != null) {
    if (!Array.isArray(usage.additional_rate_limits)) throw new UsageError("Invalid additional account limits");
    for (const value of usage.additional_rate_limits) {
      const additional = object(value);
      if (typeof additional.limit_name !== "string" || !additional.limit_name.trim()) {
        throw new UsageError("Invalid additional account-limit name");
      }
      const name = additional.limit_name.toLowerCase() === "gpt-reserve"
        ? "Luna Reserve" : additional.limit_name.replace(/[\x00-\x1f\x7f]/g, "");
      rows.push(...limitRows(additional.rate_limit, `${name} `));
    }
  }
  if (!rows.length) return "No subscription limits or credit balance reported for this account.";
  const width = Math.max(...rows.map((row) => row.label.length));
  return rows.map((row) => `  ${row.label.padEnd(width)}  ${row.value}`).join("\n");
}

function accountId(token: string): string {
  try {
    const payload = object(JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf8")));
    const claim = object(payload["https://api.openai.com/auth"]);
    if (typeof claim.chatgpt_account_id === "string" && claim.chatgpt_account_id) {
      return claim.chatgpt_account_id;
    }
  } catch { /* Never include the credential or decoded claims in diagnostics. */ }
  throw new UsageError("ChatGPT subscription login required. Use /login and select OpenAI Codex.");
}

export async function showSubscriptionUsage(
  ctx: ExtensionCommandContext,
  request: typeof fetch = fetch,
): Promise<void> {
  if (ctx.mode !== "tui") {
    ctx.ui.notify("Subscription usage is available only in interactive mode", "warning");
    return;
  }
  try {
    // Pi owns credential discovery, refresh, and provider overrides. Never read auth.json.
    const resolved = await ctx.modelRegistry.getProviderAuth(PROVIDER);
    const provider = ctx.modelRegistry.getProvider(PROVIDER);
    const baseUrl = resolved?.auth.baseUrl ?? provider?.baseUrl;
    if (baseUrl && !/^https:\/\/chatgpt\.com\/backend-api(?:\/codex)?\/?$/.test(baseUrl)) {
      throw new UsageError("Subscription usage requires the direct ChatGPT provider; a custom proxy is configured.");
    }
    const token = resolved?.auth.apiKey;
    if (!token) throw new UsageError("ChatGPT subscription login required. Use /login and select OpenAI Codex.");
    const headers = new Headers();
    for (const [key, value] of Object.entries(resolved?.auth.headers ?? {})) {
      if (value != null) headers.set(key, value);
    }
    const id = accountId(token);
    if (!headers.has("chatgpt-account-id")) headers.set("chatgpt-account-id", id);
    headers.set("authorization", `Bearer ${token}`);
    headers.set("accept", "application/json");
    // Passive readers must not opt into Codex's Luna Reserve fallback experiment.
    headers.delete("x-openai-codex-luna-reserve");
    const response = await request(USAGE_URL, {
      headers, signal: AbortSignal.timeout(15000), redirect: "error",
    });
    if (!response.ok) {
      if (response.status === 401) throw new UsageError("ChatGPT login expired or was rejected. Run /login again.");
      throw new UsageError(`Account-usage request failed (HTTP ${response.status}). Try /usage again later.`);
    }
    ctx.ui.notify(formatSubscriptionUsage(await response.json()), "info");
  } catch (error) {
    // Auth resolvers and transport errors can contain credentials or response bodies.
    const message = error instanceof UsageError
      ? error.message : "Could not read ChatGPT subscription usage. Check your login and connection, then retry /usage.";
    ctx.ui.notify(message, "error");
  }
}

export default function subscriptionUsage(pi: ExtensionAPI): void {
  pi.registerCommand("usage", {
    description: "Show ChatGPT subscription limits, credits, and reset times",
    handler: async (args, ctx) => {
      if (args.trim()) {
        ctx.ui.notify("Usage: /usage (no arguments)", "warning");
        return;
      }
      await showSubscriptionUsage(ctx);
    },
  });
}
