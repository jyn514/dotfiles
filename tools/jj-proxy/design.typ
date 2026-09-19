#set document(title: "Jujutsu metadata proxy")
#set page(margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true)

= Jujutsu metadata proxy

== Objective

Allow an LLM-controlled Codex container to edit a repository and create or
reorganize Jujutsu commits without giving arbitrary processes direct write
access to `.jj` or `.git`.

The protection is against accidental or adversarial filesystem operations such
as `rm -rf .git .jj`. It is not intended to prevent the agent from making bad
logical commits through operations that the proxy deliberately exposes.

== Threat model

Treat every process in the Codex container as untrusted, including root. The
agent may bypass `PATH`, invoke binaries by absolute path, compile programs,
change environment variables, or send arbitrary requests to any socket mounted
into the container.

The agent must not be able to:

- write, rename, replace, or remove repository metadata directly;
- choose the executable run by the proxy;
- escape through a shell, alias, editor, pager, diff tool, signing program, or
  untrusted Jujutsu configuration;
- redirect the proxy to another repository; or
- control the container daemon that establishes the protective mounts.

The agent may:

- read repository metadata;
- modify any ordinary working-tree file permitted by the repository mount;
- invoke supported Jujutsu operations with operands accepted by the command
  policy; and
- make logically destructive but recoverable history edits, such as `abandon`
  or `rebase`, when those commands are included in policy.

== Architecture

`codex-sandbox` starts two sibling containers under the outer container daemon:

```text
outer Docker or Podman daemon
|
+-- jj-proxy
|   +-- repository mounted read-write and no-exec
|   +-- trusted jj binary and configuration
|   `-- Unix socket created in a private volume
|
`-- Codex
    +-- working tree mounted read-write
    +-- .git overlaid by a read-only bind mount
    +-- .jj overlaid by a read-only bind mount
    +-- proxy socket volume mounted read-only
    `-- jj wrapper forwards argv to the proxy
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

The Codex container receives the repository normally, followed by nested
read-only mounts for its metadata:

```text
--mount type=bind,src=$repo,dst=$container_repo
--mount type=bind,src=$repo/.git,dst=$container_repo/.git,readonly
--mount type=bind,src=$repo/.jj,dst=$container_repo/.jj,readonly
--mount type=volume,src=$socket_volume,dst=/run/jj-proxy,readonly
```

The proxy receives the repository read-write and no-exec at the same absolute
path and the socket volume read-write. Keeping the path identical makes
working-copy paths and diagnostics agree between containers. The no-exec mount
is defense in depth: it prevents direct execution of a binary or script created
in the working tree, but it does not make arbitrary tool selection safe. A
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

The first version protects only the selected repository root. Nested
repositories are out of scope unless the launcher discovers and overlays every
nested metadata path before Codex starts.

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
  "version": 1,
  "cwd": "subdirectory/within/repository",
  "argv": ["commit", "-m", "Fix parser recovery", "src/parser.clj"]
}
```

Responses contain the exit status and captured streams:

```json
{
  "version": 1,
  "exit": 0,
  "stdout": "...",
  "stderr": "..."
}
```

Set explicit request and response size limits. Reject malformed UTF-8, unknown
fields, embedded NUL bytes, excessive argument counts, and oversized messages.
Resolve `cwd` relative to an already-open repository descriptor without
following magic links or escaping the repository, retain the resulting
descriptor, and enter it with `fchdir`. A string-based canonicalization followed
by `chdir` is insufficient because the agent can replace a working-tree path
between those operations. The proxy passes the fixed repository path to
Jujutsu independently of `cwd`.

The proxy serializes requests per repository and runs every request in a fresh
process group or cgroup. It incrementally enforces output limits rather than
capturing unbounded output first. On timeout, client disconnect, or output-limit
failure, it kills and reaps the entire group. Apply explicit PID, memory, CPU,
file-size, and file-descriptor limits so malformed or expensive requests cannot
exhaust the outer daemon or leave descendants running.

The socket is an authorization boundary only by possession: the LLM is expected
to send arbitrary requests. Security comes from request validation, not from a
secret token or from trusting the wrapper.

== Repository access modes

The proxy distinguishes mutation access from read-only inspection access. A
mutation request is bound to the selected repository, uses its fixed working
copy descriptor, and receives read-write Landlock access to the working tree,
Jujutsu store, and resolved Git metadata. This is the only mode that may
snapshot a working copy or change repository state.

The launcher admits repositories by mounting the host source tree read-only at
`/src` in both containers. An inspection request identifies a directory beneath
that mount. The proxy opens its `cwd` components without following symlinks, requires
an ancestor with a `.jj` directory, and runs Jujutsu in a child process with a
second, read-only Landlock policy and `--ignore-working-copy`. Linked workspaces
whose metadata is outside the mounted tree are not admitted by this mechanism.
The trusted proxy may also resolve a single `-R` or `--repository` selector
against the invocation directory. It canonicalizes the target, requires a
workspace under `/src`, and derives access from the resolved workspace rather
than the client's requested mode. A client may request stricter inspection but
cannot grant mutation access to another workspace.
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
admission; the selected repository remains the sole mutation target.

== Wrapper

Replace the current `jj` shim's final invocation with a small client that sends
the current working directory and argument vector to the socket. Preserve its
existing agent identity and plain-diff behavior either by translating those
choices into request fields or, preferably, by moving identity selection into
the trusted proxy.

=== Runtime agent identity

Agent identity is dynamic session state, not repository configuration. Pi's
active model may change while the container is running, so `pi.json` and the
container's initial environment are not authoritative sources for commit
attribution.

The Pi integration owns the current model and writes its `provider` and
`modelId` to a session-scoped file whenever the active model changes. The
launcher gives Pi and its shell children a stable `PI_MODEL_FILE` path, but
the integration replaces the file atomically after each change. The file is a
transport representation, not an authorization source; the `jj` wrapper reads
it for every invocation, constructs the agent identity from the current value,
and includes that identity in the proxy request:

```text
Pi gpt-5.6-sol
```

The flow is therefore:

```text
Pi model switch
  -> Pi integration updates PI_MODEL_FILE
  -> jj wrapper reads the current file
  -> proxy request carries the resolved agent identity
  -> trusted jj commit records that identity as author and committer
