// Exercise normal discovery, not an explicitly injected skill list.
import assert from "node:assert/strict";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const packageDir = process.env.PI_PACKAGE_DIR ?? "/opt/agent-pi/src/packages/coding-agent";
const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
const { DefaultResourceLoader, formatSkillsForPrompt, SettingsManager } = await import(
  pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href);

test("shared discovery advertises work selection and reflects installed description changes", async t => {
  const home = await mkdtemp(join(tmpdir(), "work-selection-discovery-"));
  const previousHome = process.env.HOME;
  process.env.HOME = home;
  t.after(async () => {
    if (previousHome === undefined) delete process.env.HOME;
    else process.env.HOME = previousHome;
    await rm(home, { recursive: true, force: true });
  });
  const installed = join(home, ".agents/skills");
  await mkdir(join(home, ".agents"), { recursive: true });
  await cp(join(root, "skills"), installed, { recursive: true });
  const loader = new DefaultResourceLoader({
    cwd: home,
    agentDir: join(home, ".pi/agent"),
    settingsManager: SettingsManager.inMemory({ packages: [] }),
    noExtensions: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  });
  await loader.reload();
  let { skills, diagnostics } = loader.getSkills();
  assert.deepEqual(diagnostics, []);
  for (const name of ["work-selection", "autonomous-work", "creative-inquiry"]) {
    const matches = skills.filter(skill => skill.name === name);
    assert.equal(matches.length, 1, `expected one normally discovered ${name}`);
    assert.equal(matches[0].disableModelInvocation, false);
    assert.ok(formatSkillsForPrompt([matches[0]]).includes(name));
  }

  // Descriptions come from the installed authority, not a caller's copied policy.
  const path = join(installed, "work-selection/SKILL.md");
  const original = await readFile(path, "utf8");
  const changed = original.replace(/^(description: .+)$/m, "$1 Discovery change fixture.");
  assert.notEqual(changed, original);
  await writeFile(path, changed);
  await loader.reload();
  ({ skills, diagnostics } = loader.getSkills());
  assert.deepEqual(diagnostics, []);
  assert.ok(skills.find(skill => skill.name === "work-selection")?.description
    .endsWith("Discovery change fixture."));
  assert.ok(formatSkillsForPrompt(skills).includes("Discovery change fixture."));

  // A likely discovery regression is observable even if the body still exists.
  await writeFile(path, original.replace(/^description: .+\n/m, ""));
  await loader.reload();
  ({ skills, diagnostics } = loader.getSkills());
  assert.equal(skills.some(skill => skill.name === "work-selection"), false);
  assert.ok(diagnostics.some(diagnostic => diagnostic.path === path));
  assert.ok(skills.some(skill => skill.name === "autonomous-work"));
});
