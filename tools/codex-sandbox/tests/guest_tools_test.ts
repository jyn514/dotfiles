import { test, expect, mock } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { rewritePiResourcePaths } from "../../../config/pi-agent/pi-extensions/guest-tools-core.ts";

test("host Pi resource paths are rewritten to guest paths", () => {
  const host = "/Users/jyn/.local/share/pi/node/node_modules/@earendil-works/pi-coding-agent";
  const guest = "/opt/agent-pi/src/packages/coding-agent";
  const prompt = [
    `Main documentation: ${host}/README.md`,
    `Additional docs: ${host}/docs`,
    `Examples: ${host}/examples`,
  ].join("\n");

  const rewritten = rewritePiResourcePaths(prompt, {
    [`${host}/README.md`]: `${guest}/README.md`,
    [`${host}/docs`]: `${guest}/docs`,
    [`${host}/examples`]: `${guest}/examples`,
  });

  expect(rewritten).not.toContain(host);
  expect(rewritten).toContain(`${guest}/README.md`);
  expect(rewritten).toContain(`${guest}/docs`);
  expect(rewritten).toContain(`${guest}/examples`);
});

test("host project paths are rewritten without touching sibling paths", () => {
  const host = "/Users/jyn/src/personal/lapwing/stint";
  const guest = "/src/personal/lapwing/stint";
  const prompt = [
    `Skill location: ${host}/.agents/skills/spec-review/SKILL.md`,
    `Sibling location: ${host}-old/.agents/skills/spec-review/SKILL.md`,
  ].join("\n");

  const rewritten = rewritePiResourcePaths(prompt, { [host]: guest });

  expect(rewritten).toContain(`${guest}/.agents/skills/spec-review/SKILL.md`);
  expect(rewritten).toContain(`${host}-old/.agents/skills/spec-review/SKILL.md`);
});

// Resolve the installed SDK's public export, as in session_side_test.ts;
// Bun does not resolve NODE_PATH and no checkout node_modules is needed.
const packageDirs = process.env.PI_PACKAGE_DIR ? [process.env.PI_PACKAGE_DIR] : [
  join(homedir(), ".local/share/pi/node/node_modules/@earendil-works/pi-coding-agent"),
  "/opt/agent-pi/src/packages/coding-agent",
];
const installedDir = packageDirs.find(dir => existsSync(join(dir, "package.json")));
if (!installedDir) throw new Error("Installed Pi SDK not found; set PI_PACKAGE_DIR");
const packageDir = realpathSync(installedDir);
const manifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
const publicEntry = manifest.exports?.["."]?.import;
if (manifest.name !== "@earendil-works/pi-coding-agent" || typeof publicEntry !== "string") {
  throw new Error(`Pi package has no supported public import export: ${packageDir}`);
}
const sdk = await import(pathToFileURL(resolve(packageDir, publicEntry)).href);
mock.module("@earendil-works/pi-coding-agent", () => sdk);
const { default: guestTools } = await import("../../../config/pi-agent/pi-extensions/guest-tools.ts");

async function eventually(predicate: () => boolean) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await Bun.sleep(20);
  }
  throw new Error("connector did not reach expected state");
}

test("registered tools and human bash snapshot their own public invocation context", async () => {
  const dir = mkdtempSync(join(tmpdir(), "pi-guest-metadata-"));
  // A holds its transport open while B changes the context and executes.
  const connector = join(import.meta.dir, "fixtures/guest-tool-metadata.py");
  const env = {
    CODEX_SANDBOX_TOOL_CONTAINER: "fixture",
    CODEX_SANDBOX_TOOL_CONNECT: connector,
    CODEX_SANDBOX_GUEST_CWD: dir,
    CODEX_SANDBOX_PI_RESOURCE_PATHS: "{}",
    CODEX_GUEST_CALL_TEST_DIR: dir,
    PI_CALL_MODEL: "stale-env",
    PI_MODEL_FILE: join(dir, "model.json"),
  };
  writeFileSync(env.PI_MODEL_FILE, '{"modelId":"stale-file"}');
  const previous = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  Object.assign(process.env, env);
  const tools = new Map<string, any>();
  const hooks = new Map<string, any>();
  try {
    guestTools({ registerTool: (tool: any) => tools.set(tool.name, tool),
      on: (name: string, hook: any) => hooks.set(name, hook) } as any);
    const ctx = { model: { provider: "provider-a", id: "model-a" } };
    const params = { command: "pause", model: "model-selected-parameter" };
    const a = tools.get("bash").execute("a", params, undefined, undefined, ctx);
    await eventually(() => existsSync(join(dir, "started")));
    // Mutate the actual model object, not just the context reference.
    ctx.model.provider = "provider-b";
    ctx.model.id = "model-b";
    const b = await tools.get("bash").execute("b", { command: "b" }, undefined, undefined, ctx);
    writeFileSync(join(dir, "release"), "");
    const aResult = await a;
    expect(b).toEqual({ tool: "bash", params: { command: "b" },
      model: { provider: "provider-b", modelId: "model-b" } });
    expect(aResult).toEqual({ tool: "bash", params,
      model: { provider: "provider-a", modelId: "model-a" } });

    const human = hooks.get("user_bash")({ command: "human" }, ctx);
    ctx.model.id = "later-model";
    expect(await human.operations.exec("human", dir, { onData() {} })).toEqual({
      tool: "user_bash", params: { command: "human" },
      model: { provider: "provider-b", modelId: "model-b" },
    });
    for (const tool of tools.values()) {
      const result = await tool.execute("unknown", {}, undefined, undefined, { model: undefined });
      expect(result.model).toBeNull();
    }
    const unknown = hooks.get("user_bash")({}, { model: undefined });
    expect((await unknown.operations.exec("unknown", dir, { onData() {} })).model).toBeNull();
    expect(process.env.PI_CALL_MODEL).toBe("stale-env");
    expect(readFileSync(env.PI_MODEL_FILE, "utf8")).toBe('{"modelId":"stale-file"}');
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    rmSync(dir, { recursive: true, force: true });
  }
});
