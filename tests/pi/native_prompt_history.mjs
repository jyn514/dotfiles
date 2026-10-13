// Load through installed Pi so the picker uses the real Input and SelectList.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const packageDir = process.env.PI_PACKAGE_DIR || "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
const { DefaultResourceLoader, SessionManager, SettingsManager } =
  await import(pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href);
const extensionPath = resolve(dirname(fileURLToPath(import.meta.url)),
  "../../config/pi-agent/pi-extensions/prompt-history-search.ts");

async function openPicker(t, prompts, { query = "", saved = [] } = {}) {
  const root = await mkdtemp(join(tmpdir(), "pi-native-history-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const agentDir = join(root, "agent");
  await mkdir(agentDir);
  const manager = SessionManager.create(root, join(root, "current"));
  for (const [index, text] of prompts.entries()) {
    manager.appendMessage({ role: "user", content: text, timestamp: index + 1 });
  }
  const historyDir = join(process.env.HOME, ".pi/agent/sessions", root.split("/").at(-1));
  await mkdir(historyDir, { recursive: true });
  t.after(() => rm(historyDir, { recursive: true, force: true }));
  await writeFile(join(historyDir, "older.jsonl"), saved.map((text, index) => JSON.stringify({
    type: "message", message: { role: "user", content: text, timestamp: 100 + index },
  })).join("\n"));
  const loader = new DefaultResourceLoader({
    cwd: root, agentDir, settingsManager: SettingsManager.inMemory(),
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: [extensionPath],
  });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  const extension = loader.getExtensions().extensions.find(({ path }) => path === extensionPath);
  assert.ok(extension, "installed Pi loaded the edited extension");
  let component, close, restored;
  const ready = Promise.withResolvers();
  const theme = { fg: (_color, text) => text, bold: (text) => text };
  const run = extension.commands.get("history-search").handler("", {
    sessionManager: manager,
    ui: {
      getEditorText: () => query,
      setEditorText: (text) => { restored = text; },
      setStatus() {},
      custom(factory) {
        return new Promise((done) => {
          close = done;
          component = factory({ requestRender() {
            if (!component.render(80).at(-1).includes("loading older prompts")) ready.resolve();
          } }, theme, undefined, done);
          component.focused = true;
        });
      },
    },
  });
  t.after(() => close(null));
  return { component, ready: ready.promise, run, restored: () => restored };
}

test("history keeps the exact selected prompt when saved history arrives", async (t) => {
  const raw = "alpha\n  beta";
  const picker = await openPicker(t, [raw, "alpha beta"], { saved: ["newest saved prompt"] });
  assert.match(picker.component.render(80).at(-1), /loading older prompts/);
  picker.component.handleInput("\x1b[B");
  await picker.ready;
  picker.component.handleInput("\r");
  await picker.run;
  assert.equal(picker.restored(), raw, "display normalization must not change the restored text");
});

test("history search retains case-insensitive terms anywhere in a prompt", async (t) => {
  const picker = await openPicker(t, ["fix unrelated tests", "please fix the parser"], {
    query: "PARSER fix", saved: ["document parser behavior"],
  });
  await picker.ready;
  picker.component.handleInput("\r");
  await picker.run;
  assert.equal(picker.restored(), "please fix the parser");
});

test("history list scrolls, wraps, and treats ctrl+r as next selection", async (t) => {
  const prompts = Array.from({ length: 13 }, (_, index) => `prompt ${index}`);
  const picker = await openPicker(t, prompts);
  await picker.ready;
  picker.component.handleInput("\x1b[A");
  assert.ok(picker.component.render(80).some((line) => line.includes("prompt 0")));
  assert.ok(!picker.component.render(80).some((line) => line.includes("prompt 12")));
  picker.component.handleInput("\x12");
  picker.component.handleInput("\r");
  await picker.run;
  assert.equal(picker.restored(), "prompt 12");
});

test("editing the query resets selection and escape preserves the editor", async (t) => {
  const picker = await openPicker(t, ["first", "second"]);
  await picker.ready;
  picker.component.handleInput("\x1b[B");
  picker.component.handleInput("s");
  assert.ok(picker.component.render(80).some((line) => line.includes("second")));
  picker.component.handleInput("no match");
  assert.ok(picker.component.render(80).includes("No matching prompts"));
  picker.component.handleInput("\x1b");
  await picker.run;
  assert.equal(picker.restored(), undefined);
});
