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
- invoke supported Jujutsu operations with arbitrary valid operands; and
- make logically destructive but recoverable history edits, such as `abandon`
  or `rebase`, when those commands are included in policy.

== Architecture

`codex-sandbox` starts two sibling containers under the outer container daemon:

```text
outer Docker or Podman daemon
|
+-- jj-proxy
|   +-- repository mounted read-write
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

== Mount layout

The Codex container receives the repository normally, followed by nested
read-only mounts for its metadata:

```text
--mount type=bind,src=$repo,dst=$container_repo
--mount type=bind,src=$repo/.git,dst=$container_repo/.git,readonly
--mount type=bind,src=$repo/.jj,dst=$container_repo/.jj,readonly
--mount type=volume,src=$socket_volume,dst=/run/jj-proxy,readonly
```

The proxy receives the repository read-write at the same absolute path and the
socket volume read-write. Keeping the path identical makes working-copy paths
and diagnostics agree between containers.

The launcher must resolve and validate the repository root before starting
either container. It must reject missing, symlinked, or unexpectedly shaped
metadata rather than silently starting without protection. A Git worktree may
use a `.git` file instead of a directory; the implementation must support a
read-only file mount and also protect the referenced Git directory if that
directory lies within an agent-writable mount.

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
fields, embedded NUL bytes, excessive argument counts, oversized messages, and
paths that escape the fixed repository after lexical and filesystem
canonicalization. The proxy serializes requests per repository and applies a
timeout to every child process.

The socket is an authorization boundary only by possession: the LLM is expected
to send arbitrary requests. Security comes from request validation, not from a
secret token or from trusting the wrapper.

== Wrapper

Replace the current `jj` shim's final invocation with a small client that sends
the current working directory and argument vector to the socket. Preserve its
existing agent identity and plain-diff behavior either by translating those
choices into request fields or, preferably, by moving identity selection into
the trusted proxy.

All Jujutsu commands, including apparently read-only commands such as `status`
and `diff`, go through the proxy. Jujutsu may snapshot the working copy and
write metadata during those commands, so the real binary cannot reliably run
against the read-only metadata view.

If the socket is unavailable, the wrapper fails closed with a concise error. It
must not fall back to a local real `jj` binary.

== Command policy

The request carries an argument array that is passed directly to `execve`; the
proxy never invokes `sh -c` or reparses shell quoting.

Use a pinned Jujutsu binary and a trusted, immutable configuration. Start the
child with a minimal environment, including fixed values equivalent to:

```text
PATH=/trusted/bin
JJ_CONFIG=/trusted/jj.toml
PAGER=cat
GIT_PAGER=cat
EDITOR=false
VISUAL=false
```

Accept most ordinary Jujutsu subcommands, but reject privilege-crossing
surfaces:

- `util`, especially `util exec`;
- `debug`;
- configuration mutation and all command-line configuration overrides;
- alternate repository, workspace, or config paths;
- arbitrary diff, merge, editor, pager, signing, or conflict-resolution tools;
- `git init` and commands that redirect storage; and
- irreversible recovery deletion such as operation abandonment or garbage
  collection.

Maintain an allowlist of top-level commands rather than a denylist. Initially
include common working-copy and history operations: `status`, `diff`, `log`,
`show`, `interdiff`, `commit`, `describe`, `new`, `split`, `squash`, `rebase`,
`restore`, `abandon`, `duplicate`, `edit`, `next`, `prev`, `undo`, constrained
bookmark commands, and explicitly selected Git synchronization commands.

Validate global options before identifying the subcommand. Pinning the Jujutsu
version makes the accepted grammar stable; upgrading Jujutsu requires reviewing
new commands and options before changing the pin.

== Lifecycle

`codex-sandbox` performs these steps:

+ Resolve the repository root and metadata paths.
+ Create a session-specific socket volume and proxy container name.
+ Start the proxy with the repository mounted read-write.
+ Wait for an explicit readiness response from the socket.
+ Start Codex with the working tree writable and metadata overlaid read-only.
+ On exit or signal, stop and remove the proxy and remove the socket volume.

Cleanup must preserve the Codex exit status and tolerate partially completed
startup. Names include the host UID and launcher PID to avoid collisions between
sessions.

== Implementation stages

+ Build the proxy and client with protocol framing, fixed-repository execution,
  environment scrubbing, argument validation, serialization, and timeouts.
+ Add unit tests for every rejected escape surface and malformed request.
+ Add an integration fixture containing colocated `.jj` and `.git` metadata.
+ Add launcher support for the proxy container, socket volume, readiness, nested
  read-only mounts, and cleanup.
+ Move the existing wrapper's identity behavior behind the proxy and remove any
  local-real-`jj` fallback.
+ Exercise normal status, diff, commit, split, rebase, undo, and Git sync flows.
+ Attempt direct metadata writes as the ordinary user and through `sudo`; both
  must fail while proxy commits succeed.

== Acceptance checks

- `rm -rf .git .jj` from Codex fails without damaging host metadata.
- Direct writes, renames, symlink replacement, and writes through `/proc` or an
  alternate path to the same mounts fail.
- Absolute invocation of the real `jj` inside Codex cannot mutate metadata.
- Shell metacharacters in commit messages remain literal data.
- Config overrides, alternate repositories, external tools, and `util exec` are
  rejected.
- Supported commands preserve stdout, stderr, and exit status closely enough
  for interactive agent use.
- Concurrent requests are serialized and interrupted requests do not leave the
  proxy wedged.
- Proxy failure is fail-closed, and launcher cleanup removes only resources for
  its own session.
- Existing non-agent working-copy changes remain intact across proxy startup,
  commands, and shutdown.

== Alternatives rejected

A `PATH` wrapper is not enforcement because it can be bypassed. Unix ownership
cannot grant access based on the executable being run. Landlock and bubblewrap
restrictions are inherited by child processes, so an in-container `jj` cannot
regain metadata access. A setuid `jj` or setuid wrapper would place Jujutsu's
large CLI, configuration, and subprocess surface inside the privilege boundary.
The sibling proxy keeps that boundary small, explicit, and testable.
