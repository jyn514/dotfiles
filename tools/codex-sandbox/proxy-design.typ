#set document(title: "Sandbox command proxies")
#set page(margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true)

= Sandbox command proxies

*Status:* Implemented.

== Objective

Allow an untrusted agent container to request a small set of trusted repository operations without giving it direct write access to protected metadata or the outer container daemon.

The design generalizes the sibling-container pattern used by `jj-proxy`.
The launcher remains unaware of repository-specific request schemas and argument grammars.
Repository-specific shims such as the `bb bug` client route requests to a proxy, which owns container isolation, request validation, and access to protected paths.

== Scope

The first additional capability is `bug`, which runs Flower's git-bug bridge with write access to Git metadata.
The design also supports future fixed commands that need authority unavailable inside the agent container.

This design does not make arbitrary repository commands safe, grant the agent Docker access, or infer trust from a read-only mount.
It also keeps reusable model-provider credentials outside the agent while granting the agent authority to make model requests through a launcher-owned sidecar.
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
- read, replace, or export a reusable model-provider access or refresh token

The agent is authorized to submit arbitrary supported model requests and therefore to disclose request content, consume quota, and incur charges within configured limits.
This authority is intentional and distinct from possession of the reusable upstream credential.

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
The model-provider sidecar described below is a launcher-owned sibling container rather than a manifest command because it carries user authority independent of the repository.

Each proxy image is read-only, non-root, capability-free, and uses `no-new-privileges`.
The launcher supplies explicit container-level PID, memory, CPU, filesystem, and file-descriptor limits.
Networking is disabled unless the manifest declares it and the command requires it.

== Manifest

`.agents/sandbox/proxy-commands.json` declares named proxies and their fixed execution policy.
The launcher also injects trusted built-in commands from its own installation checkout; repository-local declarations may add names but cannot replace a trusted command.
The `jj` command is such a built-in, so repositories can use it without copying the proxy implementation or declaring a local manifest.
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

Repositories that need no additional command proxies may omit the manifest or provide an empty one:

```json
{"version": 1, "commands": {}}
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

A proxy image starts the fixed server named by `argv`, binds `/run/sandbox-proxy/socket` only after initialization succeeds, and provides the fixed byte-forwarding client at `/trusted/bin/sandbox-proxy-forward` for host routing.

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
The directory contains stable `coordination.lock` and `session.lock` files plus atomically published session metadata.
The runtime directory is outside the repository and is not mounted into the agent container.

Before discovering or starting proxies, the launcher acquires an exclusive host-kernel advisory lock on `coordination.lock`, then takes a shared lock on `session.lock` for the complete sandbox session.
If session metadata exists, the launcher attaches its agent to the recorded socket volumes and uses the already validated manifest snapshot.
Otherwise it starts and publishes one shared proxy set before releasing the coordination lock.
It never deletes or replaces the lock file.
After every proxy becomes ready, the launcher atomically publishes session metadata containing the repository identity and each manifest command's immutable proxy container ID and resolved image hash.
The metadata contains no command-specific protocol version or request fields.

A launcher-supplied host router owns lock acquisition, stale-state cleanup, session discovery, and Podman invocation for every manifest command.
A host-side `bb bug` shim gives it the `bug` manifest key, framed request, and local bridge entrypoint.
The router chooses one path:

+ If it acquires the host lock, remove stale session metadata, run the local bridge with the human's authority, then release the lock
+ If the launcher holds the lock and valid metadata exists, use `podman exec` or the equivalent daemon API to run a fixed immutable byte-forwarding client in the recorded proxy container
+ If the lock is held without metadata, wait for metadata or lock release, then retry

A command-specific host shim invokes the same router directly:

```sh
sandbox-proxy-route \
  --repo "$repository" \
  --command example \
  -- local-example-bridge
