# Sandbox instructions

## Differences between guest and host

- Treat this process as a disposable container, not the host, but remember that mounted writes persist. Before changing configuration or diagnosing missing state, distinguish guest state, host mounts, and external services.
- The active workspace and launcher dotfiles checkout are the two writable checkouts under `/src`; ordinary files in both are writable. The launcher-selected dotfiles checkout is normally `/src/dotfiles`; relocated checkouts or name collisions can use another path.
  Other `/src` repositories are inspection-only; use `/cd` before editing them. This does not apply to the launcher dotfiles checkout.
  Writable access does not authorize unrelated edits or taking ownership of another contributor's changes.
- A command, credential, file, or daemon missing here may exist on the host. When that distinction matters, inspect the launcher, mounts, environment, or proxy boundary.
- Choose the fix for the affected environment, not for the environment you can modify.
  If a host problem needs a one-off command and you cannot execute it, give the user that command.
  Missing host access changes who performs the action;
  it does not justify replacing that action with configuration, startup automation, or a new tool.
  Before adding persistent behavior, establish why the operation needs to recur.
- `/home/codex/.agents/skills` is writable and host-backed, you may edit it.
- Other shared instructions under `/home/codex/.agents` are staged read-only; edit their tracked source instead.
- Most `/home/codex/.pi/agent` state is private and disposable. Host sessions are mounted read-only at `/home/codex/.pi/agent/sessions` for searching past conversations. Staged configuration is read-only; edit its tracked source and start a new sandbox session to refresh startup-loaded state.
- If a current guest-facing operational path under `/home/jyn` is advertised as usable but is unusable here, establish the proper path and report the sandbox bug at the end of your turn. Historical transcripts and provenance may preserve original host paths without being sandbox failures.

## Permissions

- Repository metadata and sandbox policy—including `.git`, `.jj`, their external backing paths, and `.agents/sandbox`—are protected in both writable checkouts.
  Use ordinary wrapped commands such as `jj`; proxy failure is fail-closed and does not authorize bypassing the mount or invoking another binary.
  For a scoped cross-repository commit, use the selected dotfiles path and a root-relative fileset, for example:
  `jj -R /src/dotfiles commit 'root:skills/example' -m 'Improve example guidance'`.
- The active project's accepted policy owns services and credentials; writable dotfiles does not enable its optional services.
- Host and private-network services are blocked except through designated relays or proxies. Proxy capabilities are fixed at session startup; direct failure does not authorize another route.
- Public network access is allowed, but must be READ-ONLY unless explicitly authorized by a human.
  Be considerate of others and do not hammer expensive network endpoints.
- Root, `sudo`, and the exposed `docker` or `podman` command do not grant access to the outer container daemon or sibling proxy containers.

## Behavior

- jyn is in Central Europe (UTC+2 during daylight-savings-time).
- Use guest-only `work/` for caches, build trees, extracted data, and other high-cardinality intermediates.
  The launcher preserves it across sandbox sessions for the same workspace, but it remains disposable with the VM or manual volume removal.
  Cargo uses the active workspace's `work/cargo-target` automatically.
  Python bytecode, mypy, and Ruff use the active workspace's `work/cache` automatically.
- Use host-backed `target/` only for artifacts that host tools, other agents, or jyn must inspect.
- Use host-backed `notes/` for compact unresolved findings that can change a future decision.
  Do not use it for routine logs, session summaries, or information already owned by maintained documentation.
- Never leave the only evidence for a reported result in `work/`.
  Copy the necessary artifact to `target/` or preserve the decisive facts in `notes/`.
- When a tool needed for authorized work or validation is missing, install it in the disposable sandbox and retry the blocked command.
  A guest-only tool installation is not a new host prerequisite and does not require separate approval.
  You may use `sudo` for guest-only tool installation.
  Keep installation out of host-backed mounts.
  Do not install local substitutes for required host proxies or credentials.
  If installation fails, report the attempted installation and actual failure—not merely that the tool is missing.
  Missing tools likely indicate a deficiency in `.agents/sandbox`; report the missing tool at the end of your turn.
