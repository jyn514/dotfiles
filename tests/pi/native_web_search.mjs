// Run with Node, not Bun: module mocks must not replace the installed Pi SDK.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const sdkEntry = resolve(packageDir, manifest.exports["."].import);
const { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } =
  await import(pathToFileURL(sdkEntry).href);
const installedRequire = createRequire(sdkEntry);
let aiPackageDir;
for (const modulesDir of installedRequire.resolve.paths("@earendil-works/pi-ai")) {
  const candidate = join(modulesDir, "@earendil-works/pi-ai");
  try {
    await readFile(join(candidate, "package.json"));
    aiPackageDir = candidate;
    break;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}
assert.ok(aiPackageDir, "pi-ai must resolve from the installed SDK");
const aiManifest = JSON.parse(await readFile(join(aiPackageDir, "package.json"), "utf8"));
assert.equal(aiManifest.name, "@earendil-works/pi-ai");
const { InMemoryCredentialStore, getSystemMessageText } =
  await import(pathToFileURL(resolve(aiPackageDir, aiManifest.exports["."].import)).href);
const extensionPath = resolve(dirname(fileURLToPath(import.meta.url)),
  "../../config/pi-agent/pi-extensions/pi-web-search.ts");
const baseUrl = "http://pi-native-web-search.invalid/v1";
const marker = "\uE200cite\uE202turn1search0\uE201";
const source = { type: "url_citation", url: "https://example.invalid/native-(source)", title: "Offline [source]",
  start_index: 18, end_index: 18 + marker.length };
const { Markdown } = await import(pathToFileURL(installedRequire.resolve("@earendil-works/pi-tui")).href);
const markdownTheme = Object.fromEntries([
  "heading", "link", "linkUrl", "code", "codeBlock", "codeBlockBorder", "quote", "quoteBorder",
  "hr", "listBullet", "bold", "italic", "strikethrough", "underline",
].map((name) => [name, (text) => text]));

function responseEvents(answer, withSource) {
  const item = { type: "message", id: "msg_fixture", role: "assistant", status: "completed",
    content: [{ type: "output_text", text: answer, annotations: withSource ? [source] : [] }] };
  return [
    { type: "response.created", response: { id: "resp_fixture", status: "in_progress" } },
    { type: "response.output_item.added", output_index: 0, item: { ...item, content: [] } },
    { type: "response.content_part.added", output_index: 0, content_index: 0,
      part: { type: "output_text", text: "", annotations: [] } },
    { type: "response.output_text.delta", output_index: 0, content_index: 0, delta: answer },
    ...(withSource ? [{ type: "response.output_text.annotation.added", output_index: 0, content_index: 0,
      annotation_index: 0, annotation: source }] : []),
    { type: "response.output_text.done", output_index: 0, content_index: 0, text: answer },
    { type: "response.output_item.done", output_index: 0, item },
    { type: "response.completed", response: { id: "resp_fixture", status: "completed", output: [item],
      usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } } },
  ];
}

function sse(events) {
  return new Response(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("") + "data: [DONE]\n\n",
    { status: 200, headers: { "content-type": "text/event-stream" } });
}

