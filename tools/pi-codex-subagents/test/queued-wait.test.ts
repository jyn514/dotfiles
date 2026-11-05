import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { Type } from "typebox";
import { fauxAssistantMessage, fauxProvider, fauxToolCall, type FauxResponseFactory } from "@earendil-works/pi-ai/providers/faux";
import {
  createAgentSessionFromServices, createAgentSessionServices, createCodemodeExtension,
  getAgentDir, ModelRuntime, SessionManager, SettingsManager,
  type AgentSessionEvent, type ExtensionContext, type ToolResultEvent,
} from "@earendil-works/pi-coding-agent";
import { getAgent } from "../core.ts";
import { heldToolFiles } from "./held-tool-extension.ts";
import { heldExtension, productionIndex, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
const waits = ["default", "any", "all"] as const;
type Wait = typeof waits[number];
type Role = "user" | "custom";
const markerText = "independent queued steering marker";
function text(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.filter(part => part.type === "text").map(part => part.text).join("\n");
}

/**
 * Consumer oracle: jyn's November 2 request + ticket38438831 require steering
 * of either role to release every wait mode normally, without aborting the
 * parent, changing child lifetime, or taking the queued message. Follow-up is not
 * steering. The one-second deadline is a generous test bound, not a new SLA.
 * Actual source SDK, production extension registration, native input admission,
 * and a native held-tool child are used; only provider responses and gate timing
 * are fixtures. No runtime queue or manager method is replaced.
 */
async function fixture() {
  if (!process.env.PI_TEST_OWNED_ROOT) throw new Error("Use test/run-source-tests.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT, "queued-wait-"));
  const childMarker = join(cwd, "child");
  const childFiles = heldToolFiles(childMarker);
  const template = `queued-wait-${randomUUID()}`;
  const templates = join(getAgentDir(), "pi-codex-subagents", "agents");
  mkdirSync(templates, { recursive: true });
  const templateFile = join(templates, `${template}.md`);
  writeFileSync(templateFile, `---\nname: ${template}\nprovider: faux\nmodel: faux-1\nthinking: off\nextensions: ${heldExtension}\n---\n`);
  const faux = fauxProvider();
  const modelRuntime = await ModelRuntime.create({
    authPath: join(cwd, "auth.json"), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false,
  });
  modelRuntime.registerNativeProvider(faux.provider);
  const events: AgentSessionEvent[] = [];
  const resultBoundaries: Array<{ event: ToolResultEvent; pending: boolean }> = [];
  let context: ExtensionContext | undefined;
  let gateEntered = false;
  let gateReleased = false;
  const settingsManager = SettingsManager.create(cwd, getAgentDir(), { projectTrusted: true });
  settingsManager.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false }, defaultTools: ["+codemode"] });
  const services = await createAgentSessionServices({
    cwd, agentDir: getAgentDir(), modelRuntime, settingsManager,
    resourceLoaderOptions: {
      noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: [productionIndex],
      extensionFactories: [createCodemodeExtension({ mode: "on" }), (pi) => {
        pi.on("session_start", (_event, ctx) => { context = ctx; });
        pi.on("tool_result", (event, ctx) => {
          if (event.toolName === "wait_agent") resultBoundaries.push({ event, pending: ctx.hasPendingSteeringMessages() });
        });
        pi.registerTool({
          name: "qa_gate", label: "QA gate", description: "Disposable timing boundary before wait admission.",
          parameters: Type.Object({}), executionMode: "sequential",
          async execute(_id, _args, signal) {
            gateEntered = true;
            while (!gateReleased) await delay(5, undefined, { signal });
            return { content: [{ type: "text", text: "released" }], details: {} };
          },
        });
      }],
    },
  });
  const { session, extensionsResult } = await createAgentSessionFromServices({
    services, sessionManager: SessionManager.create(cwd), model: faux.getModel(), thinkingLevel: "off", noTools: "builtin",
  });
  expect(extensionsResult.errors).toEqual([]);
  session.subscribe(event => events.push(event));
  await session.bindExtensions({});
  const parentId = session.sessionManager.getSessionId();
  const respond: FauxResponseFactory = () => { faux.appendResponses([respond]); return fauxAssistantMessage("parent remains available"); };
  faux.setResponses([
    fauxAssistantMessage(fauxToolCall("spawn_agent", { task_name: "held", agent_type: template, message: `hold-tool:${childMarker}` }), { stopReason: "toolUse" }),
    respond,
  ]);
  await session.prompt("start disposable child");
  await until(() => existsSync(childFiles.started), "native child reaches held tool");
  const child = getAgent("held", parentId)!;
  expect(child.status).toBe("running");
  const toolResults = (name: string) => session.messages.filter(message => message.role === "toolResult" && message.toolName === name);
  const notifications = () => session.messages.filter(message => message.role === "custom" && message.customType === "pi-codex-subagent-completion");
  return {
    session, context: () => context!, events, resultBoundaries, childFiles, toolResults, notifications,
    get child() { return getAgent("held", parentId)!; },
    async spawnOther() {
      const otherMarker = join(cwd, "other-child");
      faux.setResponses([
        fauxAssistantMessage(fauxToolCall("spawn_agent", { task_name: "other", agent_type: template, message: `hold-tool:${otherMarker}` }), { stopReason: "toolUse" }), respond,
      ]);
      await session.prompt("start second disposable child");
      const files = heldToolFiles(otherMarker);
      await until(() => existsSync(files.started), "second native child reaches held tool");
      return {
        release() { writeFileSync(files.release, "complete second child"); },
        get child() { return getAgent("other", parentId)!; },
      };
    },
    start(wait: Wait | "invalid", gate = false, nested = false, targets: string[] | null = ["held"]) {
      gateEntered = false; gateReleased = !gate;
      if (nested) session.setActiveToolsByName([...session.getActiveToolNames(), "codemode"]);
      const params = { ...(targets ? { targets } : {}), ...(wait === "default" ? {} : { until: wait }) };
      const call = nested ? fauxToolCall("codemode", { code: `const result = await tools.wait_agent(${JSON.stringify(params)}); text(result); text("script continued after wait");` })
        : fauxToolCall("wait_agent", params);
      faux.setResponses([fauxAssistantMessage([...(gate ? [fauxToolCall("qa_gate", {})] : []), call], { stopReason: "toolUse" }), respond]);
      return session.prompt(`exercise ${wait}`);
    },
    gateEntered: () => gateEntered,
    releaseGate() { gateReleased = true; },
    async queue(role: Role, lane: "steer" | "followUp" = "steer") {
      if (role === "user") await session[lane](markerText);
      else await session.sendCustomMessage({ customType: "qa-steering", content: markerText, display: false }, { deliverAs: lane, triggerTurn: true });
    },
    releaseChild() { writeFileSync(childFiles.release, "complete child"); },
    async close() {
      gateReleased = true;
      writeFileSync(childFiles.release, "cleanup");
      await session.abort();
      await session.extensionRunner?.emit({ type: "session_shutdown", reason: "exit" });
      session.dispose();
      rmSync(templateFile, { force: true });
      rmSync(cwd, { recursive: true, force: true });
    },
  };
}

