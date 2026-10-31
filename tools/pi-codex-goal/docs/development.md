# Development and release checks

[Back to the README](../README.md)

## Local setup

Use Node.js 24 (`.nvmrc`) and the npm version in `packageManager`.

From the dotfiles repository root:

```sh
dev/pytest -q tests/native/test_native_pi_codex_goal.py
```

The adapter uses a disposable package copy and its locked development dependencies.
It runs `npm run check` without writing dependencies or package artifacts into this authoritative tree.
The installed-Pi probe also checks the setup-style relative package alias, extension and prompt discovery, and persisted goal reload without live model calls.

`npm run check` type-checks with TypeScript 7 and runs the Node test suite with native type stripping, including source, Git-production, and packed-artifact loading, tool persistence, and SDK compaction/continuation tests. It also runs an `npm pack` dry run. Run it with an empty HOME/agent profile and a short TMPDIR outside your real home ancestry, with no project markers in its ancestors. The selected host must be installed in this checkout's dependency graph; changing only a CLI on PATH does not select its SDK types. No live model is called.

Dotfiles setup installs the local package alias `~/.pi/agent/packages/pi-codex-goal`.
The settings source `./packages/pi-codex-goal` loads both declared resource types without a build or production dependency install.
Keep only that source active: additional npm, Git, or project-local installs register conflicting goal tools.
Use disposable profiles for installation checks; see [AGENTS.md](../AGENTS.md) for the module map.

## Goal-scope behavior checks

`test/fixtures/goal-scope-cases.json` defines manual next-action cases for goal-scope guidance.
The historical cases are reduced reconstructions, not full session replays; the milestone-hold case is a contract-derived control.
These cases are not automatic model tests in `npm run check`.

Distinguish extension-only goal-contract checks from optional `autonomous-work` strategy evaluation.
Core contracts apply without the skill; prerequisite diagnosis and work selection require a separate skill-present evaluation.
For that evaluation, retain the exact skill version, advertised path, and evidence that the model actually read its body, not merely that the source changed.
Include implementation, research, writing, planning, and review goals, plus ordinary bounded-task and inactive-goal controls.
Check that persistence does not grant unrequested edits, execution, or publication.
The existing goal-scope fixtures alone do not qualify those activity boundaries.

Compare baseline and candidate standing guidance, the exposed `update_goal` definition, and the compact continuation together.
Use the same model and case inputs in separate fresh contexts, with disposable action-recording tools rather than a request for a checklist.
Score the recorded tool choices against `expectedActions`, keeping the answer keys out of model inputs.
Include genuine dependency blocks and explicit holds so that continuing unauthorized work is also a failure.
For historical excerpts, use original message timestamps, exclude subsequent user corrections, and record truncation limits.
Retain the exact prompt inputs and tool records outside the authoritative checkout.

On October 14, 2026, four reduced paired cases and two paired transcript windows produced the expected tool choices with both versions.
The historical windows used the last 30 visible messages, capped individual text/tool items at 1,800 characters, and omitted private thinking.
The October 11 direct-conjunction window included a later user correction and is not a valid pre-failure comparison.
These probes do not demonstrate a behavioral improvement or end-to-end task recovery.

### Decision-point replay

`npm run replay:block` calls a live model and incurs provider costs; it is opt-in and is not called by `npm run check`.
It replays the context immediately before an assistant message requesting `update_goal(blocked)`.
It needs the session history, not the historical workspace or ignored artifacts.

```sh
npm run replay:block -- \
  --session /path/to/original-session.jsonl --before BLOCK_ASSISTANT_ENTRY_ID \
  --baseline-src /path/to/baseline/src --candidate-src ./src \
  --output /tmp/goal-block-replay-new \
  --api-key-env REPLAY_API_KEY
```

Source directories must contain trusted `prompts.ts` and `tools.ts` modules with resolvable dependencies.
The harness reads their exported guidance and registered goal declarations without invoking tool execution callbacks.
Use `--base-url-env NAME` for an endpoint override and `--sdk MODULE_OR_ABSOLUTE_PATH` for an explicitly selected Pi SDK.
It otherwise uses the installed SDK, the recorded model and thinking level, and in-memory credential/model stores rather than the live Pi profile.
Run `npm run replay:block -- --help` for query limits and request timeouts.

The cutoff must identify the original assistant block request, not its tool result or persisted blocked state.
Pi selects the native branch and compaction-aware context; the harness excludes that request and every later entry.
It preserves paths, historical messages, ordinary tool definitions, and recorded system instructions.
Both arms replace standing goal guidance and goal declarations from the selected source bundles; unmatched historical instructions remain.
It does not inject a startup continuation or a description of the replay experiment.
Sessions lacking recorded system rules, goal declarations, an active goal, or model selection are rejected rather than filled from current configuration.

Only `get_goal` calls receive results, using frozen goal state reconstructed from the original branch.
All other requests stop the replay before execution, including filesystem tools, workers, human questions, and goal mutations.
A different valid tool request counts as avoiding the block at this decision point; no subsequent progress or continued avoidance is established.
This includes requesting a skill-file read: the replay does not execute that read or expose its result.
It cannot qualify skill loading or subsequent workflow behavior.
Answer-only responses, completion, objective replacement, invalid requests, provider errors, and query exhaustion are inconclusive.
Mixed batches containing a valid block request count as requesting a block even if they also request another action.
Paused annotations and blocked-goal activation requests are ineligible on the active replay seed and remain inconclusive, including mixed batches with ordinary actions.

