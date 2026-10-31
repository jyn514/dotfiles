import { describe, expect, test } from "bun:test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import subscriptionUsage, {
  formatSubscriptionUsage, readCodexUsage, showSubscriptionUsage,
} from "../../config/pi-agent/pi-extensions/subscription-usage";
import fixturePayload from "./fixtures/subscription-usage.json";

const weekly = {
  usedPercent: 4, windowDurationMins: 10080,
  resetsAt: new Date(2026, 9, 14, 9, 38).getTime() / 1000,
};
const main = { ...fixturePayload.rateLimits, secondary: weekly };
const payload = {
  rateLimits: main,
  rateLimitsByLimitId: {
    codex: main,
    codex_reserve: { ...fixturePayload.rateLimitsByLimitId.codex_reserve,
      primary: { ...weekly, usedPercent: 0, resetsAt: new Date(2026, 9, 14, 18, 10).getTime() / 1000 } },
  },
};

function context(mode = "tui") {
  const notifications: Array<[string, string]> = [];
  const ctx = {
    mode,
    ui: { notify: (message: string, level: string) => notifications.push([message, level]) },
    modelRegistry: new Proxy({}, { get: () => { throw new Error("Pi credentials must not be accessed"); } }),
  };
  return { ctx, notifications };
}

async function server(scenario: string, check: (launch: () => ChildProcessWithoutNullStreams, trace: string) => Promise<void>) {
  const root = await mkdtemp(join(tmpdir(), "subscription-usage-test-"));
  const trace = join(root, "trace.jsonl");
  const launch = () => spawn(process.execPath, [new URL("./fixtures/subscription-usage-server.mjs", import.meta.url).pathname, "app-server"], {
    stdio: "pipe",
    env: { ...process.env, USAGE_FIXTURE_SCENARIO: scenario, USAGE_FIXTURE_TRACE: trace },
  });
  try { await check(launch, trace); }
  finally { await rm(root, { recursive: true, force: true }); }
}

async function traceRows(path: string): Promise<any[]> {
  return (await readFile(path, "utf8")).trim().split("\n").map((line) => JSON.parse(line));
}

function expectGone(pid: number) {
  expect(() => process.kill(pid, 0)).toThrow();
}

describe("subscription usage formatting", () => {
  test("shows bars, credits, Reserve, and local resets without duplicating the mirrored primary quota", () => {
    expect(formatSubscriptionUsage(payload)).toBe([
      "  Weekly limit:               [███████████████████░] 96% left (resets 09:38 on 14 Oct)",
      "  Credits:                    62500 credits",
      "  Luna Reserve Weekly limit:  [████████████████████] 100% left (resets 18:10 on 14 Oct)",
    ].join("\n"));
  });

  test("accepts older single-bucket replies and empty optional maps", () => {
    for (const rateLimitsByLimitId of [undefined, null, {}]) {
      expect(formatSubscriptionUsage({ rateLimits: main, rateLimitsByLimitId })).toBe([
        "  Weekly limit:  [███████████████████░] 96% left (resets 09:38 on 14 Oct)",
        "  Credits:       62500 credits",
      ].join("\n"));
    }
  });

  test("prefers the complete map even when the single view mirrors a non-Codex bucket", () => {
    const bucket = { limitName: "another-model", primary: weekly };
    const result = formatSubscriptionUsage({ rateLimits: bucket, rateLimitsByLimitId: { other: bucket } });
    expect(result.split("\n")).toHaveLength(1);
    expect(result).toContain("another-model Weekly limit:");
  });

  test("uses minutes from app-server, preserves unknown times, and clamps overspent windows to zero left", () => {
    const result = formatSubscriptionUsage({ rateLimits: {
      primary: { ...weekly, usedPercent: 80, windowDurationMins: 300 },
      secondary: { usedPercent: 105, windowDurationMins: null, resetsAt: null },
    } });
    expect(result).toContain("5h limit:");
    expect(result).toContain("[████░░░░░░░░░░░░░░░░] 20% left");
    expect(result).toContain("Secondary limit:");
    expect(result).toContain("[░░░░░░░░░░░░░░░░░░░░] 0% left (reset time unavailable)");
  });

  test("does not manufacture missing credits or windows", () => {
    for (const [credits, expected] of [
      [{ unlimited: true }, "Unlimited"],
      [{ hasCredits: true }, "Available (balance not reported)"],
      [{ hasCredits: false }, "None"],
      [{ balance: "0.5" }, "0.5 credits"],
    ] as const) expect(formatSubscriptionUsage({ rateLimits: { credits } })).toContain(expected);
    expect(formatSubscriptionUsage({ rateLimits: { primary: null, secondary: null, credits: null } })).toBe(
      "No subscription limits or credit balance reported for this Codex account.",
    );
  });

  test("rejects malformed responses without exposing values", () => {
    for (const bad of [null, [], {}, { rateLimits: [] }, { rateLimits: main, rateLimitsByLimitId: [] },
      { rateLimits: { credits: { balance: 5 } } }, { rateLimits: { credits: { balance: "private" } } },
      { rateLimits: main, rateLimitsByLimitId: { other: { limitName: 5 } } },
      ...["4", -1, NaN, Infinity].map((usedPercent) => ({ rateLimits: { primary: { ...weekly, usedPercent } } })),
      { rateLimits: { primary: { ...weekly, resetsAt: Infinity } } },
      { rateLimits: { primary: { ...weekly, windowDurationMins: 0 } } },
    ]) expect(() => formatSubscriptionUsage(bad)).toThrow();
  });
});

