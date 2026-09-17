# Host Pi with guest tool execution: implementation plan

The selected design is specified in [launcher-interface.typ](spec/launcher-interface.typ),
[proxy-design.typ](spec/proxy-design.typ), and
[process-ownership.typ](spec/process-ownership.typ). Host Pi is now the launcher
default; `CODEX_SANDBOX_HOST_PI=0` retains guest-Pi mode.

## Outcome and boundaries

Pi, its UI, conversations, model requests, and subagents run on the host using
host credentials. The launcher starts one guest worker for each Pi launch. Pi's
built-in tools and human `!` commands run there during normal operation. Other
host extensions retain their existing host authority; this is not a malicious-code
security boundary.

Pi owns its conversation store; the guest does not mount it. The launcher starts
host Pi only after the worker is ready, and a lost worker interrupts host Pi.
The transport does not replay calls after a possible write.

## Work and logical commits

1. **Install the Pi extension.** Override Pi's built-in tools with guest-backed
   implementations and route `!` and RPC bash through `user_bash`, as Pi's SSH
   extension example does. Load the extension in parent and child processes;
   `PI_SUBAGENT_PI_BIN` can enforce child launch arguments. Verify ordinary
   `/reload` and child behavior. A failed extension reload can restore local
   execution; that failure mode is outside the requested security boundary.
2. **Add a guest worker and attachment.** Reuse the existing agent mount and
   service setup in `codex-sandbox`, replacing the guest Pi entrypoint with a
   persistent tool worker. The JSON-line transport carries progress, images,
   completion, and errors. A disconnect aborts the active call; no call is replayed.
3. **Start host Pi with built-in guest tools.** Keep sessions and model requests
   on the host using its existing credentials. Bind built-in
   reads, writes, and shell operations to the guest backend. A successful
   extension reload restores those bindings; a failed reload may not.
4. **Route subagents.** Use `PI_SUBAGENT_PI_BIN` so child Pi processes receive
   the guest-tool extension and the same worker binding. Other extensions keep
   their existing host behavior.
5. **Implement lifecycle and directory handoff.** On `/cd`, validate first,
   settle and close the old session and guest, then start a fresh attachment and
   fork the conversation, or start fresh if it has no saved messages. Failed
   validation leaves the old session usable; failed cleanup stops the handoff.
   Cross-directory resume also forks.
6. **Switch the default and document operation.** The host path is the default;
   guest-Pi mode remains available. The README, image, and test entrypoint reflect
   the new path. The runtime image builds with a local Pi source context, and a
   real Pi `read` call succeeds in the guest worker. Full launcher RPC `!` calls
   return `/src/dotfiles` and `Linux`, including with child-style
   `--no-extensions`. An interactive `/reload` followed by `!` still returned
   `/src/dotfiles` and `Linux`. An empty-session `/cd` restarted Pi in the
   selected subdirectory. After the stale default extension path was removed,
   the user reported a successful `spawn_agent` retry. A separate live child
   `bash` call returned `Linux` and `/src/dotfiles`; worker-loss behavior has
   not been probed end to end.

## Decision ledger

- **Decided:** host Pi, guest tool worker, one attachment per Pi session and its
  children, guest execution in normal operation, no automatic call replay.
- **Implemented default:** host Pi; `CODEX_SANDBOX_HOST_PI=0` retains guest-Pi
  mode while the remaining acceptance checks are completed.
- **Observed extension seam:** pinned Pi revision
  `929ffac0ce312fa5ccca1ee87f80c8c053d81fe4` permits extensions to override
  built-in tools and replace `user_bash` operations. Subagents already disable
  extension discovery and accept explicit extension paths, so they can load the
  same guest extension through their existing process manager.
- **Decided:** Pi's `!`/RPC bash commands run in the guest during normal operation.
  A failed extension reload can leave the hook absent and restore Pi's local
  fallback; this is outside the requested security boundary.
- **Decided:** host Pi uses its existing provider credentials directly; guest-Pi
  mode retains the sandbox's authenticated broker route.

Operational acceptance remains open for worker loss. The direct `/skill:`
delegation warning is a separate unresolved issue.
