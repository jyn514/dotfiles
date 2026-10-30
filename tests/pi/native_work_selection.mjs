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

test("shared discovery exposes task-specific skills, not optional references, and reflects description changes", async t => {
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
  const reviewSkills = ["spec-review", "audit-spec-against-impl", "completion-audit"];
  for (const name of ["work-selection", "autonomous-work", "creative-inquiry", "architecture-design", "implementation-plan",
    "holistic-writing", "readme-writing", ...reviewSkills]) {
    const matches = skills.filter(skill => skill.name === name);
    assert.equal(matches.length, 1, `expected one normally discovered ${name}`);
    assert.equal(matches[0].disableModelInvocation, false);
    assert.ok(formatSkillsForPrompt([matches[0]]).includes(name));
  }

  for (const retired of ["boundary-declaration", "design-space-scout", "design-deliberation", "second-user",
    "design-for-change", "double-check", "review", "technical-docs"]) {
    assert.equal(skills.some(skill => skill.name === retired), false, `${retired} must not remain registered`);
  }

  // Shared checks and documentation guidance ship without becoming skills.
  for (const reference of ["references/review-evidence.md", "holistic-writing/references/documentation.md"]) {
    const path = join(installed, reference);
    assert.ok((await readFile(path, "utf8")).startsWith("# "));
    assert.equal(skills.some(skill => skill.filePath === path), false);
  }

  // Descriptions come from each installed authority, not a caller's copied policy.
  for (const name of ["work-selection", ...reviewSkills]) {
    const path = join(installed, name, "SKILL.md");
    const original = await readFile(path, "utf8");
    const fixture = `Discovery change fixture for ${name}.`;
    const changed = original.replace(/^(description: .+)$/m, `$1 ${fixture}`);
    assert.notEqual(changed, original);
    await writeFile(path, changed);
    await loader.reload();
    ({ skills, diagnostics } = loader.getSkills());
    assert.deepEqual(diagnostics, []);
    assert.ok(skills.find(skill => skill.name === name)?.description.endsWith(fixture));
    assert.ok(formatSkillsForPrompt(skills).includes(fixture));
    await writeFile(path, original);
  }

  // A missing description drops that task, not the other independently discovered audits.
  const path = join(installed, "spec-review/SKILL.md");
  const original = await readFile(path, "utf8");
  await writeFile(path, original.replace(/^description: .+\n/m, ""));
  await loader.reload();
  ({ skills, diagnostics } = loader.getSkills());
  assert.equal(skills.some(skill => skill.name === "spec-review"), false);
  assert.ok(diagnostics.some(diagnostic => diagnostic.path === path));
  for (const name of ["audit-spec-against-impl", "completion-audit", "autonomous-work"]) {
    assert.ok(skills.some(skill => skill.name === name));
  }
});
