# Host Pi with guest tool execution: implementation plan

The selected design is specified in [launcher-interface.typ](spec/launcher-interface.typ),
[proxy-design.typ](spec/proxy-design.typ), and
[process-ownership.typ](spec/process-ownership.typ). Host Pi is the launcher
execution path. Its normal-operation checks do not establish conformance to
proxy-design's host extension authority contract; that contract controls the
required security boundary.

## Outcome and boundaries

Pi, its UI, conversations, model requests, subagents, and model-requested session
forks run on the host. The launcher supplies their inherited guest attachment.
Guest tools run there during normal operation; failed extension reload may
restore host-local tools. Routing is not a malicious-code security boundary.
Host handlers and authenticated traffic retain proxy-design's admission and broker
rules, including fail-closed proxy and credential failures.
The launcher contract owns the selected fork behavior and acceptance checks.

Pi owns its conversation store; the guest's host-session mount is read-only.
The launcher starts host Pi only after the worker is ready, and a lost worker
interrupts host Pi.
The transport does not replay calls after a possible write.

## Work and logical commits

1. **Install the Pi extension.** Override Pi's built-in tools with guest-backed
   implementations and route `!` and RPC bash through `user_bash`, as Pi's SSH
   extension example does. Load the extension in parent and child processes;
   `PI_SUBAGENT_PI_BIN` can enforce child launch arguments. Verify ordinary
   `/reload` and child behavior. Fail-closed host tool dispatch is not required;
   failed reload may restore local tools.
2. **Add a guest worker and attachment.** Reuse the existing agent mount and
   service setup in `codex-sandbox`, replacing the guest Pi entrypoint with a
   persistent tool worker. The JSON-line transport carries progress, images,
   completion, and errors. A disconnect aborts the active call; no call is replayed.
3. **Start host Pi with built-in guest tools.** Keep sessions on the host and
   bind reads, writes, and shell operations to the guest backend. Route model
   requests through admitted brokers. Successful reload restores guest routing.
4. **Route subagents and session forks.** Use `PI_SUBAGENT_PI_BIN` and the existing
   child manager with inherited guest routing during normal operation. Admit host
   handlers under proxy-design's authority contract; model-selected templates
   cannot widen it.
5. **Implement lifecycle and directory handoff.** On `/cd`, validate first,
   settle and close the old session and guest, then start a fresh attachment and
   fork the conversation, or start fresh if it has no saved messages. Failed
   validation leaves the old session usable; failed cleanup stops the handoff.
   Cross-directory resume also forks.
6. **Switch the default and document operation.** The README, image, and test entrypoint reflect
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
- **Implemented:** host Pi with a guest tool worker; guest-Pi execution was removed
  after the host-Pi acceptance path became operational.
- **Observed extension seam:** pinned Pi revision
  `929ffac0ce312fa5ccca1ee87f80c8c053d81fe4` permits extensions to override
  built-in tools and replace `user_bash` operations. Subagents already disable
  extension discovery and accept explicit extension paths, so they can load the
  same guest extension through their existing process manager.
- **Decided:** host-local tool fallback after failed reload is outside the
  guest-routing guarantee. Proxy and credential failures still fail closed.
- **Implementation gap:** direct host provider credentials do not satisfy
  proxy-design's selected broker contract.

Security acceptance remains open for host handler admission, protected host code
sources, guest-view resource reads, and brokered model requests.
Model-requested session forks remain selected, not implemented. Operational
acceptance remains open for worker loss. The direct `/skill:` delegation warning
is a separate unresolved issue.
