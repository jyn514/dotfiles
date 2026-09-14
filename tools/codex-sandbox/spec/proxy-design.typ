= Sandbox command proxies

*Status:* Proxy isolation, transports, capability selection, image resolution,
and request-failure isolation are implemented. The generic authenticated egress
broker specified below is selected but not implemented. Manifest examples below
describe the temporary version 1 wire format.

== Objective

Let an untrusted agent container request selected trusted repository operations without direct write access to protected metadata or the outer container daemon.

The design generalizes the sibling-container pattern used by `jj-proxy`.
The launcher remains unaware of repository-specific request schemas and argument grammars.
Repository-specific shims such as the `bb bug` client route requests to a proxy, which owns container isolation, request validation, and access to protected paths.

== Scope

The first additional capability is `bug`, which runs Flower's git-bug bridge with write access to Git metadata.
The design also supports future fixed commands that need authority unavailable inside the agent container.

This design does not make arbitrary repository commands safe, grant the agent Docker access, or infer trust from a read-only mount.
It also keeps reusable service credentials outside the agent while granting bounded HTTP request authority through launcher-owned instances of one authenticated egress broker component.
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
- read, replace, or export a reusable upstream credential
- choose an authenticated upstream origin, authorization scheme, or credential source

The agent is authorized to submit requests allowed by its selected egress routes and therefore may disclose request content, consume quota, mutate remote state where a route permits it, and incur charges within configured limits.
This authority is intentional and distinct from possession of a reusable upstream credential.

Proxy manifests under `.agents/sandbox/` are trusted repository configuration.
The configuration loader accepts repository command, resolver, and mount declarations without a built-in command allowlist, so the repository and its manifest authors must be trusted before startup. It returns validated policy and a bound resolver to the launcher; it does not execute image resolution while loading policy.
The read-only mount protects that accepted policy from the running agent; it does not authenticate its source.

Trusted proxy images, their fixed entrypoints, and any code copied into them are also part of the trusted computing base.
A proxy must not load executable code from the agent-writable working tree.

== Protected sandbox configuration

Implemented sandbox-owned repository configuration lives under:

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

At the first launch of a shared session, the loader resolves and validates the repository root and any existing `.agents/sandbox` before starting containers. An absent configuration file or directory selects the installed defaults described by the launcher interface; an existing invalid path is an error. Reject symlinked components, unexpected metadata indirection, and hard-linked manifest or executable files reachable through an agent-writable mount.
When the directory is absent, no configuration overlay is needed: the accepted default policy remains fixed for the session, and configuration created by the agent is never loaded on a join. A later session must accept it through trusted startup. When the directory exists, retain its nested read-only overlay even if the configuration file is absent. The accepted configuration source, including its absence, remains fixed for the session.

== Architecture

The outer launcher starts the agent and its proxies as sibling containers:

