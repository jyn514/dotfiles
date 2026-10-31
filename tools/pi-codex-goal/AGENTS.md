# pi-codex-goal — agent notes

Pi extension: Codex-style `/goal` command and `get_goal` / `create_goal` / `update_goal` tools. State lives in pi session custom entries.

## Dotfiles installation and tests

This tree is the authoritative dotfiles package, installed by setup at `~/.pi/agent/packages/pi-codex-goal`.
The user settings source is `./packages/pi-codex-goal`; preserve both extension and prompt resources.
Do not add a second npm, Git, or project-local install: duplicate packages register conflicting goal tools.
The original standalone checkout is historical, not an installed dependency.

Follow the repository's `dev/README.md` and run tests through `dev/test-environment`.
The native adapter `tests/native/test_native_pi_codex_goal.py` copies this package to disposable storage before running its checks.
Do not run dependency installation, generated-output checks, or package tests against the authoritative tree as a test fixture.

## Verify before finishing

```sh
# From the dotfiles repository root:
dev/pytest -q tests/native/test_native_pi_codex_goal.py
```

The adapter runs `npm run check`: the full Node test suite (`test/*.test.ts`, via Node's native type stripping), `tsc`, and an `npm pack` dry run. Relative imports use `.ts`; there is no build step, and the npm artifact ships `extensions/` and `src/` as TypeScript.

## Pi 1.0 contracts

Registered context and native lifecycle keepers own continuation rewriting and delivery. Keep distinct terminal inputs and domain guards; do not duplicate index-only reducer calls under stop-reason names or simulate host recovery receipts in the test harness.

Pi 1.0.0 remains the support floor. Locked Pi/TypeBox development dependencies are reproducible snapshots, not validation targets. Qualification must select the latest stable official Pi and latest maintained fork main, resolving version/commit once per workflow run and retaining SDK/CLI evidence. Use each selected host's actual companion graph rather than inferring runtime compatibility from a development bump. Preserve native custom-entry recovery, per-loop guarded continuation and final settlement; do not replace `agent_end` with notification-only `agent_settled`. Use native finalized events/tool correlation for exact-once usage and never assume `message_end` or boundary drafts have already appended. No removed fork checkpoint, recordUsage or metadata/revision API is a supported requirement. Run host-sensitive native suites/packed CLI qualification against the latest maintained fork's exact revision on every qualification run.

Historical release channels are owned npm `pi-codex-goal` plus GitHub releases; proposed new version 0.6.0. Parent controls independent review/merge/release; no live activation.

## Layout

| Area | Modules |
|------|---------|
| Wiring | `src/index.ts`, `goal-runtime-controller.ts` |
| User / model API | `commands.ts`, `tools.ts`, `prompts.ts`, `format.ts`, `clipboard.ts`, `prompts/create-goal.md` |
| Runtime events | `goal-runtime-event-handlers.ts`, `goal-runtime-*-handlers.ts` |
| Transitions | `goal-transition.ts`, `goal-transition-effects.ts`, `goal-state-controller.ts` |
| Stale continuations | `stale-queued-work-*.ts` |
| Recovery | `recovery*.ts` |
| Domain | `state.ts`, `types.ts`, `goal-persistence.ts` |
