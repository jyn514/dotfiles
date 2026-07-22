#set document(title: "Sandbox command proxies")
#set page(margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true)

= Sandbox command proxies

*Status:* Design only.

== Objective

Allow an untrusted agent container to request a small set of trusted repository operations without giving it direct write access to protected metadata or the outer container daemon.

The design generalizes the sibling-container pattern used by `jj-proxy`.
The launcher remains unaware of repository-specific request schemas and argument grammars.
Repository-specific shims such as the `bb bug` client route requests to a proxy, which owns container isolation, request validation, and access to protected paths.

== Scope

The first additional capability is `bug`, which runs Flower's git-bug bridge with write access to Git metadata.
The design also supports future fixed commands that need authority unavailable inside the agent container.

This design does not make arbitrary repository commands safe, grant the agent Docker access, or infer trust from a read-only mount.
Jujutsu retains `jj-proxy`'s command-specific argument policy while using the generic manifest lifecycle.

== Trust model

Treat every process in the agent container as untrusted, including root.
The agent may bypass `PATH`, invoke binaries by absolute path, compile programs, modify ordinary working-tree files, and send arbitrary requests to every mounted proxy socket.

The agent must not be able to:

- write, replace, rename, or remove protected repository metadata directly
- choose a proxy executable, image, mount, environment variable, or container option
- execute mutable working-tree code with proxy authority
- redirect a proxy to another repository
- control the outer container daemon
- increase its proxy capabilities during a sandbox session

Proxy manifests under `.agents/sandbox/` are trusted repository configuration.
The launcher accepts their command, image-builder, mount, and environment declarations without a built-in capability allowlist, so the repository and its manifest authors must be trusted before startup.
The read-only mount protects that accepted policy from the running agent; it does not authenticate its source.

Trusted proxy images, their fixed entrypoints, and any code copied into them are also part of the trusted computing base.
A proxy must not load executable code from the agent-writable working tree.

== Protected sandbox configuration

Sandbox-owned repository configuration lives under:

```text
.agents/sandbox/
├── base-image
└── proxy-commands.json
```

The launcher mounts the repository normally and then overlays `.agents/sandbox` read-only in the agent container:

```text
--mount type=bind,src=$repo,dst=$container_repo
--mount type=bind,src=$repo/.agents/sandbox,dst=$container_repo/.agents/sandbox,readonly
```

Every sibling container with a read-write view of the working tree must receive the same nested read-only overlay.
Without it, a metadata proxy could change the host copy as a side effect of `restore`, `undo`, checkout, or another working-copy operation even though the agent's own path is read-only.

The launcher resolves and validates the repository root and `.agents/sandbox` before starting any container.
It rejects a missing directory, symlinked components, unexpected metadata indirection, and hard-linked manifest or executable files reachable through an agent-writable mount.
The validated source remains fixed for the session.

== Architecture

The outer launcher starts the agent and its proxies as sibling containers:

```text
outer Docker or Podman daemon
|
+-- jj-proxy
|   +-- repository metadata read-write
|   `-- session socket volume
|
+-- command-proxy: bug
|   +-- trusted bridge and git-bug binaries
|   +-- repository read-only
|   +-- declared Git and bridge metadata read-write
|   +-- .agents/sandbox overlaid read-only
|   `-- session socket volume
|
`-- agent
    +-- working tree read-write
    +-- .git and .jj overlaid read-only
    +-- manifest-declared paths overlaid with their agent modes
    +-- .agents/sandbox overlaid read-only
    `-- proxy socket volumes mounted read-only
```

The proxy containers receive no outer daemon socket.
The agent may receive a separate, isolated inner container service, but that service cannot replace the outer launcher's mounts or proxy containers.

Each proxy image is read-only, non-root, capability-free, and uses `no-new-privileges`.
The launcher supplies explicit container-level PID, memory, CPU, filesystem, and file-descriptor limits.
Networking is disabled unless the manifest declares it and the command requires it.

== Manifest

