import { describe, expect, test } from "bun:test";
import subscriptionUsage, {
  formatSubscriptionUsage, showSubscriptionUsage,
} from "../../config/pi-agent/pi-extensions/subscription-usage";

const weekly = {
  used_percent: 4, limit_window_seconds: 604800,
  reset_at: new Date(2026, 9, 14, 9, 38).getTime() / 1000,
};
const payload = {
  rate_limit: { primary_window: null, secondary_window: weekly },
  credits: { has_credits: true, unlimited: false, balance: "62500" },
  additional_rate_limits: [{
    limit_name: "gpt-reserve", metered_feature: "codex_reserve",
    rate_limit: { primary_window: { ...weekly, used_percent: 0,
      reset_at: new Date(2026, 9, 14, 18, 10).getTime() / 1000 } },
  }],
};
const token = `fixture.${Buffer.from(JSON.stringify({
  "https://api.openai.com/auth": { chatgpt_account_id: "fixture-account" },
})).toString("base64url")}.fixture`;

function context(options: { token?: string; baseUrl?: string; headers?: Record<string, string | null>; mode?: string } = {}) {
  const notifications: Array<[string, string]> = [];
  let authCalls = 0;
  const ctx = {
    mode: options.mode ?? "tui",
    ui: { notify: (message: string, level: string) => notifications.push([message, level]) },
    modelRegistry: {
      getProviderAuth: async (provider: string) => {
        expect(provider).toBe("openai-codex");
        authCalls++;
        return { auth: { apiKey: options.token ?? token, headers: options.headers } };
      },
      getProvider: () => ({ baseUrl: options.baseUrl ?? "https://chatgpt.com/backend-api" }),
    },
  };
  return { ctx, notifications, authCalls: () => authCalls };
}

function request(fn: (url: string, init: RequestInit) => Promise<Response> | Response): typeof fetch {
  return fn as typeof fetch;
}

const offline = request(() => { throw new Error("Unexpected network request"); });