```text
outer container-engine daemon
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
Each authenticated egress broker instance described below is a launcher-owned sibling container rather than a manifest command because it carries user authority independent of the repository.

Each proxy image is read-only, non-root, capability-free, and uses `no-new-privileges`.
The launcher supplies explicit container-level PID, memory, CPU, filesystem, and file-descriptor limits.
Networking is disabled unless the manifest declares it and the command requires it.

== Implemented manifest and selected replacement

`.agents/sandbox/proxy-commands.json` declares named proxies and their fixed execution policy.
The launcher also injects trusted built-in commands from its own installation checkout; repository-local declarations may add names but cannot replace a trusted command.
The `jj` command is such a built-in, so repositories can use it without copying the proxy implementation or declaring a local manifest.
The temporary version 1 image adapter comprises `image-command`, `image-target`,
`argv`, `workdir`, `network`, and `mounts`. The
#link("launcher-interface.typ")[version 2 launcher interface] now owns repository
syntax and optional capability selection; resolver lifecycle migration remains open.
The fixed execution and mount policies below apply through either path.
Container resource limits, generated container names, socket-volume identifiers, startup polling, and cleanup mechanics are launcher implementation details rather than manifest fields.
A representative first manifest is:

```json
{
  "version": 1,
  "commands": {
    "bug": {
      "image-target": "bb-bug",
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
The configuration loader rejects unknown fields, unsupported schema versions, malformed paths, escaping paths, duplicate targets, and configurations that would hide the proxy executable or socket. The launcher receives validated execution policy rather than manifest fields.

`mounts` grants additional or overriding views without command-specific launcher knowledge.
Each entry names a source, repository-relative target, and the access mode seen by the proxy and agent containers.
The modes are `read-write`, `read-only`, and `hidden`.
An omitted proxy mode inherits the proxy's read-only repository view, while an omitted agent mode inherits the agent's ordinary repository view and protected-metadata overlays.
Writable proxy authority must be declared per path; one mount does not make its parent or siblings writable.
The launcher establishes all declared views before the agent starts and applies an agent restriction to every untrusted agent container in the session.
A project resolver may create a declared source before returning its image reference; otherwise the launcher rejects a missing source rather than silently omitting its mount.

The launcher passes `argv` directly to process execution, never through a shell, and resolves its executable only through the proxy's fixed trusted `PATH`; manifest arguments cannot name absolute container binary paths.
The manifest starts one fixed server; its image owns the server and protocol policy, while the matching agent-side shim owns the client.
The launcher provides the conventional socket volume and waits for readiness but remains unaware of Flower's request schema and argument grammar.
For `bb-bug`, the immutable image contains both the socket server and the trusted bridge entrypoint.

Image resolution follows #link("launcher-interface.typ")[the launcher interface].
The loader binds declaration details behind the resolver interface. The launcher
selects capabilities first and, at shared-session creation, invokes only their required resolvers,
and verifies immutable results in the admitted engine before starting consumers.
The #link("bake-resolver.typ")[bundled Bake resolver] owns its input capture and
cache policy; project resolvers own their existing image lifecycle.

A proxy image starts the fixed server named by `argv`, binds the path in `SANDBOX_PROXY_SOCKET` (defaulting to `/run/sandbox-proxy/socket`) only after initialization succeeds, and provides the fixed byte-forwarding client at `/trusted/bin/sandbox-proxy-forward` for readiness checks and runtimes that use container execution for host routing.
The forwarding client uses the configured path while it exists and otherwise falls back to the default path.

The selected resolver and all executable inputs it loads are trusted startup support code.
It resolves freshness at shared-session creation, with shared dependencies resolved once.
Starting another sandbox for the same checkout joins the existing shared session. Joins use its accepted configuration and immutable images without reading changed sandbox configuration or invoking image resolvers. The launcher verifies recorded images and live services before attaching; invalid recorded state fails only the join.
Configuration and source changes take effect at the next trusted startup after the final attached agent exits. Per-agent instructions, skills, and extensions remain reloadable through `/reload`.
There is no live replacement: one server retains ownership of command serialization, sockets, and shared state for the session.

== Socket protocol

Each proxy is published at `/run/sandbox-proxy/socket` in its session-specific volume.
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
If a live shared session exists, the launcher validates its recorded state and attaches using the accepted configuration, image set, and socket volumes as specified by the launcher interface. It does not compare against current repository declarations. Per-launch relays retain separate resources and tokens under the accepted opt-ins and current host authorization.
Otherwise it starts and publishes one shared proxy set before releasing the coordination lock.
It never deletes or replaces the lock file.
After required repository-command proxies and broker adapters become ready, the launcher atomically publishes session metadata containing the repository identity, recorded runtime owner, accepted route set, and every command-proxy and broker-instance container identity, immutable image reference, socket or network endpoint, and credential-domain identity.
Lima ownership includes the VM generation, namespace, hardware identity, and network-policy digest; legacy metadata belongs to Podman.
A join validates each recorded container, image, endpoint, network attachment, and required readiness state before attaching; it neither restarts one missing instance nor substitutes current policy.
The metadata contains no command-specific request fields, reusable credentials, refresh state, or session tokens.

A launcher-supplied host router owns lock acquisition, stale-state cleanup, session discovery, and recorded-runtime invocation for every host-routable manifest command or typed broker adapter.
A host-side shim supplies the accepted command or adapter name, framed request, and local entrypoint; it never supplies a container, socket, token, image, or upstream origin.
The router chooses one path:

+ If it acquires the host lock, retain stale recovery metadata, run the local bridge with the human's authority, then release the lock
+ If the launcher holds the lock and valid metadata exists, use the recorded runtime's transport to the validated proxy socket
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
Podman and Lima-containerd send the framed request to that client's standard input; it connects to the in-VM Unix socket and copies the response without interpreting either message.
Lima-Docker connects directly through a session-owned Unix-socket forward on Lima's existing SSH master. Its host transport copies request bytes, shuts down the write side at input EOF, and copies response bytes until EOF. Command-specific shims and servers own framing, size limits, deadlines, and application status; the transport does not parse messages. A zero transport status reports stream completion, not command success or a valid response; callers must reject missing or malformed response frames. SSH may deliver EOF where a container client reported a remote socket reset.
The router resolves the accepted command-proxy or broker-adapter endpoint from published metadata, then validates its launcher-owned session labels, native image identity, credential-domain identity where applicable, and repository identity before opening the transport.
It never executes a manifest- or caller-selected command or connects to a caller-selected endpoint through the outer runtime.
Only the trusted host router receives outer-daemon access; neither the agent nor a proxy or broker container receives it.
Failure of outer-runtime execution, the immutable client, or the proxy connection is a proxy error and never causes local fallback.

For Lima-Docker, each proxy's recovery state records its volume owner and guest socket target before registration. A private short guest alias avoids Unix-socket path limits; a private host listener is registered with OpenSSH's `-O forward`. Both live as long as the cached proxy, including intervals without an attached agent. Requests own only their connections: terminating a router closes its connection without stopping the SSH master or other requests. This does not promise cancellation of work the server already accepted.
Cleanup cancels the recorded listener with `-O cancel`, removes the matching guest alias, then removes proxy containers and volumes. A failed cancellation retains recovery state unless the listener refuses connections, as after master replacement. Cached sessions lacking forwarding records or a live host listener are rebuilt when exclusive; shared joins require active sessions to exit first.

The host kernel releases a launcher's shared session lock when it exits or is killed because the lock belongs to its open file descriptor, not recorded PID data.
On exit, a launcher briefly reacquires the coordination lock and attempts an exclusive session lock.
Success proves it was the final holder, so it removes the shared proxies and metadata; failure leaves them available to the remaining sessions.
After a crash or reboot, successful exclusive session-lock acquisition proves that any remaining metadata is stale and safe to clean before local execution or replacement.
If a command proxy or authenticated egress broker becomes unavailable after startup, affected requests fail closed and report the failure. Attached agents remain running; the launcher does not monitor sibling liveness to terminate them. Required readiness checks still gate startup, and an unhealthy shared session cannot accept new agents. Recovery requires attached agents to exit before shared services restart.

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

== Generic authenticated egress broker <authenticated-egress-broker>

=== Purpose and boundary

Replace duplicated authenticated-HTTP implementations with one broker component, instantiated once per credential trust domain.
Each instance owns one credential profile, its fixed upstream identities, authorization transformation, request limits, and authenticated-egress logs.
The launcher owns route selection, secret-source admission, session tokens, networks, instances, and lifecycle.
The agent owns only the application request accepted by a route adapter; it never supplies an upstream URL or receives the reusable credential.

The first concrete users are Codex model requests and Zulip transcript reads.
Both need fixed-origin HTTPS, hidden reusable credentials, bounded transport, and fail-closed lifecycle behavior, but they do not share application authority: Codex forwards a narrow HTTP surface, while Zulip accepts a typed read-only operation and owns pagination and rate limiting.
They therefore share broker machinery and image construction but run in separate instances with disjoint credential mounts, networks, tokens, mutable state, and failure domains.
Combining unrelated credentials in one process is rejected because compromise through either protocol would expose both.
Flower R2 is a later user only if a separate broker profile implements reviewed AWS Signature Version 4 signing while preserving per-request Keychain consent; generic header injection does not satisfy that boundary.
Host editing, Agent Podman, repository commands, and arbitrary public internet access remain outside this broker.

=== Route authority

The broker starts from a normalized set of immutable routes accepted at shared-session creation.
A route has:

- a stable launcher-owned route name, selected capability, and broker instance
- one fixed `https` origin, including host and port
- one installed application adapter: `http`, `zulip-read`, or another reviewed type
- adapter-specific methods, paths, query construction, completion rules, and request and response schemas
- request-body, response-body, header, duration, redirect, and concurrency limits
- one launcher-owned authentication profile or explicit `none`
- a response policy for headers exposed to the agent

Repository configuration may select an installed route through a capability.
It may declare credential-free project routes because the repository is already trusted startup policy, but it cannot name a host credential source, request an installed authentication profile, replace an installed route, or turn an unauthenticated route into an authenticated one.
Installed authentication profiles bind route names to credential owners outside repository-controlled configuration.
The loader rejects duplicate routes, unknown fields, user-info in origins, non-HTTPS authenticated origins, IP literals unless explicitly installed, wildcard hosts, path traversal, overlapping ambiguous prefixes, unbounded limits, and authentication references outside the installed namespace.
Accepted routes and their source provenance enter shared-session metadata; joins use that accepted set without reloading configuration.

=== Agent protocols and adapters

Each broker instance publishes only the transports required by its installed adapters.
An HTTP adapter listens on its private session network at a route base URL such as:

```text
http://codex-egress:8787/v1/routes/codex/<relative-path>
```

The launcher gives the agent an instance-specific bearer token and route base URL.
The token expires with that instance, authorizes only its routes, and is useless upstream.
Socket or network possession without it is insufficient.
The broker validates the token and route on every request.

The HTTP adapter rejects `CONNECT`, absolute- and authority-form targets, fragments, encoded separators, dot segments, malformed critical headers, and paths outside its prefixes after one percent-decoding and normalization pass.
Queries are rejected unless the adapter declares a query schema; that schema bounds encoded size, names allowed keys, defines duplicate-key and blank-value behavior, and validates values before constructing the upstream query.
The adapter constructs the upstream URL from its fixed origin, validated path, and validated query, resolves DNS itself, and never follows redirects.
An upstream redirect is returned only when response policy permits `Location`; it is never converted into another broker request.

The HTTP adapter removes hop-by-hop headers, client `Authorization`, `Proxy-Authorization`, `Forwarded`, `Via`, `X-Forwarded-*`, `Host`, and every authentication-reserved header.
It sets upstream authority and transport, applies authentication, and streams the body without translating the application protocol.
The route enumerates surviving client-controlled headers; all others are rejected.
Response policy similarly allowlists headers and removes upstream authentication challenges, cookies unless required, forwarding metadata, and internal diagnostics.

A typed adapter instead retains its existing bounded framed protocol over a session socket.
The Zulip adapter accepts only transcript and topic-list operations, constructs fixed API paths and queries, serializes access, enforces the existing two-second spacing, honors bounded `429 Retry-After`, paginates, validates responses, and emits the existing response schema.
It does not expose a general Zulip HTTP prefix.
Its socket remains reachable through #link(<host-coordination>)[host coordination], so a host `zulip` command uses the active instance and otherwise performs the same typed operation locally.
The sandbox client never falls back locally.

Each request has separate limits for request headers or frames, request body, response headers or frames, response body, total duration, idle duration, and redirects.
The broker enforces limits while streaming and never buffers an unbounded body.
Before sending response headers or a response frame, it returns a typed policy or upstream error.
After an HTTP response has begun, timeout, disconnect, or a body limit closes the upstream and downstream streams; clients must treat premature EOF or missing protocol completion as failure rather than a valid short response.
Typed adapters send no success frame until their complete bounded result validates.
Whether a remote mutation committed before cancellation may be unknown; the broker does not retry non-idempotent requests.
Other retries belong to the reviewed adapter, not generic transport policy.

=== Credential owners and transformations

A credential profile is installed trusted code, not repository data.
It defines one secret owner, one transformation, and one route set.
The initial transformations are deliberately narrow:

/ OAuth bearer: read and transactionally refresh the dedicated Codex OAuth state, then replace client authorization with one bearer header. The ordinary human Codex login remains a separate owner.
/ Static API header: read a launcher-approved secret file or host credential and set one fixed header. The agent cannot choose the header name or secret lookup key.
/ Zulip basic authentication: construct the fixed upstream authorization value from the admitted Zulip identity without returning either component to the agent; this profile is bound only to the `zulip-read` adapter.

Secret providers return opaque values only to their profile implementation.
Profiles must not expose a generic template language, environment expansion, arbitrary header maps, caller-selected accounts, or caller-selected Keychain services.
A refresh-capable profile is the sole writer of its refresh state and publishes an update by atomic replacement only after the complete refreshed state is durable.
Failure to read, refresh, or inject credentials fails that request and never falls back to agent credentials, a different host account, or unauthenticated upstream access.

AWS Signature Version 4 is excluded from the initial broker because it signs method, path, selected headers, and a payload hash and therefore is not equivalent to static credential injection.
Adding it requires a separate profile specification covering streaming payloads, clock ownership, retries, canonicalization, per-use consent, and outcome-unknown writes.
Until then, Flower R2 retains its dedicated relay and disclosed-credential semantics.

=== Network and process isolation

Each broker instance joins one internal agent-link network and one restricted egress network.
Only that instance receives both networks.
The agent reaches its private address but cannot route through it except through its declared adapter; the instance enables neither IP forwarding nor generic forward-proxy mode.
By default, the egress network prohibits private and special-use addresses after DNS resolution, for every resolved address and connection attempt; DNS rebinding fails closed.
An installed route requiring a private destination must declare the exact host and permitted CIDRs in launcher-owned policy, and the network owner must install the matching narrow exception before startup.
Repository routes cannot request this exception.

The broker image is launcher-owned and independent of the customizable agent image.
Every instance runs non-root with a read-only root filesystem, all capabilities dropped, `no-new-privileges`, bounded PIDs, memory, CPU, and file descriptors, and only its profile's credential mounts.
It receives no repository mount, outer-daemon socket, SSH agent, ordinary home directory, or unrelated credential.
Routes may share an instance only when they use the same credential profile and trust domain; instances never share credentials, mutable refresh files, tokens, networks, concurrency budgets, or failure status.
A failed request does not terminate another route in the same instance.
Process failure makes that instance's routes unavailable and never causes direct fallback.

Passwordless sudo inside the agent does not weaken this boundary: container root cannot inspect the sibling's filesystem, processes, mounts, or egress network.
It can invoke every selected route, but gains only the remote request authority already granted by those routes.

=== Observability

Logs record session identity, route name, method, normalized path classification, response status, byte counts, duration, limit failures, and cancellation outcome.
They never record query values, request or response bodies, authorization values, cookies, credential-source paths, refresh exchanges, or complete URLs containing user data.
Route profiles may further redact path components or headers but cannot weaken the baseline exclusions.
Before an HTTP response begins, diagnostics distinguish policy rejection, credential failure, upstream transport failure, timeout, and response-limit failure without secret material or upstream authorization details.
After streaming begins, the client sees only premature EOF or missing protocol completion; broker logs retain the specific terminal cause.

=== Migration and removal

Migration is consumer-by-consumer:

+ Implement the broker image and Codex HTTP adapter while preserving Pi's existing `baseUrl` and placeholder-key integration.
+ Port the existing Zulip framed protocol into a separate broker instance with the `zulip-read` adapter; preserve host routing, read-only request construction, pagination, response validation, pacing, and bounded `429` handling.
+ Keep Flower R2 on its dedicated Keychain relay until a separately reviewed signing profile preserves consent and avoids credential disclosure.
+ Delete service-specific HTTP, authentication, hardening, image, and lifecycle implementations only after joins, restart, refresh, host routing, and failure recovery use the shared broker component. Separate credential-domain containers and networks remain intentional.

The broker does not initially replace the agent's existing credential-free public network.
Consequently it simplifies and bounds authenticated egress but does not claim complete domain allowlisting for arbitrary tools.
A later direct-egress removal is a separate design: it must account for package managers, source downloads, certificate handling, `CONNECT`, non-HTTP protocols, and development usability rather than turning this reverse proxy into a transparent gateway.

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
The authenticated egress broker instances have no source-hosting publication route, so their bounded request authority does not grant publication authority.
Deployments that add broader authenticated routes must enforce the same restriction in their accepted route and credential-profile boundaries.

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

Short helper calls share the launcher's interpreter and receive explicit argument lists.
They reuse the Git metadata resolved during repository validation for that launch;
standalone helper commands still discover their own repository metadata.
The launcher owns its session and publication locks directly. Lock acquisition runs on the signal-owning
thread while other startup jobs proceed, so a contended launch can be cancelled.

The first launch creates the shared session with these steps. Joins instead validate and reuse its accepted configuration, image set, shared services, and metadata, then prepare their selected per-launch relays and start an agent; they neither resolve images nor republish shared state.

+ Resolve and validate the repository and protected paths
+ Acquire the repository's host session lock
+ Read and validate the trusted manifest
+ Select the fixed launch capability set
+ Resolve only selected consumers' images and dependencies through the launcher interface; validate immutable references in the admitted engine
+ Create session-specific socket volumes and container names
+ Start each configured proxy with its declared mounts and limits
+ Wait for required repository-command sockets to become ready
+ Start one authenticated egress broker instance per selected credential profile, with its accepted routes, profile-specific credential mount, and fresh token; verify every required HTTP listener and typed-adapter socket before publication
+ Atomically publish session metadata for the command-proxy and broker-instance set
+ When host editing or nested container access is selected, create the per-sandbox gateway networks and start only its selected listeners in a launcher-owned background job
+ When Flower R2 access is selected, prepare its separate relay using the readiness and consent rules in #link("r2-keychain-relay-design.typ")[the R2 specification]
+ Start the agent with metadata, sandbox configuration, socket volumes overlaid read-only, and selected clients directed to their broker route base URLs
+ Join all selected relay startup jobs before cleanup, deferring termination signals during the join
+ Detach the agent, then stop the broker instances and command proxies and remove session resources after the last attached agent exits or startup fails

Cleanup preserves the agent's exit status and removes only resources owned by that session.
When selected, the agent addresses editor and Podman ports by the gateway's session-specific container DNS name.
Early requests may fail; gateway startup failures are reported without terminating the agent.
The host editor rejects all peers until gateway address inspection installs its allowlist.
Upstream refusal ends only that connection; listener failure stops the gateway.
Names include the host UID and first launcher PID to prevent collisions.

The launcher may keep a proxy alive for the whole sandbox session.
Long-lived command proxies and the egress broker amortize image startup without sharing trusted mutable state between unrelated sandbox sessions.

== Acceptance checks

- The agent cannot modify `.git`, `.jj`, or `.agents/sandbox` directly, through an alternate path, or through a sibling metadata proxy
- Editing ordinary working-tree files remains possible
- The generic host router runs `bb bug` locally while it owns the host lock and uses the recorded runtime to reach the proxy while a sandbox launcher owns that lock
- Proxied reads and writes work without giving the agent access to `.git/git-bug` or queue control state
- `--body-file` contents cross the proxy as bounded standard input, and the proxy never opens the supplied path
- `bb bug push` and `bb bug raw` are rejected by the proxy, and push remains a maintainer-only command
- The agent cannot publish refs through direct Git, SSH-agent, credential, or provider-API access
- The agent and agent root cannot read any broker-owned access token, refresh token, basic-auth component, refresh exchange, or credential store through files, environment, process inspection, logs, network responses, or the outer daemon
- Pi streams model requests through its fixed HTTP route, while Zulip clients use only the typed read-only adapter; neither receives reusable credentials
- Unknown routes, methods, paths, origins, oversized bodies, forbidden headers, redirects, and client authorization fail closed
- Route normalization rejects encoded separators, dot segments, absolute targets, ambiguous prefixes, and prohibited resolved addresses
- Codex login and refresh update only the dedicated authentication directory transactionally and do not alter the human's ordinary Codex login
- A route failure does not expose its credential or affect another credential-domain instance
- Broker unavailability and authentication failure never fall back to direct authenticated provider access or mounting credentials in the agent
- A session key fails after its broker exits, authorizes only the accepted routes, and cannot authenticate directly to an upstream provider
- Broker logs and diagnostics contain no query values, bodies, cookies, reusable credentials, refresh exchanges, or complete sensitive URLs
- Non-idempotent requests are not retried, and cancellation reports an outcome-unknown remote mutation where success cannot be established
- Passwordless sudo remains functional inside the agent without granting access to sibling containers or their mounts
- The agent cannot append arguments, choose another executable, alter mounts, inject environment variables, or redirect the command to another repository
- Modified working-tree copies of `bb.edn`, bridge source, git-bug, or proxy scripts do not affect trusted execution
- An invalid, ambiguous, unavailable, or wrong-platform resolver result fails before its consumer starts
- Resolver freshness, sharing, refresh, and capability omission satisfy the launcher interface's acceptance checks
- Joins reuse accepted configuration and images without running resolvers, even after sandbox configuration or source edits; existing agents, sockets, and services remain untouched
- `/reload` updates per-agent instructions, skills, and extensions without reloading sandbox configuration or shared proxies
- Loss of a command proxy or broker instance reports request failures without terminating attached agents or falling back to local privileged execution or direct provider credentials
- Editing proxy source after startup does not rebuild, replace, or otherwise change the running proxy
- Concurrent drain requests execute serially
- Local human bridge execution cannot overlap a sandbox session
- Human commands during a sandbox session reach the same serialized proxy path as agent commands through the fixed in-container client
- Launcher crash or termination releases the host lock, and a later command removes stale session metadata safely
- Runtime, client, or proxy-container failure does not permit local fallback while the launcher still owns the host lock
- Direct metadata deletion fails while proxy-mediated issue updates succeed
- Malformed and oversized socket or queue requests fail without wedging the proxy
- Timeout, disconnect, and forced termination leave no descendants and permit a later successful drain
- Protocol-version mismatch and configured-but-unavailable sockets fail closed
- Proxy startup and shutdown preserve pre-existing working-copy changes and unrelated repository metadata
- A changed manifest takes effect only in a later sandbox session after trusted startup has accepted it
