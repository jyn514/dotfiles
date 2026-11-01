import { afterEach, expect, test } from "bun:test";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { processOutput } from "../behavioral/unavailable_issue/runtime.ts";
import { guestExecutor } from "../behavioral/unavailable_issue/subagent-transport.ts";
import { launchConfiguration, launchMarker, workerContext, workerPayload } from "../behavioral/unavailable_issue/subagent.ts";

const temporary: string[] = [];
afterEach(async () => { await Promise.all(temporary.splice(0).map(path => rm(path, { recursive: true, force: true }))); });
const config = { mode: "unreadable", image: "image:existing", fixture: "target/fixture", output: "target/new-run" };

test("subagent launch uses one bounded record, not inherited role instructions", () => {
  expect(launchConfiguration(`Delegated role.\n${launchMarker}${JSON.stringify(config)}`)).toEqual(config);
  for (const change of [{ mode: "unknown" }, { fixture: "/host/fixture" }, { output: "target/../source" },
    { output: "target/" }, { image: "" }, { credentials: "forbidden" }]) {
    expect(() => launchConfiguration(`${launchMarker}${JSON.stringify({ ...config, ...change })}`)).toThrow();
  }
  expect(() => launchConfiguration("ordinary task")).toThrow();
  expect(() => launchConfiguration(`${launchMarker}{}\n${launchMarker}{}`)).toThrow();
});

test("effective worker context strips host instructions and launch metadata but retains worker actions", () => {
  const action = { role: "assistant", content: [{ type: "toolCall", name: "read", id: "read-issue", arguments: { path: "/task/issue.md" } }] };
  const denied = { role: "toolResult", toolCallId: "read-issue", content: [{ type: "text", text: "PermissionError" }] };
  const messages = [{ role: "system", content: "Current private host instructions." },
    { role: "user", content: "Inherited context." },
    { role: "user", content: [{ type: "text", text: `${launchMarker}${JSON.stringify(config)}` }] },
    action, denied, { role: "system", content: "Unrelated late system patch." }];
  const tools = ["task_read", "task_edit", "task_write", "task_bash"].map(name => ({ name, description: name, parameters: { type: "object" } }));
  expect(workerContext(messages, "Archived Flower instructions.", "Original parent packet.", tools)).toEqual([
    { role: "system", content: "Archived Flower instructions.", toolsAdded: tools, timestamp: 0 },
    { role: "user", content: [{ type: "text", text: "Original parent packet." }] }, action, denied]);
  expect(() => workerContext([], "system", "packet", tools)).toThrow();
  expect(() => workerContext(messages, "system", "packet", tools.slice(0, 3))).toThrow();
  expect(messages[0].content).toBe("Current private host instructions.");
});

test("provider scrub removes recognized web builtins, retains all four functions, and rejects other tool exposure", () => {
  const functions = ["task_read", "task_edit", "task_write", "task_bash"].map(name => ({ type: "function", name, parameters: { type: "object" } }));
  const payload = { input: "worker context", tools: [...functions, { type: "web_search", search_context_size: "medium" }] };
  expect(workerPayload(payload)).toEqual({ input: "worker context", tools: functions });
  expect(payload.tools.length).toBe(5);
  for (const tools of [functions.slice(0, 3), [...functions, functions[0]],
    [...functions, { type: "computer_use" }], [{ type: "web_search" }]]) {
    expect(() => workerPayload({ tools })).toThrow();
  }
  expect(() => workerPayload({})).toThrow();
});

test("guest transport preserves binary stdin and generated shell-like arguments, then removes scratch inputs", async () => {
  const scratch = await mkdtemp(join(tmpdir(), "unavailable-issue-bridge-' λ-")); temporary.push(scratch);
  const commands: string[] = [];
  const execute = guestExecutor(async (command, signal, onData) => {
    commands.push(command);
    try { await processOutput("bash", ["-c", command], undefined, signal, onData); return { exitCode: 0 }; }
    catch (error: any) { if (typeof error.exitCode !== "number") throw error; return { exitCode: error.exitCode }; }
  }, scratch, path => path);
  const bytes = Buffer.from(Array.from({ length: 100_000 }, (_, index) => index % 256));
  expect(await execute("cat", [], bytes)).toEqual(bytes);
  expect(await readdir(scratch)).toEqual([]);
  // Deterministic Cartesian coverage: quoting must preserve bytes for each argument,
  // independently checked by Bash's printf rather than a second quoting algorithm.
  const atoms = ["", "plain", "'", '"', " ", "\n", "\\", "$HOME", "$(printf injected)", ";exit 9", "💜"];
  const arguments_ = atoms.flatMap(left => atoms.map(right => left + right));
  expect(await execute("printf", ["%s\\0", ...arguments_])).toEqual(Buffer.from(arguments_.map(value => value + "\0").join("")));
  await expect(execute("bash", ["-c", "exit 7"], "discarded input")).rejects.toMatchObject({ exitCode: 7 });
  expect(await readdir(scratch)).toEqual([]);
  expect(commands[0]).not.toContain(bytes.toString("base64"));
});

test("guest transport propagates attachment failures and still removes input files", async () => {
  const scratch = await mkdtemp(join(tmpdir(), "unavailable-issue-failed-")); temporary.push(scratch);
  const execute = guestExecutor(async () => { throw new Error("attachment lost"); }, scratch, path => path);
  await expect(execute("docker", ["inspect", "container"], "owned input")).rejects.toThrow("attachment lost");
  expect(await readdir(scratch)).toEqual([]);
});