for (const wait of waits) for (const role of ["user", "custom"] as const) for (const arrival of ["before", "during"] as const) {
  sourceTest(`${wait}: ${role} steering ${arrival} wait releases normally; queue and child survive`, async () => {
    const f = await fixture();
    try {
      const settledBefore = f.events.filter(event => event.type === "agent_settled").length;
      const run = f.start(wait, arrival === "before");
      if (arrival === "before") await until(f.gateEntered, "gate blocks before registered wait");
      else {
        await until(() => f.events.some(event => event.type === "tool_execution_start" && event.toolName === "wait_agent"), "registered wait starts");
        await delay(40);
        expect(f.toolResults("wait_agent")).toHaveLength(0);
      }
      await f.queue(role);
      expect(f.context().hasPendingSteeringMessages()).toBe(true);
      f.releaseGate();
      await until(() => f.toolResults("wait_agent").length === 1, "steering releases the real registered wait", 1000);
      await run;
      const [result] = f.toolResults("wait_agent");
      expect(result.role === "toolResult" && result.isError).not.toBe(true);
      expect(JSON.parse(text(result.content))).toEqual({
        message: "Wait interrupted by queued steering. Child agents were not stopped.", interrupted: true,
      });
      expect(f.resultBoundaries).toHaveLength(1);
      expect(f.resultBoundaries[0].pending).toBe(true);
      expect(f.session.messages.filter(message => text(message.content) === markerText)).toHaveLength(1);
      expect(f.events.filter(event => event.type === "agent_settled").slice(settledBefore).every(event => !event.aborted)).toBe(true);
      expect(f.child.status).toBe("running");
      expect(existsSync(f.childFiles.ended)).toBe(false);
      f.releaseChild();
      await until(() => f.notifications().length === 1, "later completion is delivered after interrupted wait");
      await f.session.waitForIdle();
      await delay(50);
      expect(f.notifications()).toHaveLength(1);
      expect(f.child.status).toBe("completed");
    } finally { await f.close(); }
  }, 15000);
}