```

The proxy must not infer the model from `pi.json`, a default model, repository
configuration, or an earlier request. A missing or malformed file, or a file
from another session, is an attribution failure: the wrapper must report a
warning and use the explicit unknown-model identity policy. It must not
silently claim that the configured default is active. Non-Pi agents retain
their existing identity sources.

All Jujutsu commands go through the proxy. Mutation-mode commands may snapshot
the working copy and write metadata. Inspection-mode commands must add
`--ignore-working-copy` and use read-only metadata mounts; the real binary
cannot otherwise be trusted to preserve the read-only boundary.

If the socket is unavailable, the wrapper fails closed with a concise error. It
must not fall back to a local real `jj` binary.

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
  when it resolves to the selected mutable workspace or an inspection workspace
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

For each allowed command, define the complete accepted grammar of subcommands,
options, option values, and positional operands. Reject every unrecognized
option wherever Jujutsu's parser would accept it, including global options that
appear after the subcommand. Do not rely on recognizing the top-level command
and passing the remainder through. Disable command aliases so validation applies
to the command Jujutsu actually executes. Alias spellings such as `jj push`,
`jj p`, `jj g push`, and `jj publish` are therefore rejected rather than
expanded; only the exact constrained `jj git fetch` grammar is accepted.

Reject arbitrary `--tool`, `--editor`, interactive diff or merge, signing, and
similar executable-selecting options even though the repository is mounted
no-exec in the proxy. Where needed, allow only named, hard-coded Jujutsu
built-ins such as `:git`; configuration cannot redefine an allowed built-in.
Reject alternate repository, workspace, operation-store, or configuration
paths in every syntactic position.

Git fetch accepts only pre-existing, approved remote names and reviewed URL
schemes and destinations. It cannot set a remote URL or select a credential
helper, SSH command, transport helper, hook, or arbitrary local path. Git push
is never accepted. Network access and credentials, if later required for fetch,
are separate explicit capabilities rather than consequences of allowing a Git
subcommand.

Pinning the Jujutsu version makes the accepted grammar stable; upgrading
Jujutsu requires reviewing new commands and options before changing the pin.
The policy must maintain separate mutation and inspection grammars; adding a
command to the inspection grammar requires proving that it remains read-only
under `--ignore-working-copy` and the read-only filesystem policy.

== Lifecycle

`codex-sandbox` performs these steps:

+ Resolve the repository root and metadata paths.
+ Create a session-specific socket volume and proxy container name.
+ Start the proxy with the repository mounted read-write and no-exec.
+ Wait for an explicit readiness response from the socket.
+ Start Codex with the working tree writable and metadata overlaid read-only.
+ On exit or signal, stop and remove the proxy and remove the socket volume.

Cleanup must preserve the Codex exit status and tolerate partially completed
startup. Names include the host UID and launcher PID to avoid collisions between
sessions.

== Implementation stages

+ Build the proxy and client with protocol framing, descriptor-relative
  fixed-repository execution, environment scrubbing, per-command grammar
  validation, serialization, process-group cleanup, and resource limits.
+ Add unit tests for every rejected escape surface and malformed request.
+ Add an integration fixture containing colocated `.jj` and `.git` metadata.
+ Add launcher support for the proxy container, socket volume, readiness, nested
  read-only mounts, and cleanup.
+ Add the Pi runtime identity channel and exercise a model switch before and
  after `jj status` and `jj commit`; verify that each commit uses the active
  model rather than the configured default.
+ Move the existing wrapper's identity behavior behind the proxy and remove any
  local-real-`jj` fallback.
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
- Absolute invocation of the real `jj` inside Codex cannot mutate metadata.
- Binaries and scripts in the proxy's working-tree mount cannot execute, and
  trusted interpreters or tools cannot be selected to interpret working-tree
  content.
- Shell metacharacters in commit messages remain literal data.
- Config overrides, repositories outside the `/src` mount, external tools, and
  `util exec` are rejected.
- Inspection requests can read only repositories under `/src` and cannot
  mutate their working trees, Jujutsu stores, Git metadata, configuration, or
  credentials.
- Git fetch is constrained to approved remotes, every Git push request is
  rejected, and the Codex container has no write-capable credentials for
  protected remotes.
- Supported commands preserve stdout, stderr, and exit status closely enough
  for interactive agent use.
- A Pi model switch is reflected by the next `jj` request and commit; a missing
  or malformed model file produces an explicit attribution warning rather than
  silently using `pi.json`'s default model.
- Concurrent requests are serialized; timed-out, oversized, and interrupted
  requests leave neither the proxy wedged nor descendant processes running.
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
