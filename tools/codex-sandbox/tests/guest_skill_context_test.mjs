import assert from "node:assert/strict";
import { existsSync, mkdtempSync, realpathSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const cli = join(homedir(), ".local/share/pi/node/node_modules/.bin/pi");

test("guest context rewrites expanded skills in history without changing stored messages", {
  skip: !existsSync(cli) && "requires the host Pi installation",
}, async () => {
  const { discoverAndLoadExtensions, ExtensionRunner, SessionManager } = await import(
    new URL("../index.js", pathToFileURL(realpathSync(cli))).href
  );
  const directory = mkdtempSync(join(tmpdir(), "guest-skill-context-"));
  const savedEnvironment = { ...process.env };
  try {
    process.env.CODEX_SANDBOX_TOOL_CONTAINER = "fixture";
    process.env.CODEX_SANDBOX_GUEST_CWD = "/src/repository";
    process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS = JSON.stringify({
      "/home/jyn/.agents/skills": "/home/codex/.agents/skills",
    });
    const loaded = await discoverAndLoadExtensions([
      join(root, "config/agents/pi/pi-extensions/guest-tools.ts"),
    ], directory, directory);
    assert.deepEqual(loaded.errors, []);
    const runner = new ExtensionRunner(
      loaded.extensions, loaded.runtime, directory, SessionManager.inMemory(directory), {},
    );
    const errors = [];
    runner.onError((error) => errors.push(error));
    const skill = '<skill name="jj-workflow" location="/home/jyn/.agents/skills/jj-workflow/SKILL.md">\n'
      + 'References are relative to /home/jyn/.agents/skills/jj-workflow.\n\n'
      + 'Read /home/jyn/.agents/skills/spec-review/SKILL.md.\n</skill>\n\nreview this';
    const image = { type: "image", data: "fixture", mimeType: "image/png" };
    const messages = [
      { role: "user", content: skill, timestamp: 1 },
      { role: "user", content: [{ type: "text", text: skill }, image], timestamp: 2 },
      { role: "user", content: "inspect /home/jyn/.agents/skills", timestamp: 3 },
      { role: "assistant", content: [{ type: "text", text: skill }], timestamp: 4 },
      { role: "toolResult", content: [{ type: "text", text: skill }], timestamp: 5 },
    ];
    const original = structuredClone(messages);
    const rewritten = await runner.emitContext(messages);
    assert.deepEqual(errors, []);
    const expected = skill.replaceAll("/home/jyn/.agents/skills", "/home/codex/.agents/skills");
    assert.equal(rewritten[0].content, expected);
    assert.equal(rewritten[1].content[0].text, expected);
    assert.deepEqual(rewritten[1].content[1], image);
    assert.deepEqual(rewritten.slice(2), original.slice(2));
    assert.deepEqual(messages, original);
    assert.deepEqual(await runner.emitContext(rewritten), rewritten);
  } finally {
    for (const key of Object.keys(process.env)) {
      if (!(key in savedEnvironment)) delete process.env[key];
    }
    Object.assign(process.env, savedEnvironment);
    rmSync(directory, { recursive: true, force: true });
  }
});