A comparison is conclusive only when the baseline requests a block.
Exit codes are 0 for decision-point avoidance, 1 when both arms request a block, and 2 for inconclusive results or setup errors.
Output directories must be new and are private; they retain the exact prefix hash, reconstructed inputs, source guidance, frozen goal state, model responses, and comparison.
Raw evidence can contain private historical content; do not commit it.
The selected SDK reconstructs context, but the harness cannot prove equality with original provider wire bytes or unchanged model weights.
Its deterministic tests run through the normal Node test suite, including native SDK restoration/provider handling and CLI reachability, without live model calls.

## Compatibility qualification

Pull-request CI runs `check:compat` against the latest stable official Pi and latest maintained fork `main` on Ubuntu/Node 24. Version/commit identities are resolved once per workflow run and retained with exact SDK/CLI evidence. Both hosts are required. Qualification also checks clean Git and npm consumer installs through the native Pi CLI. Hosted CI does not call a model.

Run the shared native Git/packed consumer qualification locally:

```sh
git clone https://github.com/fitchmultz/.github.git /tmp/pi-goal-automation
node /tmp/pi-goal-automation/scripts/qualify.mjs --repo pi-codex-goal --source "$PWD" \
  --host official --target latest --output /tmp/pi-goal-evidence
```

The compatibility workflow uses this qualification tool for both Pi hosts. Qualification does not publish, install into live settings, restart active sessions, merge, or tag.

## Interactive smoke tests

These checks exercise the interactive `/goal` command, hidden continuation, bridged goal tools, filesystem verification, and final `update_goal` completion.

Release-sensitive changes touching slash-command parsing, TUI submission, goal command behavior, hidden continuation, or post-tool completion require manual interactive `/goal` evidence before release. Record the command, model, session directory, final assistant evidence, and confirmation that the session JSONL contains the `/goal` command path, file verification, and `update_goal` completion.

Pi must be authenticated to a capable model in your local setup. Start Pi from this repository:

```sh
rm -f /tmp/pi-codex-goal-fast.txt /tmp/pi-codex-goal-slash-smoke.txt
rm -rf /tmp/pi-codex-goal-slash-smoke-session
pi --model <model-id> \
  --session-dir /tmp/pi-codex-goal-slash-smoke-session
```

### Fast manual smoke

For a short confidence check, paste:

```text
/goal Create /tmp/pi-codex-goal-fast.txt containing PI_GOAL_FAST_OK; verify with cat; mark complete; report final status.
```

This intentionally uses shell `cat`; use the full smoke for built-in `read` tool coverage. Expected final evidence:

```text
Verified file path: /tmp/pi-codex-goal-fast.txt
Verified content: PI_GOAL_FAST_OK
Final goal status: complete
```

### Full manual smoke

For the fuller end-to-end path, paste:

```text
/goal Create /tmp/pi-codex-goal-slash-smoke.txt containing PI_GOAL_SLASH_OK, verify the file content from the filesystem, inspect the current goal, and mark the goal complete only after verification. Final reply must include the verified file path, verified content, and final goal status.
```

Expected final evidence:

```text
Verified file path: /tmp/pi-codex-goal-slash-smoke.txt
Verified content: PI_GOAL_SLASH_OK
Final goal status: complete
```

Print mode dispatches `/goal` commands and can change saved goal state. It can exit before a queued goal turn finishes; an aborted active goal becomes paused. Run these smoke tests in interactive Pi. For headless automation, prompt the model to call `create_goal`, `get_goal`, and `update_goal`.

### TUI automation and troubleshooting

For tmux-driven interactive smoke automation, send literal text and submit with CSI-u Enter (`ESC [ 13 u`). Normal `tmux send-keys Enter` works in many setups; CSI-u is the robust scripted submit path through Pi's TUI key parser. This example uses shell `cat`; require the built-in `read` tool in the prompt when testing that path:

```sh
tmux send-keys -t "$TMUX_SESSION" -l '/goal Create /tmp/pi-codex-goal-fast.txt containing PI_GOAL_FAST_OK; verify with cat; mark complete; report final status.'
tmux send-keys -t "$TMUX_SESSION" -l $'\033[13u'
```

If a run appears stuck on `Working...` after a built-in `read` result, capture the session JSONL and TUI pane before retrying. A healthy path includes a `toolName: "read"` tool result, an `update_goal` tool result with `status: "complete"`, and a final assistant message. If only the TUI path stalls, treat it as a Pi host/tool-resume reproduction before changing goal continuation logic.

## Automatic npm releases

Follow the [shared release procedure](https://github.com/fitchmultz/.github#automatic-npm-releases): merge a reviewed PR into `main` with an intentional `package.json` version bump and a matching versioned `CHANGELOG.md` section. Once configured and enabled, publication is unattended after compatibility checks and candidate-tarball qualification pass. Complete package-specific evidence before merging a bump, including [interactive smoke tests](#interactive-smoke-tests) for release-sensitive changes. Automation never bumps versions, overwrites releases, or republishes an existing version; existing manual publisher instructions remain valid.

Failed or unpublished candidates retry daily at 12:17 UTC or through manual dispatch of `npm release` on `main`, without another bump. Set `NPM_RELEASE_ENABLED` to anything other than `true` to stop new release plans; cancel pending runs separately when needed. Workflow validation alone does not prove a completed OIDC publication. Documentation-only changes do not need a new version or release.
