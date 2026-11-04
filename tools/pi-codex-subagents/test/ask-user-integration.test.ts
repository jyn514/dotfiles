import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fauxAssistantMessage, fauxProvider, fauxToolCall, type FauxResponseFactory } from "@earendil-works/pi-ai/providers/faux";
import {
  createAgentSessionFromServices, createAgentSessionServices, getAgentDir,
  ModelRuntime, SessionManager, SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { getAgent } from "../core.ts";
import { jsonl, productionIndex, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
const askSource = resolve(import.meta.dir, "../../../config/pi-agent/pi-extensions/ask-user.ts");

/** Actual async question extension + native TUI-bound parent + RPC child.
 * Only model I/O and the browser's human interaction are fixtures. Neither
 * extension-channel transport nor question persistence/delivery is doubled.
 */
sourceTest("child ask_user reaches the parent's UI and a late answer resumes only that saved child", async () => {
  if (!process.env.PI_TEST_OWNED_ROOT) throw new Error("Use test/run-source-tests.ts");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT, "ask-user-"));
  const template = `questions-${randomUUID()}`;
  const templates = join(getAgentDir(), "pi-codex-subagents", "agents");
  mkdirSync(templates, { recursive: true });
  const templateFile = join(templates, `${template}.md`);
  writeFileSync(templateFile, `---\nname: ${template}\nprovider: faux\nmodel: faux-1\nthinking: off\nextensions: ${askSource}\n---\n`);
  const faux = fauxProvider();
  const modelRuntime = await ModelRuntime.create({ authPath: join(cwd, "auth.json"), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false });
  modelRuntime.registerNativeProvider(faux.provider);
  const settingsManager = SettingsManager.create(cwd, getAgentDir(), { projectTrusted: true });
  settingsManager.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } });
  const prompts = new Map<string, { prompt: any; respond(answer: string): void }>();
  const errors: any[] = [];
  let promptSequence = 0;
  let widget: string[] | undefined;
  const services = await createAgentSessionServices({
    cwd, agentDir: getAgentDir(), modelRuntime, settingsManager,
    resourceLoaderOptions: {
      noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      additionalExtensionPaths: [productionIndex, askSource],
      extensionFactories: [pi => {
        let adapter: any;
        const request = (options: any) => new Promise(resolve => {
          const id = `browser-native-${++promptSequence}`;
          const prompt = { ...options, id };
          adapter.onRequest(prompt);
          prompts.set(id, { prompt, respond(answer) {
            prompts.delete(id);
            resolve({ id, answer, source: "dashboard" });
          } });
        });
        pi.events.on("prompt:register-adapter", (value: any) => {
          adapter = value;
          adapter.setRespond(() => {});
          adapter.setCancel((id: string) => { prompts.delete(id); });
        });
        pi.events.on("prompt:request-bus", () => pi.events.emit("prompt:set-bus-request", { request }));
      }],
    },
  });
  const { session, extensionsResult } = await createAgentSessionFromServices({ services,
    sessionManager: SessionManager.create(cwd), model: faux.getModel(), thinkingLevel: "off", noTools: "builtin" });
  expect(extensionsResult.errors).toEqual([]);
  await session.bindExtensions({ mode: "tui", uiContext: {
    notify(text: string, type: string) { if (type === "error") errors.push(text); },
    setWidget(key: string, content: string[] | undefined) { if (key === "ask-user") widget = content; },
  } as any, onError: error => errors.push(error) });
  const parentId = session.sessionManager.getSessionId();
  const respond: FauxResponseFactory = () => { faux.appendResponses([respond]); return fauxAssistantMessage("parent remains available"); };
  try {
    // A parent-local question and a sibling distinguish actual child routing
    // from accidental forwarding into the root or a different worker.
    faux.setResponses([fauxAssistantMessage(fauxToolCall("ask_user", { questions: [
      { title: "parent-local", question: "Keep parent question?" },
    ] }), { stopReason: "toolUse" }), respond]);
    await session.prompt("queue parent question");
    expect([...prompts.values()].some(({ prompt }) => prompt.question === "parent-local")).toBe(true);
    faux.setResponses([fauxAssistantMessage([
      fauxToolCall("spawn_agent", { task_name: "desktop", agent_type: template,
        message: `invoke-tool:${JSON.stringify({ name: "ask_user", args: { questions: [
          { title: "Plover executable", question: "Which executable?", options: ["AppImage", "/usr/bin/plover"] },
        ] } })}` }),
      fauxToolCall("spawn_agent", { task_name: "sibling", agent_type: template, message: "remain independent" }),
    ], { stopReason: "toolUse" }), respond]);
    await session.prompt("start child question test");
    await until(() => getAgent("desktop", parentId)?.status === "completed" && getAgent("sibling", parentId)?.status === "completed",
      "both real RPC children settle without holding processes for human input", 20000);
    const desktop = getAgent("desktop", parentId)!;
    const sibling = getAgent("sibling", parentId)!;
    const siblingBefore = jsonl(sibling.sessionFile!);
    const childEntries = jsonl(desktop.sessionFile!);
    const queued = childEntries.filter(e => e.type === "custom" && e.customType === "dotfiles-ask-user").at(-1).data.questions;
    expect(queued).toHaveLength(1);
    const childPrompt = [...prompts.values()].find(({ prompt }) => prompt.question === "desktop — Plover executable");
    if (!childPrompt) throw new Error(JSON.stringify({ prompts: [...prompts.values()].map(p => p.prompt), errors,
      childResults: childEntries.filter(e => e.message?.role === "toolResult"),
      parentQueue: session.sessionManager.getBranch().filter(e => e.type === "custom" && e.customType === "dotfiles-ask-user"),
    }, null, 2));
    expect(widget).toEqual(["2 pending question(s) · Alt+A to answer"]);
    const parentUserCount = session.messages.filter(m => m.role === "user").length;
    // The process has settled; this must reopen its existing saved session.
    childPrompt!.respond("/usr/bin/plover\nfrom child panel");
    await until(() => jsonl(desktop.sessionFile!).some(e => e.message?.role === "user"
      && typeof e.message.content !== "undefined"
      && JSON.stringify(e.message.content).includes(`Answer to ask_user ${queued[0].id}`)), "answer admitted as child user input", 20000);
    await until(() => getAgent("desktop", parentId)?.status === "completed" && prompts.size === 1
      && widget?.[0] === "1 pending question(s) · Alt+A to answer",
      "resumed child finishes, acknowledges delivery and removes only its presentation", 20000);
    const answered = jsonl(desktop.sessionFile!).filter(e => e.message?.role === "user"
      && JSON.stringify(e.message.content).includes(`Answer to ask_user ${queued[0].id}`));
    expect(answered).toHaveLength(1);
    expect(JSON.stringify(answered[0].message.content)).toContain("/usr/bin/plover\\nfrom child panel");
    expect(session.messages.filter(m => m.role === "user")).toHaveLength(parentUserCount);
    expect(jsonl(sibling.sessionFile!)).toEqual(siblingBefore);
    expect([...prompts.values()][0].prompt.question).toBe("parent-local");
    expect(widget).toEqual(["1 pending question(s) · Alt+A to answer"]);
    expect(jsonl(desktop.sessionFile!).filter(e => e.type === "custom" && e.customType === "dotfiles-ask-user").at(-1).data.questions).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    await session.abort();
    await session.extensionRunner?.emit({ type: "session_shutdown", reason: "exit" });
    session.dispose();
    rmSync(templateFile, { force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
}, 60000);
