import { expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { getAgentDir, SessionManager } from "@earendil-works/pi-coding-agent";
import { CONTINUATION_MESSAGE } from "../handoff.ts";
import { heldToolFiles, providerCallsFile, templateStartsFile } from "./held-tool-extension.ts";
import { heldExtension, jsonl, productionIndex, sourceRpc, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
const text = (content: any): string => typeof content === "string" ? content : content?.filter((part: any) => part.type === "text").map((part: any) => part.text).join("\n") ?? "";
const toolResults = (file: string, name: string) => SessionManager.open(file).getBranch()
  .filter((entry: any) => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === name) as any[];
const freshMarkers = (file: string) => SessionManager.open(file).getBranch()
  .filter((entry: any) => entry.type === "message" && entry.message.role === "user" && text(entry.message.content) === CONTINUATION_MESSAGE);
const completions = (file: string) => SessionManager.open(file).getBranch()
  .filter((entry: any) => entry.type === "custom_message" && entry.customType === "pi-codex-subagent-completion") as any[];
const lateSteering = "same-batch steering after pause";
const steeringHistory = (file: string) => SessionManager.open(file).getBranch().filter((entry: any) =>
  (entry.type === "custom_message" && text(entry.content) === lateSteering)
  || (entry.type === "message" && entry.message.role === "user" && text(entry.message.content) === lateSteering));

sourceTest.each(["direct", "nested", "blocked"])("production index/coordinator saves active parent+child and drains %s same-batch steering before capture", async (mode) => {
  const nested = mode === "nested";
  const blocked = mode === "blocked";
  const laterTool = nested ? "faux_nested_send" : "steer_subagent";
  const parentExtensions = nested || blocked ? [productionIndex, heldExtension] : [productionIndex];
  const { getAgent, getRunsDir, parentScopeKey } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "parent-child-"));
  const parentFile = join(cwd, "parent.jsonl");
  const marker = join(cwd, "child-tool");
  const files = heldToolFiles(marker);
  const parentFiles = heldToolFiles(`${marker}.parent`);
  const templates = join(getAgentDir(), "pi-codex-subagents", "agents");
  mkdirSync(templates, { recursive: true });
  const templateFile = join(templates, "source-parent-roundtrip.md");
  writeFileSync(templateFile, `---\nname: source-parent-roundtrip\nprovider: faux\nmodel: faux-1\nthinking: off\nextensions: ${heldExtension}\n---\n`);
  // Production index owns Manager/coordinator. The optional test tool uses only
  // public ctx.executeTool; Manager loads child-helper before child template code.
  let rpc = sourceRpc(cwd, parentFile, false, parentExtensions);
  const pauseStatus = async () => {
    const start = rpc.records.length;
    expect((await rpc.request({ type: "prompt", message: "/pause --status" })).disposition).toBe("handled");
    const notification = rpc.records.slice(start).find(record => record.type === "extension_ui_request"
      && record.method === "notify" && record.message.startsWith("Suspension:"));
    expect(notification).toBeTruthy();
    return notification.message as string;
  };
  try {
    const initial = await rpc.request({ type: "get_state" });
    const parentId = initial.sessionId;
    const groupFile = join(getRunsDir(), parentScopeKey(parentId), "group.json");
    const group = () => JSON.parse(readFileSync(groupFile, "utf8"));
    await rpc.request({ type: "prompt", message: `parent-${mode === "direct" ? "" : `${mode}-`}held-task:${marker}` });
    await until(() => existsSync(files.started) && rpc.records.some(record => record.type === "tool_execution_start" && record.toolName === "wait_agent"),
      "production parent is waiting on its actual held-tool child");
    const child = getAgent("native-child", parentId)!;
    expect(child).toBeTruthy();
    const childId = child.id;
    const childFile = child.sessionFile;
    expect(SessionManager.open(parentFile).getSessionId()).toBe(parentId);
    expect(toolResults(parentFile, "spawn_agent")).toHaveLength(1);
    expect(toolResults(parentFile, "wait_agent")).toHaveLength(0);
    expect(toolResults(parentFile, laterTool)).toHaveLength(0);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
    expect(jsonl(files.effects)).toHaveLength(0);

    let pauseReplied = false;
    const pause = rpc.request({ type: "prompt", message: "/pause" }).then(result => { pauseReplied = true; return result; });
    void pause.catch(() => {}); // Cleanup may close an outstanding request after a failed assertion.
    if (blocked) {
      await until(() => existsSync(parentFiles.started), "pause releases the wait but a later parent tool still blocks handoff");
      expect(toolResults(parentFile, laterTool)).toHaveLength(0);
      await until(() => existsSync(files.pauseRequested), "child is fenced while the parent tool is still held", 3000);
      // The child can finish now without another provider call, even though its
      // parent cannot finish the admitted batch or capture pending inputs yet.
      writeFileSync(files.release, "finish child before parent handoff");
      await until(() => existsSync(files.ended), "child tool finishes while parent remains held");
      expect(existsSync(parentFiles.ended)).toBe(false);
      expect(group().parent).toBeUndefined();
      expect(await pauseStatus()).toContain("waiting for parent response/tool batch");
      await delay(50);
      expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
      writeFileSync(parentFiles.release, "finish parent batch");
    }
    await until(() => existsSync(groupFile) && !!group().parent, "coordinator durably exports active parent before child capture finishes");
    if (!blocked) expect(group().phase).toBe("preparing");
    expect(group().parent.handoff.wasActive).toBe(true);
    if (!blocked) expect(pauseReplied).toBe(false);
    const releasedWaits = toolResults(parentFile, "wait_agent");
    expect(releasedWaits).toHaveLength(1);
    expect(JSON.parse(text(releasedWaits[0].message.content)).paused).toBe(true);
    // The later call was already admitted in the same assistant tool batch. Its
    // tool_call hook must register the drain token after pause releases the wait.
    const drainedSend = toolResults(parentFile, laterTool);
    expect(drainedSend).toHaveLength(1);
    expect(drainedSend[0].message.isError).not.toBe(true);
    expect(drainedSend[0].message.details.delivery).toBe("steer");
    if (nested) {
      expect(toolResults(parentFile, "steer_subagent")).toHaveLength(0); // Nested results are not transcript entries.
      expect(drainedSend[0].message.nestedCalls.calls).toHaveLength(1);
      expect(drainedSend[0].message.nestedCalls.calls[0]).toMatchObject({
        name: "steer_subagent", status: "ok", arguments: { target: "native-child", message: lateSteering },
      });
      expect(rpc.records.filter(record => record.type === "tool_execution_end" && record.toolName === "steer_subagent"
        && record.parentToolCallId === drainedSend[0].message.toolCallId)).toHaveLength(1);
    }
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
    expect(completions(parentFile)).toHaveLength(0);
    await until(() => existsSync(files.pauseRequested), "held child observes the coordinator's actual native pause fence");
    expect(readFileSync(files.pauseRequested, "utf8")).toMatch(/^(pausing|paused)$/);
    if (!blocked) {
      await until(async () => (await pauseStatus()).includes("capturing child /native-child"),
        "live status names the child whose held tool prevents capture", 3000);
    }
    writeFileSync(files.release, "release actual child tool");
    expect((await pause).disposition).toBe("handled");
    const saved = group();
    expect(saved.phase, JSON.stringify(saved)).toBe("saved");
    const savedStatus = await pauseStatus();
    expect(savedStatus).toContain("Suspension: saved;");
    expect(savedStatus).not.toMatch(/waiting for|capturing child|closing child/);
    // Closing stdin is the documented RPC shutdown path. /pause --exit currently
    // sets shutdownRequested after RPC's async handled-prompt shutdown check.
    expect(await rpc.close()).toBe(0);
    expect(saved.parentId).toBe(parentId);
    expect(saved.parent.handoff.sessionFile).toBe(parentFile);
    expect(Object.keys(saved.children)).toEqual([childId]);
    expect(saved.children[childId].handoff.sessionFile).toBe(childFile);
    expect(saved.children[childId].handoff.wasActive).toBe(true);
    expect(saved.children[childId].handoff.pending.steering.map((message: any) => text(message.content))).toEqual([lateSteering]);
    expect(saved.children[childId].items.filter((item: any) => item.lane === "steering")).toHaveLength(1);
    expect(steeringHistory(childFile)).toHaveLength(0);
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(toolResults(childFile, "faux_hold")).toHaveLength(1);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
    expect(freshMarkers(parentFile)).toHaveLength(0);
    expect(freshMarkers(childFile)).toHaveLength(0);

    // No fixture hold flag: production discovery of saved group must fence parent startup.
    rpc = sourceRpc(cwd, parentFile, false, parentExtensions);
    const reopened = await rpc.request({ type: "get_state" });
    expect(reopened.sessionId).toBe(parentId);
    expect(reopened.sessionFile).toBe(parentFile);
    expect(reopened.pauseState).toBe("paused");
    expect(group().phase).toBe("saved");
    const reopenedStatus = await pauseStatus();
    expect(reopenedStatus).toContain("Suspension: saved;");
    expect(reopenedStatus).not.toMatch(/waiting for|capturing child|closing child/);
    expect(getAgent("native-child", parentId)!.id).toBe(childId);
    expect(getAgent("native-child", parentId)!.sessionFile).toBe(childFile);
    expect(getAgent("native-child", parentId)!.childProcess).toBeUndefined();
    await delay(50);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(2);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(1);
    expect(jsonl(templateStartsFile(childFile))).toHaveLength(1);
    expect(completions(parentFile)).toHaveLength(0);

    expect((await rpc.request({ type: "prompt", message: "/unpause" })).disposition).toBe("handled");
    await until(() => group().phase === "consumed", "production coordinator consumes the saved generation");
    await until(() => completions(parentFile).length === 1 && getAgent("native-child", parentId)!.status === "completed",
      "one real child completion is delivered into parent history");
    await until(async () => !(await rpc.request({ type: "get_state" })).isStreaming, "parent settles after completion delivery");
    const consumed = group();
    expect(consumed.parentResumed).toBe(true);
    expect(consumed.resumed).toEqual([childId]);
    expect(consumed.completions.mailbox).toHaveLength(1);
    const completionId = consumed.completions.mailbox[0].id;
    expect(consumed.completions.delivered).toEqual([completionId]);
    expect(completions(parentFile)[0].details.completionId).toBe(completionId);
    expect(completions(parentFile)[0].details.agent_name).toBe("/native-child");
    expect(getAgent("native-child", parentId)!.id).toBe(childId);
    expect(getAgent("native-child", parentId)!.sessionFile).toBe(childFile);
    expect(SessionManager.open(childFile).getSessionId()).toBe(saved.children[childId].handoff.sessionId);
    expect(freshMarkers(parentFile)).toHaveLength(1);
    expect(freshMarkers(childFile)).toHaveLength(1);
    expect(toolResults(parentFile, "spawn_agent")).toHaveLength(1);
    expect(toolResults(parentFile, "wait_agent")).toHaveLength(1);
    expect(toolResults(parentFile, laterTool)).toHaveLength(1);
    expect(steeringHistory(childFile)).toHaveLength(1);
    expect(toolResults(childFile, "faux_hold")).toHaveLength(1);
    expect(jsonl(files.effects)).toHaveLength(1);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(2);
    const childStarts = jsonl(templateStartsFile(childFile));
    expect(childStarts).toHaveLength(2);
    expect(childStarts[1].pause).toBe("paused");
    expect(childStarts[1].pid).not.toBe(childStarts[0].pid);

    // An already consumed generation is revoked, even if /unpause is requested again.
    const parentCalls = jsonl(providerCallsFile(parentFile)).length;
    await rpc.request({ type: "prompt", message: "/unpause" });
    await delay(50);
    expect(freshMarkers(parentFile)).toHaveLength(1);
    expect(freshMarkers(childFile)).toHaveLength(1);
    expect(steeringHistory(childFile)).toHaveLength(1);
    expect(toolResults(parentFile, laterTool)).toHaveLength(1);
    expect(completions(parentFile)).toHaveLength(1);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(parentCalls);
    expect(jsonl(providerCallsFile(childFile))).toHaveLength(2);
    expect(jsonl(files.effects)).toHaveLength(1);
  } finally {
    await rpc.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest.each(["any", "all"])("completed commentary reaches parent model during held child tools (%s wait)", async (wait) => {
  const { getAgent } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "commentary-"));
  const parentFile = join(cwd, "parent.jsonl");
  const marker = join(cwd, "child");
  const templates = join(getAgentDir(), "pi-codex-subagents", "agents");
  mkdirSync(templates, { recursive: true });
  const templateFile = join(templates, "source-commentary.md");
  writeFileSync(templateFile, `---\nname: source-commentary\nprovider: faux\nmodel: faux-1\nextensions: ${heldExtension}\n---\n`);
  const rpc = sourceRpc(cwd, parentFile, false, [productionIndex], { PI_TEST_CAPTURE_CONTEXT: "1" });
  const updates = () => SessionManager.open(parentFile).getBranch().filter((entry: any) =>
    entry.type === "custom_message" && entry.customType === "pi-codex-subagent-commentary") as any[];
  const modelUpdates = () => jsonl(providerCallsFile(parentFile)).filter(call => call.messages?.some((message: any) =>
    message.role === "user" && text(message.content).includes('"commentary":')));
  try {
    const { sessionId } = await rpc.request({ type: "get_state" });
    await rpc.request({ type: "prompt", message: `parent-commentary-task:${JSON.stringify({ path: marker, wait })}` });
    await until(() => existsSync(heldToolFiles(`${marker}.0`).started) && modelUpdates().length > 0,
      "parent provider receives completed commentary before held child finishes");
    const child = getAgent("commentary-child", sessionId)!;
    expect(child.status).toBe("running");
    expect(existsSync(heldToolFiles(`${marker}.0`).ended)).toBe(false);
    expect(updates()).toHaveLength(1);
    expect(updates()[0].content).toContain("child blocker and ETA");
    expect(updates()[0].content).not.toContain("PRIVATE_THINKING_DO_NOT_FORWARD");
    expect(updates()[0].content).not.toContain("faux_hold");
    expect(updates()[0].content).not.toContain('"final_response"');
    expect(completions(parentFile)).toHaveLength(0);
    await until(() => toolResults(parentFile, "read_agent_response").length === 1,
      "parent reads unchanged final-response API while child still runs");
    const response = text(toolResults(parentFile, "read_agent_response")[0].message.content);
    expect(response).toContain('"status": "running"');
    expect(response).not.toContain("child blocker and ETA");
    expect(response).not.toContain("finalResponse");
    for (const call of modelUpdates()) {
      const notifications = call.messages.filter((message: any) => message.role === "user"
        && text(message.content).includes('"commentary":'));
      expect(notifications).toHaveLength(1);
    }
    // Empty completed text and tool arguments do not create another notification.
    writeFileSync(heldToolFiles(`${marker}.0`).release, "release first");
    await until(() => existsSync(heldToolFiles(`${marker}.1`).started), "empty commentary tool starts");
    expect(updates()).toHaveLength(1);
    expect(completions(parentFile)).toHaveLength(0);
    writeFileSync(heldToolFiles(`${marker}.1`).release, "release empty");
    await until(() => existsSync(heldToolFiles(`${marker}.2`).started) && updates().length === 2,
      "second distinct completed message arrives once");
    expect(updates()[1].content).toContain("second child update");
    writeFileSync(heldToolFiles(`${marker}.2`).release, "finish child");
    await until(() => completions(parentFile).length === 1 && getAgent("commentary-child", sessionId)!.status === "completed",
      "one final completion remains separate from updates");
    await until(async () => !(await rpc.request({ type: "get_state" })).isStreaming, "parent consumes final");
    expect(updates()).toHaveLength(2);
    expect(completions(parentFile)[0].content).toContain('"final_response": "child final result"');
    expect(getAgent("commentary-child", sessionId)!.finalResponse).toBe("child final result");
    const inputs = jsonl(providerCallsFile(parentFile)).at(-1).messages.filter((message: any) => message.role === "user")
      .map((message: any) => text(message.content));
    expect(inputs.filter((value: string) => value.includes('"commentary": "child blocker and ETA"'))).toHaveLength(1);
    expect(inputs.filter((value: string) => value.includes('"commentary": "second child update"'))).toHaveLength(1);
    expect(inputs.filter((value: string) => value.includes('"final_response": "child final result"'))).toHaveLength(1);
    expect(inputs.join("\n")).not.toContain("PRIVATE_THINKING_DO_NOT_FORWARD");
  } finally {
    await rpc.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest("commentary completed during pause survives save/reopen and reaches the parent once on unpause", async () => {
  const { getAgent, getRunsDir, parentScopeKey } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "paused-commentary-"));
  const parentFile = join(cwd, "parent.jsonl");
  const marker = join(cwd, "child");
  const templates = join(getAgentDir(), "pi-codex-subagents", "agents");
  mkdirSync(templates, { recursive: true });
  const templateFile = join(templates, "source-commentary.md");
  writeFileSync(templateFile, `---\nname: source-commentary\nprovider: faux\nmodel: faux-1\nextensions: ${heldExtension}\n---\n`);
  let rpc = sourceRpc(cwd, parentFile, false, [productionIndex], { PI_TEST_CAPTURE_CONTEXT: "1" });
  const updates = () => SessionManager.open(parentFile).getBranch().filter((entry: any) =>
    entry.type === "custom_message" && entry.customType === "pi-codex-subagent-commentary") as any[];
  try {
    const { sessionId } = await rpc.request({ type: "get_state" });
    const groupFile = join(getRunsDir(), parentScopeKey(sessionId), "group.json");
    const group = () => JSON.parse(readFileSync(groupFile, "utf8"));
    await rpc.request({ type: "prompt", message: `parent-commentary-task:${JSON.stringify({ path: marker, holdResponse: true })}` });
    await until(() => existsSync(`${marker}.response-started`) && rpc.records.some(record =>
      record.type === "tool_execution_start" && record.toolName === "wait_agent"),
      "child provider in flight and parent waiting before pause");
    const callsBeforePause = jsonl(providerCallsFile(parentFile)).length;
    const pause = rpc.request({ type: "prompt", message: "/pause" });
    void pause.catch(() => {});
    await until(() => existsSync(groupFile) && group().phase === "preparing", "parent pause owns subsequent delivery");
    writeFileSync(`${marker}.response-release`, "complete admitted provider response after pause");
    await until(() => existsSync(heldToolFiles(`${marker}.0`).pauseRequested), "child held tool observes native pause");
    expect(updates()).toHaveLength(0);
    writeFileSync(heldToolFiles(`${marker}.0`).release, "finish admitted tool");
    await pause;
    expect(group().phase).toBe("saved");
    expect(group().completions.mailbox.filter((event: any) => event.commentary === "child blocker and ETA")).toHaveLength(1);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(callsBeforePause);
    expect(await rpc.close()).toBe(0);
    rpc = sourceRpc(cwd, parentFile, false, [productionIndex], { PI_TEST_CAPTURE_CONTEXT: "1" });
    expect((await rpc.request({ type: "get_state" })).pauseState).toBe("paused");
    expect(updates()).toHaveLength(0);
    writeFileSync(heldToolFiles(`${marker}.1`).release, "future empty tool");
    writeFileSync(heldToolFiles(`${marker}.2`).release, "future commentary tool");
    await rpc.request({ type: "prompt", message: "/unpause" });
    await until(() => completions(parentFile).length === 1 && getAgent("commentary-child", sessionId)!.status === "completed",
      "restored child completes and parent receives buffered update and final");
    await until(async () => !(await rpc.request({ type: "get_state" })).isStreaming, "restored parent consumes notifications");
    expect(updates().filter(entry => entry.content.includes("child blocker and ETA"))).toHaveLength(1);
    expect(updates()).toHaveLength(2);
    expect(completions(parentFile)[0].content).toContain("child final result");
    const finalInput = jsonl(providerCallsFile(parentFile)).at(-1).messages.filter((message: any) => message.role === "user")
      .map((message: any) => text(message.content));
    expect(finalInput.filter((value: string) => value.includes('"commentary": "child blocker and ETA"'))).toHaveLength(1);
    const calls = jsonl(providerCallsFile(parentFile)).length;
    await rpc.request({ type: "prompt", message: "/unpause" });
    expect(updates()).toHaveLength(2);
    expect(jsonl(providerCallsFile(parentFile))).toHaveLength(calls);
  } finally {
    await rpc.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);

sourceTest.each(["terminate", "stop-continuation"])("native %s distinguishes intermediate text from final delivery", async mode => {
  const { AgentManager, getAgent } = await import("../core.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "commentary-terminal-"));
  const parentFile = join(cwd, "parent.jsonl");
  const marker = join(cwd, "child");
  const templates = join(getAgentDir(), "pi-codex-subagents", "agents");
  mkdirSync(templates, { recursive: true });
  const templateFile = join(templates, "source-commentary.md");
  writeFileSync(templateFile, `---\nname: source-commentary\nprovider: faux\nmodel: faux-1\ntools: +faux_terminate\nextensions: ${heldExtension}\n---\n`);
  for (let index = 0; index < 3; index++) writeFileSync(heldToolFiles(`${marker}.${index}`).release, "complete tool");
  const rpc = sourceRpc(cwd, parentFile, false, [productionIndex], { PI_TEST_CAPTURE_CONTEXT: "1" });
  try {
    const { sessionId } = await rpc.request({ type: "get_state" });
    await rpc.request({ type: "prompt", message: `parent-commentary-task:${JSON.stringify({ path: marker, mode })}` });
    await until(() => completions(parentFile).length === 1 && getAgent("commentary-child", sessionId)!.status === "completed",
      "child genuinely settles after native terminal/continuation boundary");
    await until(async () => !(await rpc.request({ type: "get_state" })).isStreaming, "parent consumes final notification");
    const lastInput = jsonl(providerCallsFile(parentFile)).at(-1).messages.filter((message: any) => message.role === "user")
      .map((message: any) => text(message.content));
    const expected = mode === "terminate" ? "terminal tool text" : "child final result";
    expect(lastInput.filter((value: string) => value.includes(expected)), JSON.stringify({ lastInput,
      completion: completions(parentFile)[0].content, child: getAgent("commentary-child", sessionId) })).toHaveLength(1);
    if (mode === "terminate") {
      expect(completions(parentFile)[0].content).toContain('"final_response_reported_as_commentary": true');
      expect(completions(parentFile)[0].content).not.toContain("terminal tool text");
    } else {
      expect(lastInput.filter((value: string) => value.includes('"commentary": "stopped text before continuation"'))).toHaveLength(1);
      expect(completions(parentFile)[0].content).toContain('"final_response": "child final result"');
    }
    // New Manager reads persisted final state through the same final-only response
    // and wait interfaces, without adopting or modifying the live parent's work.
    const reader = new AgentManager();
    try {
      await reader.ready();
      expect(reader.readAgentResponse("commentary-child", sessionId).finalResponse).toBe(expected);
      expect((await reader.waitAgent(sessionId, ["commentary-child"])).event?.finalResponse).toBe(expected);
      expect((await reader.waitAllAgents(sessionId, ["commentary-child"])).responses[0].finalResponse).toBe(expected);
    } finally { await reader.shutdown(); }
  } finally {
    await rpc.close();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 30000);
