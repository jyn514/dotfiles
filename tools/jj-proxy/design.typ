#set document(title: "Jujutsu metadata proxy")
#set page(margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true)

= Jujutsu metadata proxy

*Status:* The shared-dotfiles workspace authority, protocol version 2, and cross-proxy mutation-lock contract below are implemented.

== Objective

Allow an LLM-controlled Codex container to edit a repository and create or
reorganize Jujutsu commits without giving arbitrary processes direct write
access to host-backed `.jj` or `.git`. Independent guest repositories retain
native Jujutsu operation with the existing container permissions.

The protection is against accidental or adversarial filesystem operations such
as `rm -rf .git .jj`. It is not intended to prevent the agent from making bad
logical commits through operations that the proxy deliberately exposes.

== Threat model

Treat every process in the Codex container as untrusted, including root. The
agent may bypass `PATH`, invoke binaries by absolute path, compile programs,
change environment variables, or send arbitrary requests to any socket mounted
into the container.

The agent must not be able to:

- write, rename, replace, or remove protected host repository metadata directly;
- choose the executable run by the proxy;
- escape through a shell, alias, editor, pager, diff tool, signing program, or
  untrusted Jujutsu configuration;
- redirect the proxy outside its trusted workspace authority; or
- control the container daemon that establishes the protective mounts.

The agent may:

- read repository metadata;
- modify any ordinary working-tree file permitted by the repository mount;
- invoke supported Jujutsu operations with operands accepted by the command
  policy; and
- make logically destructive but recoverable history edits, such as `abandon`
  or `rebase`, when those commands are included in policy.

== Architecture

`codex-sandbox` uses one JJ proxy per active shared session under the outer container daemon.
That existing service knows the active workspace and launcher dotfiles; it adds no dotfiles-only service:

```text
outer Docker or Podman daemon
|
+-- jj-proxy
|   +-- active and launcher-dotfiles workspaces and metadata read-write and no-exec
|   +-- persistent request locks per JJ backing repository
|   +-- trusted jj binary and configuration
|   `-- Unix socket created in a private volume
|
`-- Codex
    +-- active and launcher-dotfiles ordinary files read-write
    +-- .git, .jj, and external backing metadata overlaid read-only
    +-- .agents/sandbox overlaid read-only in both workspaces
    +-- proxy socket volume mounted read-only
    `-- jj wrapper routes host metadata to proxy, independent guest repos to native