describe("subscription usage", () => {
  test("matches weekly, credits, and Luna Reserve rows with percentages left and local resets", () => {
    expect(formatSubscriptionUsage(payload)).toBe([
      "  Weekly limit:               [███████████████████░] 96% left (resets 09:38 on 14 Oct)",
      "  Credits:                    62500 credits",
      "  Luna Reserve Weekly limit:  [████████████████████] 100% left (resets 18:10 on 14 Oct)",
    ].join("\n"));
  });

  test("reads both windows and unknown additional buckets without hardcoding weekly positions", () => {
    const result = formatSubscriptionUsage({
      rate_limit: { primary_window: { ...weekly, used_percent: 80, limit_window_seconds: 18000 }, secondary_window: weekly },
      additional_rate_limits: [{ limit_name: "another-model", rate_limit: {
        secondary_window: { ...weekly, used_percent: 105 },
      } }],
    });
    expect(result).toContain("5h limit:");
    expect(result).toContain("[████░░░░░░░░░░░░░░░░] 20% left");
    expect(result).toContain("another-model Weekly limit:");
    expect(result).toContain("[░░░░░░░░░░░░░░░░░░░░] 0% left");
    expect(result).not.toContain("Credits:");
  });

  test("does not manufacture a credit balance or missing window", () => {
    expect(formatSubscriptionUsage({ credits: { unlimited: true } })).toContain("Unlimited");
    expect(formatSubscriptionUsage({ credits: { has_credits: true } })).toContain("Available (balance not reported)");
    expect(formatSubscriptionUsage({ credits: { has_credits: false } })).toContain("None");
    expect(formatSubscriptionUsage({ credits: { balance: "0.5" } })).toContain("0.5 credits");
    expect(formatSubscriptionUsage({ rate_limit: null, credits: null })).toBe(
      "No subscription limits or credit balance reported for this account.",
    );
  });

  test("rejects invalid wire data rather than showing fabricated availability", () => {
    for (const bad of [null, [], {}, { credits: { balance: 5 } },
      { credits: { balance: "<secret>" } }, { additional_rate_limits: {} },
      { additional_rate_limits: [{ rate_limit: null }] },
      ...["4", -1, NaN, Infinity].map((used_percent) => ({
        rate_limit: { primary_window: { ...weekly, used_percent } },
      })),
      { rate_limit: { primary_window: { ...weekly, reset_at: undefined } } },
      { rate_limit: { primary_window: { ...weekly, limit_window_seconds: 0 } } },
    ]) expect(() => formatSubscriptionUsage(bad)).toThrow();
  });

  test("uses Pi's resolved credentials and account header for one bounded read-only request", async () => {
    const fixture = context({ headers: {
      "ChatGPT-Account-ID": "selected-account", "x-configured": "preserved",
      "x-openai-codex-luna-reserve": "1", "x-deleted": null,
    } });
    let calls = 0;
    await showSubscriptionUsage(fixture.ctx as never, request((url, init) => {
      calls++;
      expect(url).toBe("https://chatgpt.com/backend-api/wham/usage");
      expect(init.method).toBeUndefined(); // GET by default; no generation or redemption.
      expect(init.redirect).toBe("error");
      expect(init.signal).toBeInstanceOf(AbortSignal);
      const headers = new Headers(init.headers);
      expect(headers.get("authorization")).toBe(`Bearer ${token}`);
      expect(headers.get("chatgpt-account-id")).toBe("selected-account");
      expect(headers.get("x-configured")).toBe("preserved");
      expect(headers.has("x-deleted")).toBe(false);
      expect(headers.has("x-openai-codex-luna-reserve")).toBe(false);
      return Response.json(payload);
    }));
    expect(calls).toBe(1);
    expect(fixture.authCalls()).toBe(1);
    expect(fixture.notifications).toEqual([[formatSubscriptionUsage(payload), "info"]]);
  });

  test("derives account id from subscription token when no account header is configured", async () => {
    const fixture = context();
    await showSubscriptionUsage(fixture.ctx as never, request((_url, init) => {
      expect(new Headers(init.headers).get("chatgpt-account-id")).toBe("fixture-account");
      return Response.json(payload);
    }));
    expect(fixture.notifications[0][1]).toBe("info");
  });

  test("does not send proxy tokens or non-subscription keys to ChatGPT", async () => {
    for (const options of [ { token: "sk-fixture" }, { token: "" },
      { baseUrl: "http://localhost:8787" },
      { baseUrl: "https://chatgpt.com.evil.invalid/backend-api" },
    ]) {
      const fixture = context(options);
      await showSubscriptionUsage(fixture.ctx as never, offline);
      expect(fixture.notifications[0][1]).toBe("error");
      expect(fixture.notifications[0][0]).not.toContain("Unexpected network");
      expect(fixture.notifications[0][0]).not.toContain("sk-fixture");
    }
  });

  test("reports HTTP failures without disclosing response bodies", async () => {
    for (const status of [401, 403, 429, 503]) {
      const fixture = context();
      await showSubscriptionUsage(fixture.ctx as never, request(() => new Response("private response", { status })));
      expect(fixture.notifications[0][1]).toBe("error");
      expect(fixture.notifications[0][0]).not.toContain("private response");
      expect(fixture.notifications[0][0]).toContain(status === 401 ? "/login" : `HTTP ${status}`);
    }
  });

  test("malformed responses and resolver/transport failures produce one safe error", async () => {
    for (const failure of ["json", "schema", "transport", "auth"]) {
      const fixture = context();
      if (failure === "auth") fixture.ctx.modelRegistry.getProviderAuth = async () => {
        throw new Error(`ChatGPT ${token}`);
      };
      await showSubscriptionUsage(fixture.ctx as never, request(() => {
        if (failure === "transport") throw new Error(`network failed: ${token}`);
        if (failure === "schema") return Response.json({ private: token });
        return new Response("invalid JSON");
      }));
      expect(fixture.notifications).toHaveLength(1);
      expect(fixture.notifications[0][1]).toBe("error");
      expect(fixture.notifications[0][0]).not.toContain(token);
    }
  });

  test("noninteractive invocations do not resolve credentials or make requests", async () => {
    const fixture = context({ mode: "print" });
    await showSubscriptionUsage(fixture.ctx as never, offline);
    expect(fixture.authCalls()).toBe(0);
    expect(fixture.notifications).toEqual([["Subscription usage is available only in interactive mode", "warning"]]);
  });

  test("registers /usage without starting requests and rejects arguments", async () => {
    const commands = new Map<string, { handler: Function }>();
    subscriptionUsage({ registerCommand: (name: string, command: { handler: Function }) => commands.set(name, command) } as never);
    expect([...commands.keys()]).toEqual(["usage"]);
    const fixture = context();
    await commands.get("usage")!.handler("weekly", fixture.ctx);
    expect(fixture.authCalls()).toBe(0);
    expect(fixture.notifications).toEqual([["Usage: /usage (no arguments)", "warning"]]);
  });
});