`.agents/sandbox/proxy-commands.json` declares named proxies and their fixed execution policy.
The stable version 1 interface comprises `version`, `commands`, and each command's `image-command`, `argv`, `workdir`, `network`, and `mounts` fields, including the mount fields and modes below.
Container resource limits, generated container names, socket-volume identifiers, startup polling, and cleanup mechanics are launcher implementation details rather than manifest fields.
A representative first manifest is:

```json
{
  "version": 1,
  "commands": {
    "bug": {
      "image-command": [".agents/sandbox/bb-bug-image"],
      "argv": ["bb-bug-proxy", "serve"],
      "workdir": ".",
      "network": false,
      "mounts": [
        {
          "source": ".git",
          "target": ".git",
          "proxy": "read-write",
          "agent": "read-only"
        },
        {
          "source": ".agent-git-bug",
          "target": ".agent-git-bug",
          "proxy": "read-write",
          "agent": "read-only"
        }
      ]
    }
  }
}
```

The launcher implicitly mounts the validated repository read-only at its common repository path and overlays `.agents/sandbox` read-only; the manifest cannot omit or weaken either protection.
`workdir`, mount sources, and mount targets are relative to the repository root unless the schema explicitly defines a launcher-owned source.
The launcher resolves targets beneath its container repository path, so the manifest does not depend on an absolute path such as `/src/work`.
The launcher rejects unknown fields, unsupported schema versions, malformed paths, escaping paths, duplicate targets, and configurations that would hide the proxy executable or socket.

`mounts` grants additional or overriding views without command-specific launcher knowledge.
Each entry names a source, repository-relative target, and the access mode seen by the proxy and agent containers.
The modes are `read-write`, `read-only`, and `hidden`.
An omitted proxy mode inherits the proxy's read-only repository view, while an omitted agent mode inherits the agent's ordinary repository view and protected-metadata overlays.
Writable proxy authority must be declared per path; one mount does not make its parent or siblings writable.
The launcher establishes all declared views before the agent starts and applies an agent restriction to every untrusted agent container in the session.
An image command may create a declared source before returning its image hash; otherwise the launcher rejects a missing source rather than silently omitting its mount.

The launcher passes `argv` directly to process execution, never through a shell, and resolves its executable only through the proxy's fixed trusted `PATH`; manifest arguments cannot name absolute container binary paths.
The manifest starts one fixed server; its image owns the server and protocol policy, while the matching agent-side shim owns the client.
The launcher provides the conventional socket volume and waits for readiness but remains unaware of Flower's request schema and argument grammar.
For `bb-bug`, the immutable image contains both the socket server and the trusted bridge entrypoint.

`image-command` is an argument array that the launcher executes before the agent starts.
Like `.agents/sandbox/base-image`, the command may inspect the trusted startup checkout, build an image from its current sources, pull an existing image by tag or digest, or reuse a cached build.
It prints exactly one resolved image hash on standard output and sends progress or diagnostics to standard error.
The launcher rejects an empty, malformed, or multi-line result and starts the proxy by the returned immutable image hash rather than by a mutable tag.
An image builder that needs stronger reproducibility may also pin and verify an OCI digest.

The image command and everything it loads from `.agents/sandbox` are trusted manifest support code.
It completes before the agent starts and never reruns during the session, so agent edits cannot rebuild or replace the resolved image.
At the start of a later session, the repository and its manifest support code must be accepted as trusted again before the launcher runs them.

== Socket protocol

Each proxy listens at `/run/sandbox-proxy/socket` in its session-specific volume.
The agent mounts that volume read-only at `/run/sandbox-proxies/<command>/`, which permits connection to the existing socket but prevents replacing it.
The launcher sets the generic `SANDBOX_PROXY_DIR=/run/sandbox-proxies` environment variable in the agent and derives `<command>` from the manifest key.
A command-specific shim constructs its socket path from that directory and its known manifest key; the launcher needs no command-specific environment variable or protocol configuration.

A fixed command needs only a bounded request.
A command-specific protocol may carry reviewed fields, as the `bb-bug` protocol does:

