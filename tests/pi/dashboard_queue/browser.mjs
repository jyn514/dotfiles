import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const { chromium } = await import(pathToFileURL(process.env.DASHBOARD_TEST_PLAYWRIGHT).href);
const result = { consoleErrors: [], sockets: [], checks: [] };
const expectedIds = JSON.parse(process.env.PROBE_QUESTION_IDS).slice(0, 3);
const titles = ["Literal queue option", "Multiline queue answer", "Native terminal answer"];
const origin = process.env.PROBE_ORIGIN;
const modelRequestCount = () => Math.max(0, ...readFileSync(process.env.PROBE_EVENTS, "utf8").split("\n")
  .filter(line => line.startsWith('{"type":"provider-request",')).map(line => JSON.parse(line).index));
const save = () => writeFileSync(process.env.PROBE_BROWSER_RESULT, JSON.stringify(result, null, 2));
const wait = async (predicate, label, timeout = 20_000) => {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${label}`);
};
let browser;
try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.DASHBOARD_TEST_CHROMIUM });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });
  await page.route("**/*", route => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
  page.on("pageerror", error => result.consoleErrors.push(String(error)));
  page.on("websocket", socket => {
    const entry = { sent: [], received: [] };
    result.sockets.push(entry);
    socket.on("framesent", frame => {
      try {
        const message = JSON.parse(String(frame.payload));
        if (["prompt_response", "session_subscribe", "subscribe"].includes(message.type)) entry.sent.push(message);
      } catch { /* Other protocol frames are irrelevant to the queue assertion. */ }
    });
    socket.on("framereceived", frame => {
      try {
        const message = JSON.parse(String(frame.payload));
        if (["prompt_request", "prompt_dismiss", "prompt_cancel", "session_added", "session_updated", "sessions_list"].includes(message.type)) entry.received.push(message);
      } catch { /* Binary/other frames are not queue evidence. */ }
    });
  });
  await page.goto(process.env.PROBE_URL, { waitUntil: "domcontentloaded", timeout: 30_000 });
  const skip = page.getByRole("button", { name: "Skip", exact: true });
  // Startup onboarding can appear after the initial document commits.
  await wait(async () => await skip.isVisible() || await page.getByText("Dashboard queue regression", { exact: true }).first().isVisible(), "onboarding or registered session");
  if (await skip.isVisible()) await skip.click();
  await page.getByText("Dashboard queue regression", { exact: true }).first().click({ timeout: 20_000 });
  const card = title => page.getByText(title, { exact: true })
    .locator('xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " rounded-lg ")][1]')
    .filter({ has: page.locator("textarea") });
  for (const title of titles) await card(title).waitFor({ state: "visible" });
  const allReceived = () => result.sockets.flatMap(socket => socket.received);
  const queueRequests = () => allReceived().filter(message => message.type === "prompt_request" && message.prompt.pipeline === "dotfiles-ask-user");
  await wait(() => new Set(queueRequests().map(message => message.prompt.metadata.questionId)).size === 3, "three real queue prompts via bridge replay");
  const firstRequests = queueRequests();
  const firstPromptIds = [...new Set(firstRequests.map(message => message.promptId))].sort();
  assert.equal(firstPromptIds.length, 3, "one bus prompt ID per pending question");
  assert.deepEqual([...new Set(firstRequests.map(message => message.prompt.metadata.questionId))].sort(), [...expectedIds].sort());
  for (const message of firstRequests) {
    assert.equal(message.prompt.metadata.kind, "queue-question");
    assert.equal(message.prompt.type, "select");
    assert.equal(message.component.type, "generic-dialog");
  }
  assert.equal(await page.getByRole("button", { name: "Obsolete", exact: true }).count(), 0, "model cancellation is absent from replay");
  assert.equal(await page.getByRole("button", { name: "Cancel", exact: true }).count(), 1, "only literal option, no destructive cancellation controls");
  result.checks.push("real bridge queue metadata and default native renderer; model cancellation absent");
  const idleStatus = async () => {
    const response = await page.request.get(`${origin}/api/sessions?id=${process.env.PROBE_SESSION_ID}`);
    assert.equal(response.status(), 200);
    const body = await response.json();
    assert.equal(body.data.length, 1);
    const session = body.data[0];
    if (session.status !== "idle" || session.currentTool) return false;
    result.pendingSessionStatus = { status: session.status, currentTool: session.currentTool ?? null };
    return true;
  };
  await wait(idleStatus, "pending queue does not falsely claim blocked/busy tool state");
  const priorSockets = result.sockets.length;
  await page.reload({ waitUntil: "domcontentloaded" });
  for (const title of titles) await card(title).waitFor({ state: "visible" });
  await wait(() => result.sockets.length > priorSockets && result.sockets.slice(priorSockets).some(socket => socket.received.filter(message => message.type === "prompt_request" && message.prompt.pipeline === "dotfiles-ask-user").length === 3), "reconnect replay");
  const replay = result.sockets.slice(priorSockets).flatMap(socket => socket.received).filter(message => message.type === "prompt_request" && message.prompt.pipeline === "dotfiles-ask-user");
  assert.deepEqual([...new Set(replay.map(message => message.promptId))].sort(), firstPromptIds, "reconnect replays the same pending bus IDs, not new controls");
  for (const title of titles) assert.equal(await card(title).count(), 1);
  await idleStatus();
  result.checks.push("authenticated browser reload preserves three pending questions without duplicate controls or false busy state");

  await card(titles[0]).getByRole("button", { name: "Cancel", exact: true }).click();
  await wait(async () => await card(titles[0]).count() === 0, "literal Cancel answer completes first question");
  await wait(() => modelRequestCount() >= 4, "literal option reaches actual model continuation");
  const textCard = card(titles[1]);
  await textCard.locator("textarea").fill(process.env.PROBE_MULTILINE);
  await textCard.getByRole("button", { name: "Submit", exact: true }).click();
  await wait(async () => await card(titles[1]).count() === 0, "multiline free text answer completes second question");
  await wait(() => modelRequestCount() >= 5, "multiline answer reaches actual model continuation");
  result.checks.push("literal Cancel and multiline free text submitted through native SelectRenderer");
  save();
  writeFileSync(process.env.PROBE_TERMINAL_READY, "ready\n");
  await wait(async () => await card(titles[2]).count() === 0, "native terminal answer dismisses browser control", 30_000);
  await wait(() => existsSync(process.env.PROBE_TERMINAL_DONE), "terminal steering persisted");
  const sent = result.sockets.flatMap(socket => socket.sent).filter(message => message.type === "prompt_response");
  assert.equal(sent.length, 2, "terminal completion must not manufacture a browser response");
  for (const message of sent) {
    assert.equal(message.source, "dashboard-default", "native Dashboard adapter response protocol");
    assert.equal(message.sessionId, process.env.PROBE_SESSION_ID);
    assert.equal(message.cancelled ?? false, false);
    assert.ok(firstPromptIds.includes(message.promptId));
  }
  assert.deepEqual(sent.map(message => message.answer), ["Cancel", process.env.PROBE_MULTILINE]);
  result.browserResponses = sent;
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByText("Dashboard queue regression", { exact: true }).first().waitFor();
  // Wait for actual session subscription/replay, not just the shell document.
  await wait(() => result.sockets.at(-1)?.sent.some(message => ["session_subscribe", "subscribe"].includes(message.type)), "final session subscription");
  await page.waitForTimeout(500);
  for (const title of titles) assert.equal(await card(title).count(), 0);
  assert.equal(result.sockets.at(-1).received.filter(message => message.type === "prompt_request" && message.prompt.pipeline === "dotfiles-ask-user").length, 0, "completed queue does not return on reconnect");
  assert.deepEqual(result.consoleErrors, []);
  result.checks.push("terminal answer removes browser question; final reconnect has no pending controls");
  result.status = "passed";
} catch (error) {
  result.error = error.stack ?? String(error);
  if (browser) {
    const page = browser.contexts()[0]?.pages()[0];
    if (page) result.failureText = (await page.locator("body").innerText()).slice(-20_000);
  }
  process.exitCode = 1;
} finally {
  save();
  await browser?.close();
}