```

The proxy is outside the LLM-controlled container but need not run directly on
the host operating system. A sibling container is portable across native Linux
and Docker or Podman virtual machines and gives the proxy a separate mount and
process namespace.

The inner `docker` command exposed to Codex must continue to target only the
isolated agent Podman service. Codex must never receive the outer daemon socket,
because control of that daemon would allow it to replace the read-only mounts.

The Codex container receives no write-capable credentials for protected Git
remotes. Rejecting push in the metadata proxy cannot stop a standalone Git
client from reading the protected metadata and speaking the push protocol
directly. Any GitHub token or other repository credential mounted into Codex
must therefore be read-only. If a stronger prohibition against pushing to
arbitrary third-party remotes is required, enforce it at the egress gateway by
allowing fetch protocols and rejecting Git receive-pack, SSH Git, and provider
API mutations; a command wrapper is not enforcement against container root.

== Mount layout

The Codex container receives both authorized workspaces, followed by nested read-only mounts for metadata and sandbox policy.
This example applies to each workspace with colocated directory metadata:

```text
--mount type=bind,src=$repo,dst=$container_repo
--mount type=bind,src=$repo/.git,dst=$container_repo/.git,readonly
--mount type=bind,src=$repo/.jj,dst=$container_repo/.jj,readonly
--mount type=bind,src=$repo/.agents/sandbox,dst=$container_repo/.agents/sandbox,readonly
--mount type=volume,src=$socket_volume,dst=/run/jj-proxy,readonly
```

The proxy receives both workspaces and their metadata read-write and no-exec at the same absolute guest paths, plus the socket volume read-write.
The launcher derives dotfiles from its own `DOTFILES`, not cwd, guest input, or sibling policy.
The active guest path remains unchanged; dotfiles normally maps to `/src/dotfiles`, with an unused `/src` fallback for relocated checkouts or collisions.
When dotfiles is active, retain its active path and deduplicate mounts and authority.
The active project's accepted policy alone owns optional services and credentials.
Before runtime startup, the host initializes valid Git-only dotfiles with `jj git init --colocate` only when JJ metadata is absent.
It rechecks absence under launcher coordination and never replaces malformed existing metadata.
The #link("../codex-sandbox/spec/launcher-interface.typ")[launcher contract] owns initialization order and path allocation.
Keeping the path identical makes working-copy paths and diagnostics agree between containers.
The no-exec mount prevents direct execution from the working tree, but does not make arbitrary tool selection safe. A
trusted interpreter or dynamic loader can still read attacker-controlled code
from a no-exec mount.

The launcher must resolve and validate the repository root before starting
either container. It must reject missing, symlinked, or unexpectedly shaped
metadata rather than silently starting without protection. Validation covers
the complete metadata indirection chain, including Git worktree `gitdir` and
`commondir` references and Jujutsu store or backend references. Every resolved
metadata target must belong to the selected repository or to an explicitly
validated external metadata mount.

A Git worktree may use a `.git` file instead of a directory; the implementation
must support a read-only file mount and also protect every referenced Git
directory that lies within an agent-writable mount. Nested read-only mounts are
path-based and do not protect a metadata inode through a hard link elsewhere in
the writable tree. Before startup, the launcher must reject metadata files with
hard-link aliases reachable through any agent-writable mount. An implementation
that cannot establish this invariant must instead put the writable working tree
on a distinct filesystem or copy-up layer from the protected metadata.

Protection covers the active workspace and launcher dotfiles, including external metadata and policy through every exposed alias.
Other source siblings remain inspection-only.
Nested repositories are out of scope unless the launcher discovers and overlays every nested metadata path before Codex starts.
Writable files remain shared host state; access does not authorize unrelated edits or ownership of another contributor's changes.

The launcher supplies `JJ_PROXY_REPO` as the active guest root.
Trusted `JJ_PROXY_WORKSPACES` is a JSON array of entries with exactly `root`, `git_dir`, `common_dir`, `jj_repo`, and `lock`.
Each entry binds an exact guest workspace root, its resolved metadata paths, and a persistent request-lock path.
Validate all entries and prepare secure configuration for both workspaces before readiness.
Accepted-session authority binds the exact set, metadata layouts, lock mounts, and live trusted environment.
Guest request fields cannot add entries; a shared JJ store does not authorize an unlisted linked workspace.

Container root must not receive `CAP_SYS_ADMIN`. Passwordless `sudo` inside a
VM-backed Codex container therefore does not permit remounting metadata
read-write.

== Socket protocol

Use a Unix-domain stream socket at `/run/jj-proxy/socket`. Mounting its volume
read-only in the Codex container permits connection to the existing socket but
prevents replacing it.

Requests are length-delimited JSON objects, not shell command strings:

```json
{
  "version": 2,
  "mode": "mutate",
  "cwd": "/src/project/subdirectory",
  "argv": ["commit", "-m", "Fix parser recovery", "src/parser.clj"]
}
```

Responses contain the exit status and captured streams:

```json
{
  "version": 2,
  "exit": 0,
  "stdout": "...",
  "stderr": "..."
}
```

Set explicit request and response size limits. Reject malformed UTF-8, unknown
fields, embedded NUL bytes, excessive argument counts, and oversized messages.
Protocol version 2 requires a physical absolute `cwd` beneath `/src` in both mutation and inspection modes.
Resolve it through checked filesystem traversal from an already-open `/src` descriptor without magic links or escape.
Retain the resulting descriptor and enter it with `fchdir`.
String canonicalization followed by unchecked `chdir` is insufficient because working-tree paths can change between those operations.
Resolve a single `-R` or `--repository` selector relative to this checked invocation cwd and pass the resolved repository to JJ.
The requested command retains its invocation cwd and native fileset interpretation; repository selection does not change cwd.
Only author prehooks and applicable author reset target the resolved repository explicitly.
Private agent-split targets the workspace resolved from its invocation cwd.

For a scoped commit from another project, use the selected dotfiles path and a root-relative fileset:

```sh
jj -R /src/dotfiles commit 'root:skills/example' -m 'Improve example guidance'
```

`root:` selects paths relative to the target repository; other filesets retain invocation-cwd semantics and native errors.
A cross-repository commit must not snapshot or reattribute the invoking workspace.

The proxy serializes mutation requests per backing repository as specified below.
It runs every request in a fresh process group or cgroup and incrementally enforces output limits.
On timeout, client disconnect, or output-limit failure, it kills and reaps the entire group.
Apply explicit PID, memory, CPU,
file-size, and file-descriptor limits so malformed or expensive requests cannot
exhaust the outer daemon or leave descendants running.

The socket is an authorization boundary only by possession: the LLM is expected
to send arbitrary requests. Security comes from request validation, not from a
secret token or from trusting the wrapper.

== Repository access modes

The proxy distinguishes mutation access from read-only inspection access.
A mutation request resolves to an exact root in trusted `JJ_PROXY_WORKSPACES`.
It receives read-write Landlock access to the authorized worktrees, JJ stores, resolved Git metadata, and required request locks.
Only mutation mode may snapshot a working copy or change repository state.

The launcher admits repositories by mounting the host source tree read-only at
`/src` in both containers. An inspection request identifies a directory beneath
that mount. The proxy opens its `cwd` components without following symlinks, requires
an ancestor with a `.jj` directory, and runs Jujutsu in a child process with a
second, read-only Landlock policy and `--ignore-working-copy`. Linked workspaces
whose metadata is outside the mounted tree are not admitted by this mechanism.
The trusted proxy may also resolve a single `-R` or `--repository` selector
against the invocation directory. It canonicalizes the target, requires a
workspace under `/src`, and derives mutation permission from exact trusted root membership rather than a path prefix or store identity.
A client may request stricter inspection, including for an authorized root, but cannot grant additional mutation access.
Inspection requests are restricted to commands whose reviewed grammar has no
repository mutation path, initially `status`, `diff`, `log`, `show`,
`interdiff`, observational `file` subcommands, `workspace list`, `git root`,
and `help`. They cannot fetch,
write working-tree files or alter configuration. A selector never enlarges
their write authority.

Read-only classification is an enforced command-policy property, not a label
in the client. The proxy must reject commands that can snapshot, update stores,
write configuration, invoke helpers, or access credentials even when their
usual invocation appears observational. The `/src` mount defines inspection
admission; only exact trusted workspace roots permit mutation.

== Mutation ownership across proxies

Launchers create persistent request-lock files keyed by the canonical host JJ backing repository.
Mount the same file into every trusted JJ service targeting that store, including proxies from distinct active-project sessions and linked workspaces.
Never unlink or replace it during cleanup or restart; the agent receives no lock mount.
Include lock identity and mounts in accepted authority, live-resource validation, VM bind preflight, and Landlock access.
This runtime advisory lock is separate from host-kernel launcher session coordination.
It coordinates trusted proxies, not arbitrary host commands or concurrent ordinary file edits.

Acquire the target repository's lock before any mutation-mode action, including author prehooks.
Hold it through the command and applicable author reset, including requests with no author hook.
Secure-config preparation at startup uses the same lock.
The launcher supplies the positive-integer `JJ_PROXY_STARTUP_TIMEOUT_SECS` budget; one startup deadline covers all workspace preparations.
The manager's JJ readiness budget exceeds that deadline so ordinary shared-store contention is not mistaken for unhealthy startup.
A process-local mutex or active project's session lock is insufficient: another proxy's `new`, `edit`, or commit must not interleave a prehook and command.
Independent backing repositories remain concurrent.
Hold at most one repository lock at a time, never for a session lifetime or while waiting for another repository lock.
Read-only inspection needs no mutation lock; linked workspaces retain shared-history semantics, not history isolation.

Use one bounded request deadline for lock wait and the protected sequence, within the client's response timeout.
A lock-wait timeout or cancellation runs no prehook or command.
On command failure or timeout, stop and reap its process group before releasing ownership; retain conditional author-reset behavior.
Closing the owning descriptor releases the lock on normal exit or process death.
A timeout or disconnect can leave a mutation applied without its response; never replay automatically.
Inspect the target repository before deciding whether to retry.

== Wrapper

The wrapper uses one read-only router shared with agent-split. The router
resolves repository selectors, symlinks, JJ workspace/store pointers, Git
indirections, and effective mounts. Targets backed by the existing host source
views or protected metadata use the proxy; independent guest repositories use
native JJ, including private tmpfs and guest-created volumes. Unknown mount
provenance alone does not deny native invocation. Kernel mounts and server
policy, not routing, enforce authorization.

Bootstrap commands route by destination and any shared backing, not the
invoking repository. Array aliases are read as inert data from the same native
global configuration installed from `config/jj.toml`; execution retains the
original argv and cwd. A read-only clone source does not make the destination
host-backed. A guest workspace sharing a protected store routes to the proxy,
but its guest-only cwd remains outside the server namespace and is rejected
without changing cwd or enlarging admission.

The shared router returns checked JSON containing backend, physical workspace,
bootstrap destination, expanded command prefix, and whether native author hooks
may run. It never probes JJ or Git, executes configuration, or writes metadata.
Native attribution hooks target only the selected workspace or newly created
destination and skip help/version, historical-operation, and
`--ignore-working-copy` modes. Identity and plain noninteractive diff handling
remain wrapper responsibilities; proxy serialization and policy are unchanged.

The private `jj --agent-split PATCH MESSAGE REVISION` operation is recognized
before ordinary argument parsing. Its three operands are opaque. The wrapper
requires exactly four arguments, queries the workspace route, and resolves the
ordinary runtime identity before forwarding a proxy request. A native route
rejects this operation before hooks or socket access. Agent-split uses ordinary
native split/editor execution for local workspaces and retains operation capture
and recovery even while a proxy is mounted; proxy failures never trigger native
recovery.

=== Runtime agent identity

Agent identity is dynamic session state, not repository configuration. Pi's
active model may change while the container is running, so `settings.json` and the
container's initial environment are not authoritative sources for commit
attribution.

At dispatch, each guest operation snapshots its invoking Pi context's model;
separate panes and ordinary subagents share a worker, so last-writer state cannot
identify a call. The host extension sends required metadata outside tool
parameters: `model` is `null` or an object with exactly nonempty, control-free
`provider` and `modelId` strings. The worker rejects missing or malformed
metadata and arbitrary environment fields before execution, deriving only
`PI_CALL_MODEL` for that individual shell via documented Pi APIs, without
process-wide environment or file changes.

The flow is:

```text
Invoking Pi context's model at dispatch
  -> guest request carries {provider, modelId}, or null
  -> worker sets this shell's PI_CALL_MODEL
  -> jj wrapper resolves the invocation's identity
  -> proxy request carries that identity
  -> trusted jj commit records it as author and committer