```json
{
  "version": 1,
  "command": "bug",
  "argv": ["show", "abc123"],
  "stdin": ""
}
```

The response preserves the command's exit status and bounded output:

```json
{
  "version": 1,
  "exit": 0,
  "stdout": "...",
  "stderr": "..."
}
```

Each connection carries one request and one response.
The client shuts down its write side after the request, and the server verifies end of input before executing the command and closes the connection after its response.
Each message starts with a four-byte unsigned big-endian byte length followed by exactly that many bytes of UTF-8 JSON.
The receiver rejects a length above its configured message limit before allocating or reading the body, premature end of input, trailing bytes, malformed UTF-8 or JSON, unknown or duplicate fields, and unsupported `version` values.
The `version` field identifies the complete command-specific request and response contract, including framing, fields, validation, and semantics.
Socket possession is authorization to request the configured command, so security depends on the manifest and proxy implementation rather than a secret token.

Each protocol defines separate limits for argument count, individual and aggregate argument size, standard input, standard output, standard error, and command duration.
The client enforces the input limit while reading rather than buffering an unbounded body before framing the request.
The image server is responsible for request validation, request-level input and output limits, timeouts, disconnect handling, process-group cleanup, and reaping descendants.
The launcher is responsible for the coarser container limits and for stopping the complete proxy container during session cleanup.
The server binds the conventional socket only after its initialization succeeds and is then ready to accept requests.
The command-specific shim and server check the protocol version on every request, and the client fails clearly when they are incompatible.

On timeout, disconnect, or output-limit failure, the image server kills and reaps the complete child process group.
Proxy failure is fail-closed; a client never falls back to a local privileged executable.

== Host coordination <host-coordination>

The launcher, not a proxy container, owns cross-boundary coordination between sandbox and host processes.
Container advisory locks cannot provide that coordination on systems such as macOS, where containers run under a separate Linux virtual-machine kernel and bind-mounted files cross the host/guest boundary.

The launcher derives a repository identity from the canonical Git common directory and uses a per-user host runtime directory for that identity.
The directory contains a stable `session.lock` and atomically published session metadata.
The runtime directory is outside the repository and is not mounted into the agent container.

Before starting any proxy, the launcher acquires an exclusive host-kernel advisory lock on `session.lock` and holds its open file descriptor for the complete sandbox session.
It never deletes or replaces the lock file.
After every proxy becomes ready, the launcher atomically publishes session metadata containing the repository identity and each manifest command's immutable proxy container ID and resolved image hash.
The metadata contains no command-specific protocol version or request fields.

A launcher-supplied host router owns lock acquisition, stale-state cleanup, session discovery, and Podman invocation for every manifest command.
A host-side `bb bug` shim gives it the `bug` manifest key, framed request, and local bridge entrypoint.
The router chooses one path:

+ If it acquires the host lock, remove stale session metadata, run the local bridge with the human's authority, then release the lock
+ If the launcher holds the lock and valid metadata exists, use `podman exec` or the equivalent daemon API to run a fixed immutable byte-forwarding client in the recorded proxy container
+ If the lock is held without metadata, wait for metadata or lock release, then retry

Every proxy image contains that launcher-owned client at one conventional absolute path.
The router sends the framed request to the client's standard input; the client connects to the conventional in-VM Unix socket and copies the framed response to standard output without interpreting either message.
The router validates the container's launcher-owned session labels, resolved image hash, and repository identity before invoking the fixed client, and never executes a manifest- or caller-selected command through `podman exec`.
Only the trusted host router receives outer-daemon access; neither the agent nor a proxy container receives it.
Failure of Podman execution, the immutable client, or the proxy connection is a proxy error and never causes local fallback.

The host kernel releases the session lock when the launcher exits or is killed because the lock belongs to its open file descriptor, not recorded PID data.
After a crash or reboot, successful lock acquisition proves that any remaining metadata is stale and safe to remove before local execution.
If only a proxy container dies, the launcher still owns the session lock; it marks the command unavailable, cleans up the session, and releases the lock only after proxy-mediated execution can no longer resume.