for (const wait of waits) for (const role of ["user", "custom"] as const) {
  sourceTest(`${wait}: ${role} follow-up alone does not release an active wait`, async () => {
    const f = await fixture();
    try {
      const run = f.start(wait);
      await until(() => f.events.some(event => event.type === "tool_execution_start" && event.toolName === "wait_agent"), "wait starts");
      await f.queue(role, "followUp");
      expect(f.context().hasPendingMessages()).toBe(true);
      expect(f.context().hasPendingSteeringMessages()).toBe(false);
      await delay(180);
      expect(f.toolResults("wait_agent")).toHaveLength(0);
      expect(f.child.status).toBe("running");
      f.releaseChild();
      await run;
      expect(f.toolResults("wait_agent")).toHaveLength(1);
      expect(text(f.toolResults("wait_agent")[0].content)).toContain("completed");
      expect(f.session.messages.filter(message => text(message.content) === markerText)).toHaveLength(1);
    } finally { await f.close(); }
  }, 15000);
}

for (const wait of waits) {
  sourceTest(`${wait}: explicit parent abort still aborts parent, not child`, async () => {
    const f = await fixture();
    try {
      const run = f.start(wait);
      await until(() => f.events.some(event => event.type === "tool_execution_start" && event.toolName === "wait_agent"), "wait starts");
      await f.session.abort();
      await run;
      expect(f.events.some(event => event.type === "agent_settled" && event.aborted)).toBe(true);
      expect(f.child.status).toBe("running");
      f.releaseChild();
      await until(() => f.notifications().length === 1, "abort also releases completion ownership");
      await f.session.waitForIdle();
    } finally { await f.close(); }
  }, 15000);

  sourceTest(`${wait}: completed child followed by queued input retains its response`, async () => {
    const f = await fixture();
    try {
      const run = f.start(wait, true);
      await until(f.gateEntered, "wait not yet admitted");
      f.releaseChild();
      await until(() => f.child.status === "completed", "child completion wins before input");
      await f.queue("custom");
      f.releaseGate();
      await run;
      const content = text(f.toolResults("wait_agent")[0].content);
      // Either scheduling policy may choose completion or interruption. The
      // response must remain visible once, through the result or notification.
      const responseInResult = content.includes("faux:hold-tool:");
      const notifications = f.notifications();
      expect(Number(responseInResult) + notifications.length).toBe(1);
      expect(f.session.messages.filter(message => text(message.content) === markerText)).toHaveLength(1);
    } finally { await f.close(); }
  }, 15000);
}

sourceTest("codemode nested wait returns on custom steering and surrounding script continues", async () => {
  const f = await fixture();
  try {
    const run = f.start("all", false, true);
    await until(() => f.events.some(event => event.type === "tool_execution_start" && event.toolName === "wait_agent") || f.toolResults("codemode").length > 0, "codemode enters registered nested wait or reports its failure");
    if (f.toolResults("codemode").length) throw new Error(JSON.stringify(f.toolResults("codemode")));
    await f.queue("custom");
    await until(() => f.toolResults("codemode").length === 1, "nested steering returns through codemode", 1000);
    await run;
    expect(text(f.toolResults("codemode")[0].content)).toContain("script continued after wait");
    expect(f.child.status).toBe("running");
    expect(f.session.messages.filter(message => text(message.content) === markerText)).toHaveLength(1);
  } finally { await f.close(); }
}, 15000);