```

The request and response remain on standard input and output.

Every proxy image contains that launcher-owned client at one conventional absolute path.
The router sends the framed request to the client's standard input; the client connects to the conventional in-VM Unix socket and copies the framed response to standard output without interpreting either message.
The router validates the container's launcher-owned session labels, resolved image hash, and repository identity before invoking the fixed client, and never executes a manifest- or caller-selected command through `podman exec`.
Only the trusted host router receives outer-daemon access; neither the agent nor a proxy container receives it.
Failure of Podman execution, the immutable client, or the proxy connection is a proxy error and never causes local fallback.

The host kernel releases a launcher's shared session lock when it exits or is killed because the lock belongs to its open file descriptor, not recorded PID data.
On exit, a launcher briefly reacquires the coordination lock and attempts an exclusive session lock.
Success proves it was the final holder, so it removes the shared proxies and metadata; failure leaves them available to the remaining sessions.
After a crash or reboot, successful exclusive session-lock acquisition proves that any remaining metadata is stale and safe to clean before local execution or replacement.
If a proxy container dies, every attached launcher marks the command unavailable and terminates its own agent.

Any number of launchers may share one checkout's proxy set.
Linked worktrees retain distinct repository identities and proxy sets.

== Trusted execution

The proxy starts from an empty environment and adds only manifest-declared or launcher-required fixed values.
It does not inherit credentials, agent forwarding, dynamic-loader variables, user configuration paths, pager or editor selection, or container-daemon access.

The proxy image contains every executable and source file needed by its command.
A trusted interpreter may read attacker-controlled code even from a `noexec` mount, so mounting the working tree `noexec` is only defense in depth.
For an interpreted repository tool, the immutable image carries the trusted startup snapshot of the program rather than invoking the mutable checkout's copy.

The launcher starts a proxy with its manifest `argv` as the fixed operation.
It does not expose a general-purpose shell, `docker exec`, alternate entrypoint, or arbitrary command API to the agent.

== Model-provider credential sidecar <model-provider-sidecar>

The launcher starts a trusted sibling container and redirects Pi's existing provider `baseUrl` to it over the sandbox network.
Only the sidecar mounts a launcher-managed Codex authentication directory, without any ordinary home or configuration directory.
The trusted `codex-sandbox auth login` command creates that OAuth login rather than copying the human's normal Codex refresh token, so the two clients cannot race token rotation.
The agent receives no provider access or refresh token through its image, mounts, environment, configuration, responses, or logs.
The sidecar writes refresh updates transactionally within that directory.

The sidecar is a small streaming reverse proxy.
It accepts only the required provider request path and method, strips client authorization and forwarding headers, sends the request to one fixed HTTPS origin, injects upstream authorization, and streams the response back.
It rejects other paths, methods, origins, and oversized requests; it neither interprets prompts nor translates the provider protocol.

Each sidecar receives a random session key that Pi sends as its placeholder API key.
The key is readable by the agent and intentionally grants only the model-request authority Pi already has; it is not an upstream credential and stops working when the sidecar exits.
This prevents unrelated containers on the shared sandbox network from using the sidecar.

The sidecar follows the existing proxy-container lifecycle and hardening: immutable launcher-owned image, non-root user, read-only root filesystem, dropped capabilities, `no-new-privileges`, bounded resources, no repository or outer-daemon mount, and cleanup with the agent session.
The Codex authentication directory is its only writable host mount.
Pi continues to use `openai-codex-responses` with only `baseUrl` and the placeholder API key changed.
Startup, authentication, or refresh failure fails closed and never falls back to mounting the credential in the agent.

Passwordless sudo inside the agent does not weaken this boundary: container root has no outer-daemon access and cannot inspect the sibling's filesystem, processes, or mounts.
It can call the sidecar directly, but that grants only the model-request authority Pi already has.

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
Publishing refs remains a maintainer command outside the sandbox; the proxy receives neither network access nor push credentials, and the agent receives no write-capable Git credentials, writable SSH agent, or reusable provider token that could bypass the proxy through Git or a hosting API.
The model-provider sidecar accepts only model API requests and cannot reach source-hosting APIs, so its bounded request authority does not grant publication authority.
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
Its repository bind starts at the nearest common ancestor of a linked worktree, its `gitdir`, and its common Git directory, and is writable to preserve filesystem identity.
A fail-closed Landlock policy permits reads only from the selected worktree, its resolved metadata, and trusted runtime files; it permits writes only beneath the resolved Git metadata, `.jj`, the proxy's private configuration directory, and its socket directory.
Metadata operations remain available, while commands that would update ordinary working-copy files fail at the Landlock boundary.
Execution is permitted only beneath `/trusted/bin`, giving the working tree the same effective `noexec` property under Docker and Podman without unsafe syscall bindings or a hard-coded kernel ABI.
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
+ Start the model-provider sidecar with its authentication-directory mount and one fresh session key, then verify readiness
+ Atomically publish session metadata for the ready proxies
+ Start the agent with metadata, sandbox configuration, socket volumes overlaid read-only, and its provider base URL redirected to the sidecar
+ Stop the session's sidecar and proxies, remove session resources, and release the host lock when the agent exits or startup fails

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
- The agent and agent root cannot read the Codex access token, refresh token, OAuth exchange, or authentication directory through files, environment, process inspection, logs, network responses, or the outer daemon
- Pi can stream supported model requests through the sidecar without a real credential in agent `auth.json`, and direct supported requests have no more authority than Pi's own requests
- Unknown methods, paths, origins, oversized bodies, and client authorization headers fail closed
- Sidecar login and refresh update only the dedicated authentication directory transactionally and do not alter the human's ordinary Codex login
- Sidecar unavailability and authentication failure never fall back to direct authenticated provider access or mounting the credential in the agent
- A session key fails after its sidecar exits and cannot authenticate directly to the upstream provider
- Passwordless sudo remains functional inside the agent without granting access to sibling containers or their mounts
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