describe("host Codex transport", () => {
  for (const scenario of ["success", "chunked"]) {
    test(`performs the passive initialize → initialized → usage exchange (${scenario}) and reaps the child`, async () => {
      await server(scenario, async (launch, trace) => {
        const result = await readCodexUsage(launch);
        expect(formatSubscriptionUsage(result)).toBe(formatSubscriptionUsage(fixturePayload));
        const rows = await traceRows(trace);
        expect(rows[0].args).toEqual(["app-server"]);
        expect(rows.filter((row) => row.method).map((row) => row.method)).toEqual([
          "initialize", "initialized", "account/rateLimits/read",
        ]);
        expect(rows.find((row) => row.method === "account/rateLimits/read").params).toEqual({ excludeResetCreditDetails: true });
        expectGone(rows[0].pid);
      });
    });
  }

  test("missing host Codex has a useful error without leaking the executable path", async () => {
    await expect(readCodexUsage(() => spawn("/nonexistent/private-codex-command", [], { stdio: "pipe" }))).rejects.toThrow(
      "Codex CLI not found on the host PATH",
    );
  });

  for (const [scenario, expected] of [
    ["rpc-auth", "Codex ChatGPT login required"],
    ["rpc-method", "Update Codex on the host"],
    ["rpc-private", "Codex could not read account usage"],
    ["invalid-json", "Invalid Codex app-server response"],
    ["missing-result", "Invalid Codex app-server response"],
    ["early-exit", "exited before returning"],
    ["oversize", "exceeded the size limit"],
  ]) {
    test(`reports ${scenario} safely and reaps the child`, async () => {
      await server(scenario, async (launch, trace) => {
        let caught: unknown;
        try { await readCodexUsage(launch); } catch (error) { caught = error; }
        expect(String(caught)).toContain(expected);
        expect(String(caught)).not.toContain("private-");
        expectGone((await traceRows(trace))[0].pid);
      });
    });
  }

  for (const scenario of ["timeout", "timeout-ignore-term"]) {
    test(`times out and reaps ${scenario}`, async () => {
      await server(scenario, async (launch, trace) => {
        await expect(readCodexUsage(launch, 500)).rejects.toThrow("timed out");
        const rows = await traceRows(trace);
        expectGone(rows[0].pid);
        if (scenario === "timeout-ignore-term") expect(rows.some((row) => row.signal === "SIGTERM")).toBe(true);
      });
    });
  }
});

describe("/usage command", () => {
  test("labels the account owner and does not access Pi credentials", async () => {
    const fixture = context();
    await showSubscriptionUsage(fixture.ctx as never, async () => payload);
    expect(fixture.notifications).toEqual([[`Codex-account usage\n${formatSubscriptionUsage(payload)}`, "info"]]);
  });

  test("sanitizes unexpected reader failures", async () => {
    const fixture = context();
    await showSubscriptionUsage(fixture.ctx as never, async () => { throw new Error("private-token"); });
    expect(fixture.notifications).toHaveLength(1);
    expect(fixture.notifications[0][1]).toBe("error");
    expect(fixture.notifications[0][0]).not.toContain("private-token");
  });

  test("noninteractive invocations do not start Codex", async () => {
    const fixture = context("print");
    let calls = 0;
    await showSubscriptionUsage(fixture.ctx as never, async () => { calls++; return payload; });
    expect(calls).toBe(0);
    expect(fixture.notifications).toEqual([["Subscription usage is available only in interactive mode", "warning"]]);
  });

  test("registers /usage without starting Codex and rejects arguments", async () => {
    const commands = new Map<string, { handler: Function }>();
    subscriptionUsage({ registerCommand: (name: string, command: { handler: Function }) => commands.set(name, command) } as never);
    expect([...commands.keys()]).toEqual(["usage"]);
    const fixture = context();
    await commands.get("usage")!.handler("weekly", fixture.ctx);
    expect(fixture.notifications).toEqual([["Usage: /usage (no arguments)", "warning"]]);
  });
});