Only one launcher may own a Git common directory at a time.
Additional sandbox launches for that repository fail rather than creating independent metadata writers.

== Trusted execution

The proxy starts from an empty environment and adds only manifest-declared or launcher-required fixed values.
It does not inherit credentials, agent forwarding, dynamic-loader variables, user configuration paths, pager or editor selection, or container-daemon access.

The proxy image contains every executable and source file needed by its command.
A trusted interpreter may read attacker-controlled code even from a `noexec` mount, so mounting the working tree `noexec` is only defense in depth.
For an interpreted repository tool, the immutable image carries the trusted startup snapshot of the program rather than invoking the mutable checkout's copy.

The launcher starts a proxy with its manifest `argv` as the fixed operation.
It does not expose a general-purpose shell, `docker exec`, alternate entrypoint, or arbitrary command API to the agent.

== Git-bug proxy <git-bug-proxy>

The `bug` proxy runs the existing `bb bug` bridge outside the agent container.
Reads, writes, queue draining, cache maintenance, and other supported local operations all follow this path, so the agent never needs access to `.git/git-bug`.

The bridge needs read-write access to more than `.git/git-bug`:

- `.git/objects/` for new Git objects
- `refs/bugs/*` and `refs/identities/*` for authoritative issue state
- `.git/git-bug/` for clocks, caches, indexes, selection, and transient locks
- `.agent-git-bug/` for queued requests and results

The `bug` mount gives only the proxy write access to `.agent-git-bug/inbox`, `processing`, `done`, `failed`, `results`, and temporary bridge files, preventing the agent from replacing requests or control state during a command.
The trusted bridge enqueues, drains, and reads each transported invocation inside the proxy before returning its response.
Agent-authored body files no longer need to live under `.agent-git-bug/tmp`; contributor instructions should name an ordinary agent-writable scratch location instead.

The immutable proxy image includes pinned copies of Babashka, git-bug, the bridge namespaces, their runtime dependencies, and the `bb-bug-proxy` server.
It must not run `bb.edn`, Clojure source, scripts, or configuration from the writable checkout.

Inside the agent, `bb bug` sends its argument vector and standard input through the proxy socket when present and otherwise runs the local bridge.
The check is a routing convenience rather than an authorization boundary: bypassing or editing it gives the agent only the read-only metadata view.
An unavailable or incompatible configured proxy fails closed instead of falling back locally.
The privileged bridge always runs at the validated repository root; the shim resolves and consumes path-based agent inputs before sending the request.

The editable Flower source supplies the unprivileged client rather than the launcher or proxy image.
Editing or bypassing it changes only the requests sent; server validation and metadata protection remain authoritative.

For `--body-file`, the shim reads the file with the agent's authority, sends the bounded contents in the request, and rewrites the argument to `--body-stdin` before privileged execution.
The proxy therefore never follows an agent-selected body path or reads a file visible only in its container.
An invocation that already uses `--body-stdin` forwards bounded standard input unchanged.
A direct socket request that still contains `--body-file` is invalid, so bypassing the shim cannot recover the privileged path-reading behavior.

The protocol rejects `bb bug push` and `bb bug raw` before execution.
Publishing refs remains a maintainer command outside the sandbox; the proxy receives neither network access nor push credentials, and the agent receives no write-capable Git credentials, writable SSH agent, or provider token that could bypass the proxy through Git or a hosting API.
Deployments that permit broader network credentials must enforce the same restriction at their credential or egress boundary.

During a sandbox session, #link(<host-coordination>)[host coordination] sends agent and human requests to the same long-lived `bug` proxy instead of running the local bridge.
The proxy processes complete operations serially, so no PID comparison or stale-lock recovery crosses namespaces or the host/guest kernel boundary.
Diagnostic request-owner details do not control mutual exclusion.

If a drain is interrupted after git-bug starts, the bridge applies its existing recovery policy and rebuilds derived cache state when required.
Authoritative issue state remains in Git refs.

== Jujutsu proxy