// Built-in Responses serializes and parses the real request/stream. Only its
// HTTP boundary is replaced; no extension handler is invoked by this test.
test("native request injects web search and streamed citations stay on the stored assistant message", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "pi-native-web-search-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const cwd = join(root, "project");
  const agentDir = join(root, "agent");
  await Promise.all([mkdir(cwd), mkdir(agentDir)]);
  const requests = [];
  const streamEvents = [];
  const notificationKinds = new Set();
  const endedMessages = [];
  const guidance = [];
  let responsesCount = 0;
  // Fail closed: even accidental model discovery or retries cannot contact a
  // real endpoint. No inherited credential store is opened; this literal is a
  // dummy value required by the built-in OpenAI client, never a paid API key.
  t.mock.method(globalThis, "fetch", async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    assert.ok(url === `${baseUrl}/responses` || url === `${baseUrl}/chat/completions`,
      `unexpected network request: ${url}`);
    const body = JSON.parse(init?.body ?? await input.clone().text());
    requests.push({ url, body });
    if (url.endsWith("/responses")) {
      responsesCount++;
      return sse(responseEvents(`Offline answer ${responsesCount}. ${marker}`, responsesCount === 1));
    }
    return sse([
      { id: "chat_fixture", object: "chat.completion.chunk", choices: [{ index: 0,
        delta: { role: "assistant", content: "Unsupported offline answer." }, finish_reason: null }] },
      { id: "chat_fixture", object: "chat.completion.chunk", choices: [{ index: 0,
        delta: {}, finish_reason: "stop" }] },
    ]);
  });
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: join(agentDir, "models-store.json"), allowModelNetwork: false, refreshOnCreate: false,
  });
  for (const provider of ["offline-search-responses", "offline-search-unsupported"]) {
    await modelRuntime.setRuntimeApiKey(provider, "offline-not-a-credential");
  }
  const loader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: [extensionPath], systemPrompt: "Offline native web-search regression.",
    extensionFactories: [(pi) => {
      for (const [name, api] of [["offline-search-responses", "openai-responses"],
        ["offline-search-unsupported", "openai-completions"]]) {
        pi.registerProvider(name, { baseUrl, api, apiKey: "offline-not-a-credential",
          models: [{ id: "fixture", name: "Offline fixture", reasoning: false, input: ["text"],
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 256 }] });
      }
      // SDK 0.99 emits data; installed 0.85.1 emits event.payload. Observe
      // either native notification without manufacturing callback delivery.
      pi.on("provider_stream_event", (event) => {
        notificationKinds.add("provider_stream_event");
        streamEvents.push(structuredClone(event.data));
      });
      pi.on("provider_event", (event) => {
        notificationKinds.add("provider_event");
        streamEvents.push(structuredClone(event.event.payload));
      });
      pi.on("message_end", (event) => {
        if (event.message.role === "assistant") endedMessages.push(structuredClone(event.message));
      });
      pi.on("before_agent_start", (event) => guidance.push(event.systemPromptOptions.sections.web_search));
    }],
  });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const { session, extensionsResult } = await createAgentSession({
    cwd, agentDir, resourceLoader: loader, settingsManager, modelRuntime,
    sessionManager: SessionManager.inMemory(cwd),
    model: { id: "fixture", name: "Offline fixture", provider: "offline-search-responses", api: "openai-responses",
      baseUrl, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 8192, maxTokens: 256 }, tools: [],
  });
  t.after(() => session.dispose());
  assert.deepEqual(extensionsResult.errors, []);
  assert.equal(extensionsResult.extensions[0].path, extensionPath, "load the actual owned TypeScript source");
  await session.prompt("Find an offline source.");
  await session.prompt("Answer without sources this time.");
  await session.setModel(modelRuntime.getModel("offline-search-unsupported", "fixture"));
  await session.prompt("Search is unsupported here.");
  assert.equal(requests.length, 3, "all turns reach a built-in provider through mocked HTTP");
  for (const request of requests.slice(0, 2)) {
    assert.deepEqual(request.body.tools, [{ type: "web_search", search_context_size: "medium" }],
      "the outgoing serialized request contains exactly one stock native search tool");
  }
  assert.ok(!requests[2].body.tools || requests[2].body.tools.length === 0,
    "unsupported API must not receive native search tools");
  assert.match(guidance[0], /Web search is available through the active model provider/);
  assert.match(guidance[1], /Web search is available through the active model provider/);
  assert.equal(guidance[2], undefined, "unsupported API must not receive search guidance");
  const assistants = session.messages.filter((message) => message.role === "assistant");
  assert.equal(assistants.length, 3, "sources must not create a separate assistant message");
  assert.deepEqual(assistants.map((message) => message.stopReason), ["stop", "stop", "stop"]);
  const lastSystem = session.messages.filter((message) => message.role === "system").at(-1);
  assert.equal(getSystemMessageText(lastSystem).includes("Web search is available"), false,
    "unsupported guidance is removed from the native transcript");
  assert.ok(streamEvents.some((event) => event?.type === "response.output_text.annotation.added" &&
    event.annotation.url === source.url), "a native provider notification delivers the streamed annotation data");
  assert.equal(notificationKinds.size, 1, "each SDK emits only one native notification shape");
  t.diagnostic(`Pi ${manifest.version}: ${[...notificationKinds].join(", ")}`);
  const text = (message) => message.content.filter((block) => block.type === "text").map((block) => block.text).join("\n");
  assert.match(text(assistants[0]), /^Offline answer 1\./);
  assert.equal(text(assistants[0]).split(source.url).length - 1, 1, "source appears once on the answer itself");
  assert.equal(text(assistants[0]), "Offline answer 1. [Offline \\[source\\]](<https://example.invalid/native-(source)>)");
  const labels = [];
  const rendered = new Markdown(text(assistants[0]), 0, 0, {
    ...markdownTheme, link: (label) => { labels.push(label); return label; },
  }).render(120).join("\n");
  assert.deepEqual(labels, [source.title], "the escaped title renders as exactly one link label");
  assert.ok(rendered.includes(source.url), "the real Markdown renderer recognizes the citation URL");
  assert.ok(!rendered.includes(marker), "provider citation markup must not reach the rendered answer");
  assert.equal(text(assistants[1]), `Offline answer 2. ${marker}`,
    "without annotations, never guess an inline URL from an earlier turn");
  assert.deepEqual(endedMessages, assistants, "message_end replacement survives in the real session transcript");
  assert.equal(text(assistants[1]).includes(source.url), false, "collector resets between turns");
  assert.equal(text(assistants[2]).includes(source.url), false, "unsupported turn inherits no stale citations");
});
