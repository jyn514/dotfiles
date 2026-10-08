# Agent skills

These skills follow the Agent Skills directory format and are intentionally small and composable. Use them manually at first; automate only the sequences you actually repeat.

## Install

Install the repository through a supported harness, or copy an individual directory from `skills/` into that harness's skill directory.

### Pi

```sh
pi install git:github.com/jyn514/dotfiles
```

### Claude Code

```sh
claude plugin marketplace add jyn514/dotfiles
claude plugin install judgement-yields-navigation@jyn-plugins
```

### Codex

Once published, install the npm package through this repository's Codex marketplace:

```sh
codex plugin marketplace add jyn514/dotfiles
codex plugin add judgement-yields-navigation@jyn-plugins
```

In `plugin@marketplace`, the suffix names the Codex marketplace; it is not an npm scope.

### Other Agent Skills clients

Copy or symlink the desired skill directories into the client's user or project skill directory. For clients that use the shared convention, install them under `~/.agents/skills/` or `.agents/skills/`.

This repository's `./setup dotfiles` command links the complete `skills/` directory to `~/.agents/skills/`.

`references/` contains shared on-demand guidance, not registered skills.
[Change with evidence](references/change-with-evidence.md) supplies code, configuration,
and test standards when the shared agent instructions request it. Plain reference
files add no startup skill descriptions. The sandbox's existing live skills mount
makes reference changes readable without restarting its worker.

## Publish a release

The Codex marketplace pins the npm version in `.agents/plugins/marketplace.json`. Publish that version before pushing the marketplace change. `dev/publish-skills` stages this file as the package-root `README.md` without changing the repository root README.

1. Set the same new semantic version in `package.json`, `.codex-plugin/plugin.json`, and `.agents/plugins/marketplace.json` (`source.version`).
2. Validate the metadata and npm archive:

   ```sh
   tests/setup/agent_skills_package_test.py
   dev/publish-skills --dry-run
   ```

3. Review and commit the release, then authenticate and publish:

   ```sh
   npm login
   npm whoami
   dev/publish-skills --access public
   ```

4. Verify the published version, then push the release commit:

   ```sh
   npm view judgement-yields-navigation version
   ```

5. Test a clean installation and start a new Codex thread so it loads the skills:

   ```sh
   codex plugin marketplace add jyn514/dotfiles
   codex plugin add judgement-yields-navigation@jyn-plugins
   ```

## Agent orchestration

When the problem's framing or approach is uncertain, use
[creative-inquiry](creative-inquiry/SKILL.md) to question assumptions and discover
possibilities. For comparing concrete software-design candidates, use
[design-deliberation](design-deliberation/SKILL.md); inquiry does not automatically
start its workflow.

`creative-inquiry` is imported from
[`nia-e/rustc-project-skills`](https://github.com/nia-e/rustc-project-skills/tree/0fe6e4d11a99b8c62776048d13f59a4e5e4ff6ca/creative-inquiry),
with a locally adapted trigger and a boundary with `design-deliberation`.

`design-deliberation` selects the smallest useful workflow while preserving candidate isolation and
explicit abstention. Its planning, critique, fusion, and review helpers are plain
reference files, not registered skills: they add no descriptions to the startup
catalog. Agents read the linked procedure when entering its phase or pass its
text or resolved absolute path, plus the phase's inputs, to a subagent. They are
not separate slash commands or named skills for subagent preloading. Copy the entire
`design-deliberation/` directory when installing it individually.

### Focused new-tool workflow

For a new independently invoked tool, CLI, service, or reusable executable subsystem, use `new-tool-development`. Product briefs are human-authored; agents may review them and add permitted TODO comments. Use `requirements-definition` for requirements, `technical-docs` for implementation-spec writing, and `spec-review` for maturity, upstream/downstream consistency, and stale invalidation review.

## Suggested workflow

For an uncertain design question:

1. `pain-axis` — inspect repository/history evidence about where the current design has hurt.
2. `design-space-scout` — produce three viable, materially distinct briefs.
3. [independent-plan](design-deliberation/references/independent-plan.md) — elaborate each brief independently, ideally in isolated subagents.
4. [cross-critic](design-deliberation/references/cross-critic.md) — compare the fixed candidates and identify assumptions, omissions, and incompatibilities.
5. [fusion-candidate](design-deliberation/references/fusion-candidate.md) — only if the critic finds cleanly composable parts, construct one explicit synthesis candidate.
6. [council-review](design-deliberation/references/council-review.md) — evaluate the fixed candidate set; choose, declare equivalence, or abstain.

After choosing a design and before implementation:

7. `boundary-declaration` — state ownership/effect boundaries and invariants explicitly.
8. `second-user` — justify proposed complexity when its current requirement, independent consumers, or hard constraints are unclear.
9. `ratchet` — choose or strengthen mechanical checks for verified invariants or demonstrated failures when the enforcement mechanism, test oracle, or baseline needs a decision; skip straightforward regression tests using an established harness.

## Focused workflows

Use these independently when their target is already selected:

- `architecture-design` — assess or design one bounded subsystem when there is no material design fork.
- [autonomous-implementation](autonomous-implementation/SKILL.md) — control explicitly requested autonomous or unattended runs, including milestone order and resumable state; links to [design-for-change](design-for-change/SKILL.md) for implementation/testing and [double-check](double-check/SKILL.md) for evidence standards and completion audits.
- `cleanup-triage` — prioritize and slice cleanup after cleanup has been selected as the opportunity.
- `design-for-change` — resolve modeling, invariant, interface, ownership, or regression-test decisions; skip routine edits with an established shape.
- `double-check` — audit substantial completed work across components, specifications, migrations, or consequential boundaries; use a diff review and native check for localized edits.
- `jj-conflict-resolution` — semantically compose Jujutsu conflict snapshots and diffs without ours/theirs or union heuristics.
- `reorganize-docs` — change documentation information architecture, navigation, splits, consolidation, or archives.

`opportunity-scan` may hand a selected cleanup or architectural opportunity to the corresponding focused skill. Use [Documentation placement](technical-docs/references/placement.md) for new-content destinations and routine additions to established sections, without loading an authoring skill. `technical-docs` owns new standalone documentation, substantive changes to reader structure or explanation, and explicit usability/correctness reviews; `reorganize-docs` owns restructuring existing documentation and navigation.

## Minimal use

You do not need the whole chain every time.

- Small refactor: implement directly when ownership and invariants are clear; use `design-for-change` for unresolved design or test decisions, and `second-user` only when added machinery needs justification.
- Simple configuration edit: inspect the diff and validate with the native parser; no design or completion-audit skill is required.
- Architecture decision: use [design-deliberation](design-deliberation/SKILL.md) to run scouting, independent planning, critique, and fixed-set review.
- Legacy subsystem: start with `pain-axis` before scouting.
- Explicitly requested autonomous run: start with [autonomous-implementation](autonomous-implementation/SKILL.md) and follow its conditional companion-skill routes. Use `ratchet` only when protecting an established invariant or preventing a demonstrated failure requires choosing or strengthening a mechanical check.

## Important rule

Treat model judgments as evidence, not verification. Prefer repository facts, tests, type checks, benchmarks, and historical evidence whenever they exist. `council-review` may return `ABSTAIN`; that is a valid result.