```

Presence of `PI_CALL_MODEL` is authoritative, including an empty value for an
unknown model. Empty or control-bearing values produce the existing warning and
`Pi unknown-model`; they never fall back to a shared file. With that variable
absent, standalone host Pi retains its session-matched `PI_MODEL_FILE` behavior:
the integration publishes an atomically replaced model record, and a missing,
malformed, or mismatched record produces the same unknown identity. The stale
`PI_MODEL` variable remains ignored. These values describe attribution, not
authorization. Non-Pi agents retain their existing identity sources.

The proxy must not infer a model from `settings.json`, a default, repository
configuration, or an earlier request. Model changes in B cannot alter A's
already dispatched call. Restart existing sandbox panes to deploy the updated
host extension and guest worker together; `/reload` replaces only the extension.

Commands targeting host-backed metadata go through the proxy. Mutation-mode
commands may snapshot the working copy and write metadata. Inspection-mode commands must add
`--ignore-working-copy` and use read-only metadata mounts; the real binary
cannot otherwise be trusted to preserve the read-only boundary.

If a proxy route's socket is unavailable, the client fails closed with a concise
error. It must not retry using native JJ. Local routes do not access the socket.

== Command policy

The request carries an argument array that is passed directly to `execve`; the
proxy never invokes `sh -c` or reparses shell quoting.

Use a pinned Jujutsu binary and a trusted, immutable configuration. The proxy
image is minimal, read-only, non-root, capability-free, and has
`no-new-privileges`. Prefer statically linked proxy and Jujutsu binaries so the
image can omit shells, interpreters, dynamic loaders, Git command-line tools,
and general-purpose utilities. Any runtime component required by the chosen
build is immutable and explicitly reviewed. Disable proxy networking except for
explicitly enabled Git fetches.

Start the child from an empty environment with fixed values equivalent to:

```text
PATH=/trusted/bin
JJ_CONFIG=/trusted/jj.toml
HOME=/nonexistent
XDG_CONFIG_HOME=/nonexistent
PAGER=cat
GIT_PAGER=cat
EDITOR=false
VISUAL=false
GIT_CONFIG_NOSYSTEM=1
GIT_CONFIG_GLOBAL=/dev/null
GIT_TERMINAL_PROMPT=0
```

Prefer Jujutsu's built-in noninteractive and no-pager behavior instead of
launching `cat` or `false`. If compatibility requires those programs, include
only reviewed immutable implementations in `/trusted/bin`; their presence does
not make them valid tool choices in requests.

Do not inherit credential, SSH-agent, dynamic-loader, locale-path, or runtime
configuration variables. Repository Git configuration is data from the
protected repository, not trusted executable policy: validate or override
settings that select helpers, hooks, SSH commands, signing programs, filters,
remote helpers, or other subprocesses. The proxy receives no credentials by
default.

Accept most ordinary Jujutsu subcommands, but reject privilege-crossing
surfaces:

- `util`, especially `util exec`;
- `debug`;
- configuration mutation and all command-line configuration overrides;
- alternate workspace or config paths; a repository selector is accepted only
  when it resolves to an exact authorized mutable workspace or an inspection workspace
  beneath the read-only `/src` mount;
- arbitrary diff, merge, editor, pager, signing, or conflict-resolution tools;
- `git init`, `git push`, and commands that redirect storage; and
- irreversible recovery deletion such as operation abandonment or garbage
  collection.

Maintain an allowlist of top-level commands rather than a denylist. Initially
include common working-copy and history operations: `status`, `diff`, `log`,
`show`, `interdiff`, `commit`, `describe`, `new`, `split`, `squash`, `rebase`,
`restore`, `abandon`, `duplicate`, `edit`, `next`, `prev`, `undo`, constrained
bookmark commands, workspace commands, and constrained Git fetch commands. The proxy does not expose
Git push; publishing to protected remotes remains a host-side operation outside
the agent container.

The image packages the trusted, checked-in `policy.toml` at `/trusted/policy.toml`.
The server loads and validates it once before opening the readiness socket,
then passes the parsed policy to request validation. `Policy::load` accepts a
trusted caller-selected path; request data and environment variables cannot
override the production path. Tests load the checked-in file through
`CARGO_MANIFEST_DIR`, without a host `/trusted` directory. `inspect` grants
inspection permissions; mutation mode inherits them and adds `mutate` rules.
A command value of `true` or an empty table permits its prefix; an optional,
nonempty `subcmds` list in a table limits it to those prefixes. A value of `false`
is rejected; omit a command to deny it.
Keys are nonempty command prefixes split on whitespace into whole argv tokens.
Each `subcmds` entry must be one nonempty token and appends to the key's prefix.
For example, `"git remote" = { subcmds = ["list"] }` permits only the `git remote list` prefix.
`updates_author` defaults to false and applies to every path in its rule.
A mutation rule takes precedence over an inherited inspection rule.
Within each section, the longest matching prefix selects the rule's metadata.
The evaluator in `src/policy.rs` returns the unchanged arguments,
read-only classification, and author-update hook; execution consumes this
decision rather than repeating command-name checks. Policy edits require
rebuilding the image, but do not require recompiling the proxy binary.

The current compatibility-preserving policy rejects known privilege-crossing
options and recognizes approved command paths, while leaving ordinary option
and operand validation to the pinned Jujutsu binary. This is deliberately less
strict than a complete per-command grammar. Tightening individual grammars is a
separate policy.toml change requiring compatibility review and new rejection
tests.

Disable command aliases so validation applies to the command Jujutsu actually
executes. Alias spellings such as `jj push`, `jj p`, `jj g push`, and `jj
publish` are therefore rejected rather than expanded; only the exact
constrained `jj git fetch` path is accepted.

Reject arbitrary `--tool`, `--editor`, interactive diff or merge, signing, and
similar executable-selecting options even though the repository is mounted
no-exec in the proxy. Where needed, allow only named, hard-coded Jujutsu
built-ins such as `:git`; configuration cannot redefine an allowed built-in.
Reject alternate workspace, operation-store, or configuration paths in every syntactic position.
Only the checked repository selector described above is permitted.

Git fetch accepts any pre-existing configured remote.
Jujutsu resolves remote selections and uses its normal defaults when none are supplied.
The proxy does not maintain a remote-name allowlist or validate remote URLs or transports.
Requests cannot add remotes, change remote URLs, or override configuration to select helpers, hooks, or SSH commands.
Git push is never accepted.
Network access and credentials, if later required for fetch, are separate explicit capabilities rather than consequences of allowing a Git subcommand.

Pinning the Jujutsu version makes the accepted grammar stable; upgrading
Jujutsu requires reviewing new commands and options before changing the pin.
The policy maintains separate mutation and inspection rule permissions;
adding a command to the inspection permission requires proving that it remains
read-only under `--ignore-working-copy` and the read-only filesystem policy.

== Lifecycle

`codex-sandbox` performs these steps:

+ Derive and validate the active and launcher-dotfiles workspace descriptions, initializing absent dotfiles JJ metadata on the host.
+ Create persistent backing-repository request locks and a session-specific socket volume and proxy container name.
+ Start the proxy with both authorized workspaces and metadata read-write and no-exec, plus the trusted lock mounts.
+ Wait for an explicit readiness response from the socket.
+ Start Codex with ordinary files in both workspaces writable and metadata and sandbox policy overlaid read-only.
+ On exit or signal, stop and remove the proxy and remove the socket volume.

Cleanup must preserve the Codex exit status and tolerate partially completed
startup. Names include the host UID and launcher PID to avoid collisions between
sessions.
Persistent request-lock files survive cleanup and restart.
Deploy launcher, both clients, router, and rebuilt guest/proxy images together in fresh sandboxes.
Editing tracked configuration does not reload staged guest configuration or the proxy's startup authority; `/reload` is insufficient.
Existing accepted sessions without workspace authority reject new joins without disturbing running attachments.

== Implementation stages

+ Build the proxy and client with protocol framing, descriptor-relative
  checked absolute-cwd execution, exact workspace authority, environment scrubbing, per-command grammar
  validation, serialization, process-group cleanup, and resource limits.
+ Add unit tests for every rejected escape surface and malformed request.
+ Add an integration fixture containing colocated `.jj` and `.git` metadata.
+ Add launcher support for the proxy container, socket volume, readiness, nested
  read-only mounts, and cleanup.
+ Exercise the Pi per-call identity channel through `jj status` and `jj commit`,
  including overlapping panes and ordinary subagents with different models.
  Verify that later selection changes cannot overwrite dispatched attribution.
+ Preserve wrapper identity through proxy requests and prohibit native retry
  after proxy failure. Route independent guest repositories natively.
+ Exercise normal status, diff, commit, split, rebase, undo, and Git fetch flows.
+ Attempt direct metadata writes as the ordinary user and through `sudo`; both
  must fail while proxy commits succeed.
+ Attempt execution from the no-exec working tree, interpreter and external-tool
  escapes, hard-link aliases, `cwd` replacement races, Git helper injection,
  and orphaned subprocesses.
+ Inject termination during metadata-writing operations and verify that the
  repository remains recoverable and subsequent proxy commands succeed.

== Acceptance checks

- `rm -rf .git .jj` from Codex fails without damaging host metadata.
- Direct writes, renames, symlink replacement, and writes through `/proc` or an
  alternate path to the same mounts fail.
- Metadata cannot be changed through a hard-link alias in any writable mount.
- Absolute invocation of the real `jj` inside Codex cannot mutate protected
  host metadata; independent guest repositories remain writable.
- Rootfs, private tmpfs, and guest-volume repositories support native commits
  and agent-split recovery with the proxy mounted.
- Bootstrap aliases use the installed native configuration and route by
  destination even from a protected checkout. Target-scoped attribution leaves
  other workspaces unchanged; no-working-copy modes suppress both hooks.
- Private split operands remain opaque; native routes reject the private
  operation without hooks or socket access, and protected splits preserve the
  active agent identity.
- Binaries and scripts in the proxy's working-tree mount cannot execute, and
  trusted interpreters or tools cannot be selected to interpret working-tree
  content.
- Shell metacharacters in commit messages remain literal data.
- Config overrides, repositories outside the `/src` mount, external tools, and
  `util exec` are rejected.
- Inspection requests can read only repositories under `/src` and cannot
  mutate their working trees, Jujutsu stores, Git metadata, configuration, or
  credentials.
- Git fetch uses host-configured remotes, requests cannot change remote configuration,
  every Git push request is rejected, and the Codex container has no write-capable credentials for protected remotes.
- Supported commands preserve stdout, stderr, and exit status closely enough
  for interactive agent use.
- Pi calls retain their invoking model under overlap. Missing or malformed guest
  call metadata prevents execution; explicit unknown models produce an attribution
  warning rather than a stale-file or configured-default identity. Standalone host
  Pi retains its session-matched model-file validation.
- Distinct proxy services sharing one JJ backing repository serialize all mutation-mode requests through hooks, command, and reset.
  A non-hook mutation cannot enter another request's paused prehook sequence.
  Independent backing repositories remain concurrent; request-lock identity survives restart.
- Lock-wait timeout or cancellation performs no mutation; process termination releases ownership.
  Timed-out, oversized, and interrupted requests leave neither the proxy wedged nor descendant processes running.
- Cross-repository commits with `root:` filesets affect only selected paths and target attribution.
  Other filesets and errors agree with native JJ at the original invocation cwd.
- Both trusted workspace roots permit mutation, while an unlisted sibling or linked workspace remains inspection-only.
  Explicit inspection of an authorized root remains read-only.
- Old accepted sessions cannot acquire new workspace authority from worker mounts or `/reload`.
- Proxy failure is fail-closed, and launcher cleanup removes only resources for
  its own session.
- Existing non-agent working-copy changes remain intact across proxy startup,
  commands, and shutdown.
- Forced termination during a metadata write leaves the repository recoverable.

== Alternatives rejected

A `PATH` wrapper is not enforcement because it can be bypassed. Unix ownership
cannot grant access based on the executable being run. Landlock and bubblewrap
restrictions are inherited by child processes, so an in-container `jj` cannot
regain metadata access. A setuid `jj` or setuid wrapper would place Jujutsu's
large CLI, configuration, and subprocess surface inside the privilege boundary.
The sibling proxy keeps that boundary small, explicit, and testable.
