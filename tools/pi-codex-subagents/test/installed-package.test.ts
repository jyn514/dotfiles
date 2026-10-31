import { expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { DefaultResourceLoader, getAgentDir, SettingsManager } from "@earendil-works/pi-coding-agent";
import { resolveChildExtensionPaths } from "../core.ts";
import { providerCallsFile } from "./held-tool-extension.ts";
import { jsonl, sourceRpc, until } from "./source-runtime.ts";

const sourceTest = test.skipIf(!process.env.PI_TEST_CORE_TSCONFIG);
sourceTest("setup alias loads the tracked package into a native provider without the old monorepo", async () => {
  const dotfiles = resolve(import.meta.dir, "../../..");
  const cwd = mkdtempSync(join(process.env.PI_TEST_OWNED_ROOT!, "installed-"));
  const agentDir = getAgentDir();
  mkdirSync(agentDir, { recursive: true });
  const manifest = JSON.parse(readFileSync(join(dotfiles, "install.conf.json"), "utf8"));
  const links = manifest.find((entry: any) => entry.link).link;
  const mapping = Object.entries(links).find(([, source]) => source === "tools/pi-codex-subagents");
  expect(mapping).toBeDefined();
  const config = join(cwd, "links.json");
  writeFileSync(config, JSON.stringify([...manifest.filter((entry: any) => entry.defaults), { link: Object.fromEntries([mapping!]) }]));
  execFileSync(join(dotfiles, "vendor/dotbot/bin/dotbot"), ["-d", dotfiles, "-c", config], { env: process.env });
  const alias = join(agentDir, "packages/pi-codex-subagents");
  expect(realpathSync(alias)).toBe(realpathSync(resolve(import.meta.dir, "..")));
  const settingsPath = join(agentDir, "settings.json");
  execFileSync("cp", [join(dotfiles, "config/pi-agent/settings.json"), settingsPath]);
  execFileSync("cmp", [join(dotfiles, "config/pi-agent/settings.json"), settingsPath]);
  const settings = SettingsManager.create(cwd, agentDir);
  const declaration = settings.getPackages().find(entry => (typeof entry === "string" ? entry : entry.source) === "./packages/pi-codex-subagents");
  expect(declaration).toBeDefined();
  // No remote package or sibling extension can hide an absent local alias.
  settings.setPackages([declaration!]);
  settings.setExtensionPaths([]);
  await settings.flush();
  const rolePath = join(agentDir, "pi-codex-subagents/SYSTEM.md");
  mkdirSync(join(agentDir, "pi-codex-subagents"), { recursive: true });
  writeFileSync(rolePath, "USER_OWNED_ROLE\n");
  const loader = new DefaultResourceLoader({ cwd, agentDir, settingsManager: settings, noContextFiles: true });
  await loader.reload();
  const loaded = loader.getExtensions();
  expect(loaded.errors).toEqual([]);
  const entry = loaded.extensions.find(extension => realpathSync(extension.path) === realpathSync(join(alias, "index.ts")));
  expect(entry).toBeDefined();
  const selected = await resolveChildExtensionPaths({ cwd, projectTrusted: false, disabledExtensions: ["pi-codex-subagents"] });
  expect(selected.some(path => path === realpathSync(join(alias, "index.ts")))).toBe(false);
  const sessionFile = join(cwd, "installed.jsonl");
  const peer = sourceRpc(cwd, sessionFile, false, []);
  try {
    await peer.request({ type: "prompt", message: "installed-alias-provider-proof" });
    await until(() => peer.records.some(record => record.type === "agent_settled"), "installed alias reaches provider");
    const calls = jsonl(providerCallsFile(sessionFile));
    expect(calls).toHaveLength(1);
    expect(calls[0].tools).toContain("spawn_agent");
    expect(peer.records.some(record => record.type === "message_end" && JSON.stringify(record.message).includes("faux:installed-alias-provider-proof"))).toBe(true);
    expect(readFileSync(rolePath, "utf8")).toBe("USER_OWNED_ROLE\n");
  } finally {
    expect(await peer.close()).toBe(0);
  }
}, 15000);
