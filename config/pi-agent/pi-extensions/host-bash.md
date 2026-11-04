# Host commands with automatic review

Run `/host` or `/host on` to expose `host_bash` alongside the ordinary guest tools.
Run `/host off` to disable it and cancel an active host call.
New managed subagent processes inherit the parent's current selection and writable host workspace, including when a worker is recreated.
Existing processes keep their own selection; changing the parent's selection does not remotely toggle them.
Template tool allowlists still apply, and excluding `host_bash` prevents inherited activation.
Each child command receives its own native policy check and, when required, Guardian review; approval decisions are not inherited.
Child review includes the selected root parent branch as human context and labels child task prompts as parent-agent assignments.
It reads a verified private snapshot through Pi's session parser without changing the live parent file.
An inherited call fails if that saved human context is unavailable; child task text cannot substitute for it.
Reloading, ordinary resumes, and conversation switches disable the host tool again.
`codex-sandbox restart` and `restart-all` preserve the selected host workspace only for the same conversation and working directory.
Ordinary `--resume` and `--fork` launches do not restore that selection.
Restart restores activation before unpausing work; every command still receives its own policy check and any required Guardian review.
Existing Pi processes need `/reload` to load this behavior; run `/host on` again afterward.
The footer shows `host: auto-review` while it is enabled.

`host_bash` takes `command`, optional `cwd`, optional `timeout` in seconds, and optional `sandbox_permissions`.
By default, `sandbox_permissions` is `use_default`: the command runs in Codex's `:workspace` sandbox on the host.
Ordinary sandboxed commands do not invoke Guardian.
Escalation is off by default, and the agent is instructed to attempt the command in the sandbox first.
The failed attempt must provide evidence that broader access would resolve a sandbox restriction before the agent retries with `sandbox_permissions: "require_escalated"`.
The required `justification` describes the failed attempt, the restriction, and why the task needs broader host access.
Ordinary command errors do not justify escalation.
Policy or Guardian denial stops the operation; native exec policy rejects forbidden commands before invoking Guardian.
Paths refer to the host; the default directory is Pi's host working directory.
The writable workspace stays bound to Pi's host working directory; selecting another `cwd` does not grant write access there.
For an alternate directory, the same guarded `cd` command is presented to both policy review and execution while both native permission resolutions remain at Pi's host workspace.
Execution uses `/bin/bash -c` without login-shell initialization.
Ordinary `bash`, `read`, `edit`, and `write` retain their existing guest routing.

The extension needs a native Codex executable with the experimental `thread/guardianReview` API and working Codex authentication.
The tested release is `0.167.0-alpha.2`; `0.166.0` lacks that API and returns an error without executing the command.
It uses `codex` from PATH by default.
To use a separately unpacked binary without installing it, start Pi with `PI_HOST_CODEX_BIN=/absolute/path/to/codex pi`.
The executable selection is fixed until extension reload.
The extension publishes its enabled workspace through `PI_HOST_BASH_WORKSPACE` and its human-context reference through `PI_HOST_BASH_AUTHORITY_CONTEXT`.
The existing subagent launcher snapshots both with the child's environment; descendants retain the same root origin.
Only managed children consume that inherited selection; ordinary root sessions still require `/host`.

Each call starts its own Codex app-server and ephemeral review thread.
Pi supplies the active branch's user and assistant text, tool arguments, and text results; it omits thinking and binary attachments.
Summaries and extension messages remain assistant context rather than becoming new user authorization.
When approval is required, this sends that conversation context to the Codex reviewer, even when Pi uses another model provider.
Codex uses its existing authentication and configuration; review or authentication failures prevent execution.

Hooks are disabled through a configuration override on this temporary thread, including session-start and pre-tool hooks.
The extension checks the thread's hook inventory before review and refuses execution if hooks remain present or discovery fails.
Saved Codex configuration is not changed.
This prevents pre-tool hooks from changing the command under review while Pi later executes the original command.
Managed requirements still apply and can reject the override or require human approval.

Codex checks exec policy for the exact command, host directory, shell, and requested permissions through `thread/guardianReview`.
If policy skips approval, that API returns `null` without invoking Guardian.
Explicit command rules can still require review for a sandboxed command; approving such a rule does not remove its sandbox.
Default execution uses the sandbox profile selected by the review thread.
Only an explicit `require_escalated` request, allowed by Guardian or exec policy, runs through `command/exec` with full host access.
The result identifies whether execution used the sandbox or full host access.
Denial, review cancellation or timeout, malformed responses, and unavailable APIs prevent starting the command; the extension never retries automatically.
Cancelling an executing command or reaching its execution timeout interrupts it but cannot undo effects it already performed.
The app-server supplies process execution and the extension enforces the returned assessment.
Automatic review is not an operating-system sandbox for an escalated command.
Output is buffered with a 64 KiB cap per stream and the default execution timeout is 60 seconds.

## Verification

`dev/test-environment bun test tests/pi/host_bash_test.ts` checks approval decisions, command identity, transcript authority, and session-local activation.
`dev/test-environment node --test tests/pi/native_host_bash.mjs` loads host and guest extensions through the installed Pi loader and checks saved restart state against real session reopening, forks, and tool allowlists.
The source-backed `tools/pi-codex-subagents/test/restart-control-roundtrip.test.ts` checks activation across controller pause, shutdown, reopen, and unpause; run it with the [changed-core test driver](../../../tools/pi-codex-subagents/test/SOURCE-CORE.md).
These checks are discovered by `dev/test`.

For a live smoke test, unpack the desired Codex release under temporary storage, then run:

```sh
PI_HOST_CODEX_BIN=/absolute/path/to/temporary/codex \
DOTFILES_TEST_HOST_AUTH="$HOME/.codex/auth.json" \
dev/test-environment bun test tests/pi/host_bash_test.ts --test-name-pattern 'native alpha'
```

The opt-in smoke test copies authentication into its private HOME, uses a disposable workspace, and removes both afterward.
It checks sandboxed execution without Guardian, blocked writes through an alternate `cwd`, a blocked metadata write, explicit Guardian-approved escalation, hook isolation, unchanged saved configuration, and cancellation after `/host off`.
The smoke test contacts the configured Codex model service; it does not install or upgrade Codex.