sourceTest("wait_agent until all: partial completion suppressed by wait is released once on steering", async () => {
  const f = await fixture();
  const other = await f.spawnOther();
  try {
    const run = f.start("all", false, false, ["held", "other"]);
    await until(() => f.events.some(event => event.type === "tool_execution_start" && event.toolName === "wait_agent"), "all-target wait starts");
    await delay(40);
    other.release();
    await until(() => other.child.status === "completed", "one child completes while all-target wait owns its response");
    expect(f.toolResults("wait_agent")).toHaveLength(0);
    expect(f.notifications()).toHaveLength(0);
    await f.queue("custom");
    await until(() => f.toolResults("wait_agent").length === 1, "steering interrupts partially completed wait", 1000);
    await run;
    await until(() => f.notifications().length === 1, "suppressed completed response becomes visible");
    expect(f.child.status).toBe("running");
    f.releaseChild();
    await until(() => f.notifications().length === 2, "remaining child's later response becomes visible");
    await f.session.waitForIdle();
    await delay(50);
    expect(f.notifications()).toHaveLength(2);
    expect(f.session.messages.filter(message => text(message.content) === markerText)).toHaveLength(1);
  } finally {
    other.release();
    await f.close();
  }
}, 15000);


// The public merge must choose the existing wait primitive, not merely accept
// the new argument. Two held children distinguish any from all without mocks.
for (const mode of waits) for (const selection of ["explicit", "omitted"] as const) {
  sourceTest(`wait_agent ${mode}, ${selection} targets: completion condition and result shape`, async () => {
    const f = await fixture();
    const other = await f.spawnOther();
    try {
      const run = f.start(mode, false, false, selection === "explicit" ? ["held", "other"] : null);
      await until(() => f.events.some(event => event.type === "tool_execution_start" && event.toolName === "wait_agent"), "merged wait starts");
      await delay(40);
      other.release();
      await until(() => other.child.status === "completed", "second child completes first");
      if (mode === "all") {
        await delay(300);
        expect(f.toolResults("wait_agent")).toHaveLength(0);
        expect(f.notifications()).toHaveLength(0);
        f.releaseChild();
        await run;
        const result = JSON.parse(text(f.toolResults("wait_agent")[0].content));
        expect(result.responses.map((response: any) => response.agent_name).sort()).toEqual(["/held", "/other"]);
        expect(result.responses.every((response: any) => response.status === "completed" && response.finalResponse.includes("faux:hold-tool:"))).toBe(true);
        expect(result.event).toBeUndefined();
        expect(f.notifications()).toHaveLength(0);
      } else {
        await run;
        const result = JSON.parse(text(f.toolResults("wait_agent")[0].content));
        expect(result.event).toMatchObject({ agentName: "/other", status: "completed" });
        expect(result.event.finalResponse).toContain("faux:hold-tool:");
        expect(result.responses).toBeUndefined();
        expect(f.child.status).toBe("running");
        expect(f.notifications()).toHaveLength(0);
        f.releaseChild();
        await until(() => f.notifications().length === 1, "unclaimed remaining completion arrives automatically");
      }
      await f.session.waitForIdle();
      await delay(50);
      expect(f.notifications()).toHaveLength(mode === "all" ? 0 : 1);
    } finally {
      other.release();
      await f.close();
    }
  }, 15000);
}

for (const mode of waits) {
  sourceTest(`wait_agent ${mode}: explicit completed target returns its retained final response`, async () => {
    const f = await fixture();
    try {
      f.releaseChild();
      await until(() => f.notifications().length === 1, "completion already delivered before wait");
      await f.session.waitForIdle();
      await f.start(mode);
      const result = JSON.parse(text(f.toolResults("wait_agent")[0].content));
      const response = mode === "all" ? result.responses[0] : result.event;
      expect(response.finalResponse).toContain("faux:hold-tool:");
      await delay(50);
      expect(f.notifications()).toHaveLength(1);
    } finally { await f.close(); }
  }, 15000);
}

sourceTest("wait_agent rejects invalid until before queued steering can turn it into an interruption", async () => {
  const f = await fixture();
  try {
    const run = f.start("invalid", true);
    await until(f.gateEntered, "input can queue before wait admission");
    await f.queue("custom");
    f.releaseGate();
    await run;
    const result = f.toolResults("wait_agent")[0];
    expect(result.role === "toolResult" && result.isError).toBe(true);
    expect(text(result.content)).not.toContain("interrupted");
    expect(f.child.status).toBe("running");
    expect(f.session.messages.filter(message => text(message.content) === markerText)).toHaveLength(1);
  } finally { await f.close(); }
}, 15000);
