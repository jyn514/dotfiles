// No prompt/LLM: invoke the real SDK's extension-wrapped registered BashTool.
// This complements the native human user_bash /model UI overlap.
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [sdkPath, guestExtension, identityExtension, consumerFixture] = process.argv.slice(2);
const { createAgentSession, DefaultResourceLoader, SessionManager } = await import(pathToFileURL(sdkPath).href);
const runtime = process.env.SIDE_PI_RUNTIME;
const cwd = process.cwd();
const sessions = [];
const quote = text => `'${text.replaceAll("'", "'\\''")}'`;
const command = label => `python3 ${quote(consumerFixture)} consumer ${label}`;
async function load(name) { return JSON.parse(await readFile(join(runtime, name), "utf8")); }
async function wait(name) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try { return await load(name); } catch (error) { if (error.code !== "ENOENT") throw error; }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error(`bounded SDK wait expired: ${name}`);
}
async function makeSession() {
  const resourceLoader = new DefaultResourceLoader({
    cwd, agentDir: process.env.PI_CODING_AGENT_DIR,
    additionalExtensionPaths: [guestExtension, identityExtension],
    noSkills: true, noPromptTemplates: true, noContextFiles: true,
  });
  await resourceLoader.reload();
  const errors = resourceLoader.getExtensions().errors;
  assert.equal(errors.length, 0, JSON.stringify(errors));
  const { session } = await createAgentSession({
    cwd, agentDir: process.env.PI_CODING_AGENT_DIR, resourceLoader,
    sessionManager: SessionManager.inMemory(),
  });
  sessions.push(session);
  await session.bindExtensions({ mode: "rpc", onError: error => { throw new Error(JSON.stringify(error)); } });
  return session;
}
function bash(session, text) {
  const tool = session.agent.state.tools.find(candidate => candidate.name === "bash");
  assert.ok(tool, "native SDK registered bash tool missing");
  return tool.execute(`sdk-bash-${sessions.indexOf(session)}`, { command: text, timeout: 15 },
                      new AbortController().signal);
}
try {
  const a = await makeSession();
  await a.setModel(a.modelRuntime.getModel("side-attribution", "fixture-model-A-raw"));
  const pendingA = bash(a, `${command("SDK_A")} --pause`);
  assert.equal((await wait("SDK_A.started.json")).call_model, "fixture-model-A-raw");
  const b = await makeSession();
  await b.setModel(b.modelRuntime.getModel("side-attribution", "fixture-model-B-raw"));
  const resultB = await bash(b, command("SDK_B"));
  assert.ok(!resultB.isError, JSON.stringify(resultB));
  await writeFile(join(runtime, "SDK_A.release"), "release\n");
  const resultA = await pendingA;
  assert.ok(!resultA.isError, JSON.stringify(resultA));
  const [receiptA, receiptB] = await Promise.all([load("SDK_A.jj.json"), load("SDK_B.jj.json")]);
  assert.equal(receiptA.jj_user, "Pi fixture-model-A-raw");
  assert.equal(receiptB.jj_user, "Pi fixture-model-B-raw");
  assert.equal(receiptA.legacy.modelId, "fixture-model-B-raw");
  assert.equal(receiptA.cwd, process.env.CODEX_SANDBOX_GUEST_CWD);
  assert.equal(receiptB.cwd, process.env.CODEX_SANDBOX_GUEST_CWD);
  assert.equal(a.messages.length, 0, "SDK tool check must not submit a model prompt");
  assert.equal(b.messages.length, 0, "SDK tool check must not submit a model prompt");
  await writeFile(join(runtime, "sdk-attribution.json"), JSON.stringify({
    ctx_model_a: { provider: a.model.provider, modelId: a.model.id },
    ctx_model_b: { provider: b.model.provider, modelId: b.model.id },
    a: receiptA, b: receiptB,
  }));
} finally {
  // Also releases a held guest consumer if a prerequisite assertion fails.
  await writeFile(join(runtime, "SDK_A.release"), "cleanup\n");
  for (const session of sessions) session.dispose();
}