`jj-proxy` is a manifest command using the same trusted sibling-container lifecycle, session socket volume, read-only metadata overlays in the agent, scrubbed environment, fixed binaries, and bounded execution.

`jj-proxy` accepts a broad but validated Jujutsu argument grammar because interactive repository work needs operands and options.
Jujutsu atomically links temporary objects between `.jj` and `.git`, so separate writable bind mounts introduce an unusable cross-device boundary.
Its repository bind is writable to preserve filesystem identity, while a fail-closed Landlock policy permits writes only beneath `.git`, `.jj`, the proxy's private configuration directory, and its socket directory.
Metadata operations remain available, while commands that would update ordinary working-copy files fail at the Landlock boundary.
The `bug` protocol is narrower than Jujutsu's grammar: it forwards one bridge subcommand, rewrites body input, rejects `push` and `raw`, and leaves issue-operation validation to the trusted bridge.

The generic manifest does not replace `jj-proxy`'s command-specific validation.
A future proxy command with caller-controlled arguments must define a complete accepted grammar and reject executable selection, alternate repositories, configuration overrides, and other privilege-crossing surfaces.

== Lifecycle

The launcher performs these steps:

+ Resolve and validate the repository and protected paths
+ Acquire the repository's host session lock
+ Read and validate the trusted manifest
+ Run every proxy image command and validate its resolved image hash
+ Create session-specific socket volumes and container names
+ Start each configured proxy with its declared mounts and limits
+ Wait for each conventional server socket to become ready
+ Atomically publish session metadata for the ready proxies
+ Start the agent with metadata, sandbox configuration, and socket volumes overlaid read-only
+ Stop proxies, remove session resources, and release the host lock when the agent exits or startup fails

Cleanup preserves the agent's exit status and removes only resources owned by that session.
Names include the host UID and launcher PID to prevent collisions.

The launcher may keep a proxy alive for the whole sandbox session.
One long-lived `bug` proxy can avoid cross-container lock ambiguity and amortize image startup without sharing trusted mutable state between unrelated sandbox sessions.

== Acceptance checks

- The agent cannot modify `.git`, `.jj`, or `.agents/sandbox` directly, through an alternate path, or through a sibling metadata proxy
- Editing ordinary working-tree files remains possible
- The generic host router runs `bb bug` locally while it owns the host lock and uses Podman to reach the proxy while a sandbox launcher owns that lock
- Proxied reads and writes work without giving the agent access to `.git/git-bug` or queue control state
- `--body-file` contents cross the proxy as bounded standard input, and the proxy never opens the supplied path
- `bb bug push` and `bb bug raw` are rejected by the proxy, and push remains a maintainer-only command
- The agent cannot publish refs through direct Git, SSH-agent, credential, or provider-API access
- The agent cannot append arguments, choose another executable, alter mounts, inject environment variables, or redirect the command to another repository
- Modified working-tree copies of `bb.edn`, bridge source, git-bug, or proxy scripts do not affect trusted execution
- An invalid or ambiguous image-command result fails before a proxy starts
- A mutable tag used by an image builder resolves to one immutable image hash for the running session
- Editing proxy source after startup does not rebuild, replace, or otherwise change the running proxy
- Concurrent drain requests execute serially
- Local human bridge execution cannot overlap a sandbox session
- Human commands during a sandbox session reach the same serialized proxy path as agent commands through the fixed in-container client
- Launcher crash or termination releases the host lock, and a later command removes stale session metadata safely
- Podman, client, or proxy-container failure does not permit local fallback while the launcher still owns the host lock
- Direct metadata deletion fails while proxy-mediated issue updates succeed
- Malformed and oversized socket or queue requests fail without wedging the proxy
- Timeout, disconnect, and forced termination leave no descendants and permit a later successful drain
- Protocol-version mismatch and configured-but-unavailable sockets fail closed
- Proxy startup and shutdown preserve pre-existing working-copy changes and unrelated repository metadata
- A changed manifest takes effect only in a later sandbox session after trusted startup has accepted it
