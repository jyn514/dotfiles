= Sandbox command proxies

*Status:* Proxy isolation, transports, capability selection, image resolution, and
request-failure isolation are implemented. Caddy 2.11.4-alpine with private profile
helpers is the selected Zulip authenticated-egress architecture. Model requests
use host Pi's native authentication and providers, not a sandbox broker. Host Pi with guest tools is implemented as an execution
path, but conformance to the host extension authority contract remains unverified;
the `git` built-in mount is implemented in the launcher, not yet consumed by the
`bug` proxy. Manifest examples use the temporary version 1 format.
The shared-dotfiles workspace authority and cross-proxy JJ locking contract is implemented.

== Objective

Let an untrusted agent container request selected trusted repository operations without direct write access to protected metadata or the outer container daemon.

The design generalizes the sibling-container pattern used by `jj-proxy`.
The launcher remains unaware of repository-specific request schemas and argument grammars.
Repository-specific shims such as the `bb bug` client route requests to a proxy, which owns container isolation, request validation, and access to protected paths.

== Scope

The first additional capability is `bug`, which runs Flower's git-bug bridge with write access to Git metadata.
The design also supports future fixed commands that need authority unavailable inside the agent container.

This design does not make arbitrary repository commands safe, grant the agent Docker access, or infer trust from a read-only mount.
It also keeps reusable service credentials outside the agent while granting bounded HTTP request authority through launcher-owned Caddy instances with private credential-profile helpers.
Jujutsu retains `jj-proxy`'s command-specific argument policy while using the generic manifest lifecycle.

== Trust model

Treat every process in the agent container as untrusted, including root.
The agent may bypass `PATH`, invoke binaries by absolute path, compile programs, modify ordinary working-tree files, and send arbitrary requests to every mounted proxy socket.

The agent must not be able to:

- write, replace, rename, or remove protected repository metadata directly
- choose a proxy executable, image, mount, environment variable, or container option
- execute mutable working-tree code with proxy authority
- redirect a proxy to a repository outside its trusted workspace authority
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

== Host extension authority

The selected #link("launcher-interface.typ")[host-Pi design] moves conversation
and UI code to the host while retaining the untrusted guest workload and proxy
boundaries. In container descriptions below, “agent” then means the guest tool
worker and its descendants. Host Pi is trusted mediation code. During normal
operation, model-controlled input uses guest tools or admitted bounded host
capabilities rather than Pi's ambient filesystem, credentials, or process authority.
Guest tool routing is not a malicious-code security boundary: a failed extension
reload may restore host-local built-in tools and `!` commands in parents and
children. Proxy and authenticated-route failures still fail closed: they cannot
fall back to privileged local commands or direct credentials.

Classify operations by their trigger, inputs, and granted effects rather than by
whether an extension imports a filesystem or subprocess API. Human commands and
trusted configuration may select host operations; model-controlled arguments may
invoke only explicitly bounded host capabilities or guest execution. Automatic
hooks can consume model-writable data and must retain that data's authority.

#table(
  columns: (1fr, 2fr),
  [Extension group], [Selected placement and authority],
  [Context/system-prompt viewers, skill autocomplete, prompt-history search],
  [Host UI. Human history search may run a fixed search over the host session store;
   restoring editor text does not execute it.],
  [Date, notification, direct-skill and subagent routing],
  [Host hooks. Fixed date/notification effects and validated model/template selection
   do not authorize a new execution environment.],
  [Compaction, provider web search, native provider selection],
  [Host model integration. Use host Pi's native authentication and providers;
   provider-side search does not imply arbitrary host URL fetching.],
  [Goal tracking],
  [Host session state through Pi APIs, including model-invoked goal tools and
   automatic continuation. Clipboard export remains a human command with data
   passed to a fixed program rather than interpreted as code.],
  [Session search, read, and title edits],
  [Bounded host session-store capability. Resolve targets through one canonical
   validated store interface, including title-result hooks; model-supplied paths
   cannot widen access. Bound search work without blocking the TUI.],
  [Instruction includes and project resources],
  [Resolve recursive project includes and resource reads in the guest view:
   model-writable instruction text can select paths. Explicit personal host
   resources are separately selected by trusted configuration.],
  [Subagents],
  [Host manager and UI with inherited guest execution during normal operation,
   as specified by the launcher. Tasks or templates do not select another backend;
   failed extension reload has the routing limitation described above.],
  [Human interactive `/split`],
  [Copies invoking context and attaches a peer pane to the existing guest worker;
   grants no model-selected host launch inputs or additional sandbox authority.],
  [Other execution extensions and MCP],
  [Guest execution by default; host admission requires a reviewed bounded capability.
   Installed packages or staged configuration alone do not establish activation
   or authority. No arbitrary extension compatibility is promised.],
)

Host-loaded Pi, extensions, dependencies, and executable configuration must come
from a host-controlled installation inaccessible to guest writes through any
mount alias. The current writable npm/Git package stores and a writable dotfiles
checkout are not suitable host code sources. A read-only extension alias does
not protect bytes also exposed through a writable workspace mount.
`/reload` may reload admitted code and guest-view resources; it cannot promote
guest-modified packages or project extensions to host execution. Host registration
must distinguish bounded host capabilities from guest-backed tools and reject
unclassified model-executable handlers. Replacing only Bash is insufficient.

*Known implementation gap:* host extensions still load from the guest-writable dotfiles checkout, so the host-code isolation requirement above remains unmet.
The approved whole-checkout writable-dotfiles scope proceeds with this limitation; its metadata and policy overlays do not enforce host-code isolation.
This approval does not remove the requirement or establish conformance.

Host Pi intentionally owns model authentication through its native providers.
Model credentials remain outside guest worker mounts and environment; the launcher
does not register a sandbox model provider or project a model session token.
This decision removes an unused guest broker, not the host-code or instruction-read
isolation requirements above.

== Protected sandbox configuration

Implemented sandbox-owned repository configuration lives under:

```text
.agents/sandbox/
├── base-image
└── proxy-commands.json
```

The launcher mounts the active workspace and launcher dotfiles writable for ordinary files, then protects each `.agents/sandbox`.
The following overlay applies to each authorized workspace in the agent container:

```text
--mount type=bind,src=$repo,dst=$container_repo
--mount type=bind,src=$repo/.agents/sandbox,dst=$container_repo/.agents/sandbox,readonly
```

Command proxies other than JJ remain active-project scoped and receive the same nested read-only overlay there.
Adding dotfiles does not accept its policy or credentials.
The JJ proxy receives both trusted workspace roots and deliberately omits their configuration overlays: allowed `restore`, `undo`, and checkout operations may change or remove tracked sandbox configuration through its writable repository view.
Even a writable nested mount would prevent JJ from removing the directory when checking out a revision that predates it.
The agent still has no direct write access to sandbox configuration; its contents can change indirectly through allowed JJ operations.

At the first launch of a shared session, the loader resolves and validates the repository root and any existing `.agents/sandbox` before starting containers. An absent configuration file or directory selects the installed defaults described by the launcher interface; an existing invalid path is an error. Reject symlinked components, unexpected metadata indirection, and hard-linked manifest or executable files reachable through an agent-writable mount.
When the directory is absent, no configuration overlay is needed: the accepted default policy remains fixed for the session, and configuration created by the agent is never loaded on a join.
A later session must accept it through trusted startup.
When the directory exists, retain its nested read-only overlay in the agent and command proxies other than JJ even if the configuration file is absent.
JJ working-copy changes do not replace the session's accepted policy.
A later trusted startup may accept the changed configuration.

== Architecture

The implemented launcher starts Pi and its proxies as sibling containers. In the
selected host-Pi design, the guest tool worker replaces Pi in the agent container;
the same mount and proxy boundaries remain:

```text
outer container-engine daemon
|
+-- jj-proxy
|   +-- active and launcher-dotfiles metadata read-write
|   +-- both working trees read-write, including .agents/sandbox
|   +-- persistent request locks per JJ backing repository
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
    +-- active and launcher-dotfiles ordinary files read-write
    +-- .git, .jj, and external metadata overlaid read-only
    +-- manifest-declared paths overlaid with their agent modes
    +-- .agents/sandbox overlaid read-only
    `-- proxy socket volumes mounted read-only
```

The proxy containers receive no outer daemon socket.
The agent may receive a separate, isolated inner container service, but that service cannot replace the outer launcher's mounts or proxy containers.
Each authenticated egress service instance described below is launcher-owned sibling infrastructure rather than a manifest command because it carries user authority independent of the repository.

Each proxy image is read-only, non-root, capability-free, and uses `no-new-privileges`.
The launcher supplies explicit container-level PID, memory, CPU, filesystem, and file-descriptor limits.
Networking is disabled unless the manifest declares it and the command requires it.

== Implemented manifest and selected replacement

`.agents/sandbox/proxy-commands.json` declares named proxies and their fixed execution policy.
The launcher also injects trusted built-in commands from its own installation checkout; repository-local declarations may add names but cannot replace a trusted command.
The `jj` command is such a built-in, so repositories can use it without copying the proxy implementation or declaring a local manifest.
The temporary version 1 image adapter comprises `image-command`, `image-target`,
`argv`, `workdir`, `network`, and `mounts`. The
#link("launcher-interface.typ")[version 2 launcher interface] owns repository
syntax, optional capability selection, and image resolution. The first publisher
captures normalized policy and immutable resolver results in schema 4 accepted
state; joiners use those accepted inputs without loading current policy or invoking
a resolver. The fixed execution and mount policies below apply through either path.
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
          "builtin": "git",
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

Command proxies receive a read-only repository view by default and a read-only `.agents/sandbox` overlay.
Declared writable mounts may override the repository view but cannot weaken that overlay.
The launcher-owned JJ proxy instead uses a writable repository view without a sandbox configuration overlay.
`workdir`, mount sources, and mount targets are relative to the repository root unless the schema explicitly defines a launcher-owned source.
The launcher resolves targets beneath its container repository path, so the manifest does not depend on an absolute path such as `/src/work`.
The configuration loader rejects unknown fields, unsupported schema versions, malformed paths, escaping paths, duplicate targets, and configurations that would hide the proxy executable or socket. The launcher receives validated execution policy rather than manifest fields.

`mounts` grants additional or overriding views without command-specific launcher knowledge.
An ordinary entry names a source, repository-relative target, and the access mode seen by the proxy and agent containers.
The modes are `read-write`, `read-only`, and `hidden`.
An omitted proxy mode inherits the proxy's read-only repository view, while an omitted agent mode inherits the agent's ordinary repository view and protected-metadata overlays.
Writable proxy authority must be declared per path; one mount does not make its parent or siblings writable.
The launcher establishes all declared views before the agent starts and applies an agent restriction to every untrusted agent container in the session.
A project resolver may create a declared source before returning its image reference; otherwise the launcher rejects a missing source rather than silently omitting its mount.

A built-in entry uses `builtin` instead of `source` and `target`; these forms cannot be mixed.
The selected `git` built-in identifies the repository's backing Git metadata, not a literal working-tree `.git` path.
It requires explicit modes: the proxy may receive `read-write` or `read-only`, while the agent must receive `read-only`.
The loader rejects unknown or repeated built-ins; the launcher rejects any explicit mount with the same resolved target.
The launcher resolves the Git directory and any separate common directory once, including for non-colocated Jujutsu workspaces; missing, ambiguous, or non-Git metadata fails startup.
It mounts all required metadata at launcher-owned paths, preserving Git's internal references, and supplies the in-container Git-directory path as `SANDBOX_GIT_DIR`.
The launcher's existing protected metadata overlay supplies the agent's read-only view; alternate mount paths must not grant write access.
The manifest names neither a host metadata path nor a container target, and expansion does not depend on the command name.

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
Configuration and source changes take effect at the next trusted startup after the final execution attachment closes. Per-agent instructions, skills, and extensions remain reloadable through `/reload` under the host extension authority rules above.
There is no live replacement: one server retains ownership of sockets and shared state for the session.
JJ mutations additionally use shared per-backing-repository request locks across distinct servers; this adds no service lifecycle.

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

The launcher derives a workspace-session repository identity from both the canonical workspace root and Git common directory.
It uses a per-user host runtime directory for that identity.
The directory contains stable `coordination.lock` and `session.lock` files plus atomically published session metadata.
The runtime directory is outside the repository and is not mounted into the agent container.

Before discovering or starting proxies, the launcher acquires an exclusive host-kernel advisory lock on `coordination.lock`, then takes a shared lock on `session.lock` for the complete sandbox session.
If a live shared session exists, the launcher validates its recorded state and attaches using the accepted configuration, image set, and socket volumes as specified by the launcher interface. It does not compare against current repository declarations. Per-launch relays retain separate resources and tokens under the accepted opt-ins and current host authorization.
Otherwise it starts and publishes one shared proxy set before releasing the coordination lock.
It never deletes or replaces the lock file.
After required repository-command proxies and Caddy services and typed adapters become ready, the launcher atomically publishes session metadata containing the repository identity, recorded runtime owner, accepted route set, and every command-proxy and authenticated-egress container identity, immutable image reference, socket or network endpoint, and credential-domain identity.
Lima ownership includes the VM generation, namespace, hardware identity, and network-policy digest; legacy metadata belongs to Podman.
A join validates each recorded container, image, endpoint, network attachment, and required readiness state before attaching; it neither restarts one missing instance nor substitutes current policy.
The owner-validated mode-`0600` metadata contains authenticated-egress session tokens needed by validated joiners, but no command-specific request fields, reusable upstream credentials, or refresh state.

A launcher-supplied host router owns lock acquisition, stale-state cleanup, session discovery, and recorded-runtime invocation for every host-routable manifest command or typed authenticated-egress adapter.
A host-side shim supplies the accepted command or adapter name, framed request, and local entrypoint; it never supplies a container, socket, token, image, or upstream origin.
The #link("tic-proxy.typ")[TicGit capability] instead provides a restricted host-native broker with best-effort startup and `agent-launch` scope.
Startup failure warns and leaves TicGit unavailable without blocking Pi; it never selects privileged local execution or native guest fallback.
Accepted workspace policy selects the capability; each launch owns a fresh endpoint and token, retained across its ordinary children and `/split` peers until final attachment release.
The guest client reads guest file inputs and normalizes them to native stdin arguments; the host validates and forwards those arguments without opening guest paths.
The TicGit contract owns that normalization, fixed command policy, repository support restrictions, and native outcome semantics.
Its guest transport never opens the database; ordinary host `ti` uses the installed TicGit fork without this router or a running broker.
Native host cwd and concurrency semantics remain unchanged; the approved ordinary `-F -` feature reads stdin.
Separate brokers may use the same SQLite database without a cross-VM writer lock or persistent service scope.
R2 is an analogy for per-launch listener and relay ownership, not a reusable guest-to-host execution route.
This proposal does not change routing for other capabilities.
For host-routable capabilities, the router chooses one path:

+ If it acquires the host lock, retain stale recovery metadata, run the local bridge with the human's authority, then release the lock
+ If the launcher holds the lock and valid metadata exists, use the recorded runtime's transport to the validated proxy socket
+ If the lock is held without metadata, wait for metadata or lock release, then retry

In the selected host-Pi mode, exclusive lock acquisition proves coordination
ownership, not that guest work stopped. Before taking the local path, the router
must require launcher-owned recovery to disable abandoned attachment admission
and verify recorded guest work and services stopped. An unavailable runtime or
incomplete cleanup blocks local execution and preserves recovery metadata.
Surviving host children cannot reuse an abandoned attachment. This replaces the
implemented local path's assumption that retaining stale metadata is sufficient;
the router delegates recovery rather than becoming another workload supervisor.

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
The router resolves the accepted command-proxy or typed-adapter endpoint from published metadata, then validates its launcher-owned session labels, native image identity, credential-domain identity where applicable, and repository identity before opening the transport.
It never executes a manifest- or caller-selected command or connects to a caller-selected endpoint through the outer runtime.
Only the trusted host router receives outer-daemon access; neither the agent nor a proxy or authenticated-egress container receives it.
Failure of outer-runtime execution, the immutable client, or the proxy connection is a proxy error and never causes local fallback.

For Lima-Docker, each proxy's recovery state records its volume owner and guest socket target before registration. A private short guest alias avoids Unix-socket path limits; a private host listener is registered with OpenSSH's `-O forward`. Both live as long as the cached proxy, including intervals without an attached agent. Requests own only their connections: terminating a router closes its connection without stopping the SSH master or other requests. This does not promise cancellation of work the server already accepted.
Cleanup cancels the recorded listener with `-O cancel`, removes the matching guest alias, then removes proxy containers and volumes. A failed cancellation retains recovery state unless the listener refuses connections, as after master replacement. Cached sessions lacking forwarding records or a live host listener are rebuilt when exclusive; shared joins require active sessions to exit first.

The host kernel releases a launcher's shared session lock when it exits or is killed because the lock belongs to its open file descriptor, not recorded PID data.
On exit, a launcher briefly reacquires the coordination lock and attempts an exclusive session lock.
Success proves it was the final holder, so it removes the shared proxies and metadata; failure leaves them available to the remaining sessions.
After a crash or reboot, successful exclusive session-lock acquisition proves that any remaining metadata is stale and safe to clean before local execution or replacement.
If a command proxy or Caddy authenticated-egress instance becomes unavailable after startup, affected requests fail closed and report the failure. Attached agents remain running; the launcher does not monitor sibling liveness to terminate them. Required readiness checks still gate startup, and join-time validation rejects an unavailable shared service. Recovery requires attached agents to exit before shared services restart.

Any number of launchers may share one checkout's proxy set.
Under the selected #link("launcher-interface.typ")[interactive `/split` plan],
one launcher retains its guest worker and session lock across peer panes; the first
Pi's exit is not final-holder release.
Linked worktrees retain distinct workspace-session identities and proxy sets.
JJ proxies sharing a canonical backing repository use the same persistent request-lock file across those sets.
These locks coordinate trusted proxy mutations inside the runtime, not arbitrary host commands or source-file edits.
They do not replace the host-kernel launcher coordination above.
Never unlink or replace request-lock files during cleanup or restart; derive their identity from the canonical host JJ backing repository.
Mount the relevant locks only into trusted JJ services and include them in accepted authority, live-resource checks, VM bind preflight, and Landlock access.

== Trusted execution

The proxy starts from an empty environment and adds only manifest-declared or launcher-required fixed values.
It does not inherit credentials, agent forwarding, dynamic-loader variables, user configuration paths, pager or editor selection, or container-daemon access.

The proxy image contains every executable and source file needed by its command.
A trusted interpreter may read attacker-controlled code even from a `noexec` mount, so mounting the working tree `noexec` is only defense in depth.
For an interpreted repository tool, the immutable image carries the trusted startup snapshot of the program rather than invoking the mutable checkout's copy.

The launcher starts a proxy with its manifest `argv` as the fixed operation.
It does not expose a general-purpose shell, `docker exec`, alternate entrypoint, or arbitrary command API to the agent.

== Caddy authenticated egress <authenticated-egress-broker>

*Decision date:* 2026-09-14.

=== Selected topology and boundary

Zulip uses two launcher-owned containers: an unmodified, digest-pinned Caddy 2.11.4-alpine container and a minimal profile-helper container. They share only a private Unix-socket volume. The helper binds its socket there; it has no agent-facing listener. Only the helper receives the credential mount and any mutable refresh state. Caddy receives no credential files. The Zulip typed adapter remains a further separate application-boundary container in the Zulip trust domain.

Caddy owns HTTP parsing and framing, standard hop-by-hop handling, TLS verification, DNS dialing, fixed reverse proxying, streaming, method/path matching, request-size enforcement, request-header limits, and configured transport/server timeouts. It is not a forward proxy and never accepts a caller-selected origin. The helper owns session-token admission, credential reading, and generation of trusted authentication headers; it does not proxy HTTP application bodies.

For every application request, Caddy performs the normative helper exchange below. It never forwards the application body to the helper.

#table(
  columns: (1.2fr, 2.8fr),
  [*Field*], [*Normative contract*],
  [Transport], [HTTP over the private Unix socket; the helper has no TCP listener.],
  [Request], [`GET /admit`; no request body.],
  [Admission], [The original client `Authorization` value carries `Bearer <session-token>`. Its total value is at most 4096 bytes. The helper performs a constant-time exact comparison with the instance token.],
  [Metadata], [Before the exchange Caddy strips authority, forwarding, proxy-authorization, and profile-reserved fields while preserving the session-token `Authorization`; other safe client headers may remain.
  Caddy supplies original method and URI through fixed precheck headers.
  Caddy's complete request-header bound is 64 KiB; after standard-library parsing the helper enforces the same aggregate bound.
  The helper consumes only the token and method/URI context and ignores other headers without logging them.
  Logging of method/path context follows Readiness and observability below, not raw header or complete URI logging.
  Parser-level failures remain internal because Caddy normalizes every helper failure.],
  [Zulip success], [`204` with exactly `Authorization: Basic <value>` as a custom response header. The value must be nonempty.],
  [Wrong token], [`401`, `Content-Length: 0`, no body, and no custom response headers.],
  [Credential failure], [`503` for credential read, validation, or refresh failure, with `Content-Length: 0`, no body, and no custom response headers.],
  [Transport deadlines], [Caddy applies a 10-second Unix-socket dial timeout and, separately, a 30-second helper response-header timeout. Either failure is handled as local `503`.],
  [Credential deadline], [After successful admission, the helper uses one 30-second monotonic deadline for all credential reading, validation, and any refresh work. This is an internal work bound, not a combined complete-exchange guarantee.],
)

The Caddy configuration expands the authentication precheck rather than relying on `forward_auth` shorthand alone. A response matcher permits proxying only when the helper returned `2xx` *and* every profile-required header is present and nonempty. Caddy then replaces the stripped client fields with those helper values. Any other helper response, malformed success, timeout, or socket failure becomes a fixed local bodyless `401` or `503` with `Content-Length: 0`, no helper/custom headers, and no upstream application request. In particular, Caddy never begins sending the application body until this gate succeeds.

Flower R2 is excluded. AWS Signature Version 4 binds request material and must preserve per-use Keychain consent. R2 remains its dedicated per-launch relay until a separately reviewed signer preserves those semantics without disclosing credentials.

=== Fixed routes

The Zulip typed adapter remains the only agent/host application interface.
It accepts transcript, topic-list, and available-channel-list framed operations, constructs requests, paginates, serializes access,
enforces two-second pacing, honors bounded `429 Retry-After`, validates complete responses, and emits the existing schemas.
It calls its local Caddy at only three finite route families on the one launcher-admitted Zulip host:

- `GET /api/v1/messages` with the adapter-constructed bounded query
- `GET /api/v1/users/me/<numeric-user-id>/topics` with the adapter-constructed bounded query
- `GET /api/v1/streams?include_can_access_content=true` for available-channel listing

Channel listing returns only numeric channel IDs and names for content the account can access.
The adapter rejects servers that report the content-access filter unsupported; it does not fall back to an unfiltered listing.

Caddy has explicit matchers for those families and a non-proxying catch-all. The agent never receives a general Zulip HTTP endpoint. Host routing continues through the typed adapter, and the sandbox client never falls back locally.

=== Header policy

Caddy applies one explicit request-header policy before proxying:

- set upstream `Host` to the fixed configured upstream host
- strip incoming authority/profile fields and `Forwarded`, `Via`, every `X-Forwarded-*` field, and `Proxy-Authorization`
- strip client `Authorization` and every profile-reserved authentication/account field
- copy only the helper's fixed authentication/account fields after successful admission
- pass all other safe end-to-end headers unchanged; there is no per-route header allowlist

Caddy performs normal protocol hop-by-hop removal. Duplicate, malformed, connection-nominated, or protocol-forbidden headers cannot supply alternate authority. Response hop-by-hop fields are handled by Caddy; helper headers and credentials are never copied to downstream responses.

=== Timeouts, bounds, and completion

The immutable Caddy configuration sets a 64 KiB request-header maximum, 10-second header-read timeout, 300-second idle timeout, 10-second application-upstream dial timeout, and 60-second application-upstream `response_header_timeout`. The helper transport separately uses a 10-second Unix-socket dial timeout and 30-second response-header timeout. Zulip request bodies are absent because all three route families are `GET`; its typed request and query bounds remain adapter-owned. Container PID, memory, CPU, file-descriptor, and network bounds constrain each service.

Caddy preserves HTTP framing failures but does not decide protocol completion.
The repository-owned Zulip adapter reports success only after a complete bounded
response validates. Native Pi owns model transport and completion semantics;
those requests do not pass through Caddy.

Caddy and the helper do not retry application requests. Whether a remote mutation committed before cancellation may be unknown. Zulip's reviewed `429` behavior remains typed-adapter policy. Service, helper, credential, TLS, DNS, or upstream failure never triggers direct authenticated fallback.

=== DNS and network topology

Caddy performs ordinary DNS resolution and dialing for the single configured application upstream host. Its application egress uses a distinct lifecycle-owned ordinary network, separate from the agent-link network.

The Zulip static-credential helper has no egress network.

=== Readiness and observability

Readiness is entirely local and causes no upstream request, OAuth refresh, or persistent credential write. The launcher calls exact bodyless `GET /ready` with no query at Caddy using the instance session token; Caddy performs exact bodyless `GET /ready` with no query over the private socket, the helper validates token and local credential structure/readability without refreshing, and Caddy returns local `204`. The readiness route has no application-upstream `reverse_proxy` handler. Publication requires this Caddy-to-helper check for both containers, plus runtime identity and socket-volume attachment validation.

Caddy access logging is disabled.
Its default logger remains at `INFO` on standard error, but `http.handlers.reverse_proxy` is excluded because its error records can serialize trusted profile headers after admission.
Application and helper reverse-proxy failures therefore produce fixed client status classes and health effects but may not produce Caddy error records.
Remaining Caddy operational logs must not contain request metadata or sensitive values.

Logging acceptance applies to the launcher-owned Caddy/helper service interfaces, including Caddy-generated fixed-route helper exchanges.
For these exchanges, the helper logs decision, original method, query-free route path, result, and optional reason.
Method and path are JSON-escaped and truncated after 64 and 2048 characters respectively, with an ellipsis on truncation.
Methods paired with these fixed-route paths, including numeric route IDs, are permitted; numeric channel IDs are not treated as secrets.
The Zulip typed adapter logs only operation class, status, counts, duration, and bounded failure class.
Logs must omit raw precheck headers, query values, topic names, bodies, cookies, tokens, auth/account-header values, credential paths, arbitrary header dumps, refresh exchanges, and complete sensitive URLs.

=== Credential profiles

The Zulip helper constructs fixed basic authentication from its admitted identity. Helpers expose no template language, arbitrary header map, environment expansion, caller-selected account, credential path, or Keychain service.

All containers run non-root with read-only root filesystems, capabilities dropped, `no-new-privileges`, and explicit resource bounds. They receive no repository, outer-daemon socket, SSH agent, or ordinary home directory. Agent root cannot access the private socket volume or another sibling's mounts or networks.

=== Caddy provenance and pin

The only admitted Caddy dependency is Docker Official Image `caddy:2.11.4-alpine`. Dependency-update evidence resolves that tag and verifies the recorded OCI index and per-platform manifest/configuration descriptors. Runtime startup never resolves or pulls the tag: it pulls the selected platform-manifest digest, then verifies the chain from that manifest to its image configuration and runtime container image ID; startup inspection proves the derivation. The generated, mounted Caddy configuration has a separate content digest and is not part of the OCI image chain. The service implementation identity binds both the verified image chain and the independent mounted-configuration digest. Accepted-session metadata records the chain, configuration digest, and platform tuple, and join validation re-inspects them all. The tag is provenance input, never runtime identity. Floating tags, standalone release binaries, locally rebuilt images, package-manager builds, automatic upgrades, and third-party images are rejected. Installed provenance records OCI index `sha256:13ba145cba2f3e28fa801994876e4c086d1b95d5aa2a520a734765ffb6b12017`; linux/amd64 manifest `sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a` and configuration `sha256:af555904a0961945f16bb323a501457b13a4f7e9bde969b145b97da80b38ecbe`; and linux/arm64/v8 manifest `sha256:1172d4213087d3fc30bafc7ff2c2896180eb0c41ff7f75f315568fb36cabdcba` and configuration `sha256:6b08c1b9858ca9a7d99c1da13c3695081e0e604c6cf214ca26a7ce0e2c4fd9b4`. A Caddy upgrade or configuration change requires explicit pin/provenance capture, regression tests, and a new shared session.

=== Migration and removal

The 2026-09-14 Caddy migration removed the custom authenticated HTTP broker.
The 2026-10-27 Codex model-broker removal selects native host-Pi providers and
retains only the Zulip Caddy/helper pair and its typed adapter. Flower R2 keeps
its dedicated per-launch Keychain relay.

Old Codex session records are cleanup-only: no publication or new join may admit
them. Existing attachments must exit before owner-validated reset removes the
recorded Caddy/helper containers, socket volume, application and refresh networks,
and immutable configuration. Failed cleanup preserves recovery authority;
recovery must not resolve images, refresh OAuth state, or read model credentials.
Legacy single-container records retain their existing cleanup-only handling.
The launcher does not delete or migrate old dedicated credential files.

The agent's credential-free public network remains outside this reverse proxy.
Removing direct egress is a separate design.

=== Caddy acceptance checks

- Startup and join admit only Docker Official Image Caddy 2.11.4-alpine whose OCI index, platform-manifest, image-configuration, and runtime container image identities form the recorded chain; the service implementation identity separately binds the mounted Caddy configuration digest.
- Every credential domain has separately recorded Caddy and helper containers and private socket volume; credentials are visible only to its helper.
- Zulip Caddy accepts only the three typed-adapter route families; every configuration ends in a non-proxying catch-all.
- `GET /admit` over the private Unix socket receives no body; constant-time exact admission enforces the at-most-4096-byte bearer session token, and metadata stays within the 64 KiB header bound.
  Other headers are ignored without logging; method/path logging follows Readiness and observability.
- Helper transport uses separate 10-second Unix dial and 30-second response-header limits; after admission, credential reading uses one internal 30-second monotonic deadline, with no claimed combined complete-exchange deadline.
- Zulip helper success is exactly bodyless `204` with nonempty `Authorization: Basic`; wrong token is `401`, credential failure is `503`, and failures have `Content-Length: 0` with no custom headers.
- Expanded Caddy response matching requires `2xx` plus every required nonempty helper header before replacing client values and proxying; every other result returns fixed local bodyless `401`/`503` and sends no application body upstream.
- Caddy fixes `Host`, strips authority/profile/forwarding fields, copies only helper auth/account fields, and passes other safe end-to-end headers unchanged.
- Tests enforce 64 KiB headers, 10-second header read, 300-second idle timeout, 10-second upstream dial, and 60-second response-header wait; no test assumes a complete-body, total-response, or response-byte deadline.
- Repository tests verify that Caddy has one fixed Zulip upstream and no application retry policy, and that malformed upstream response framing is not turned into a successful complete transport. They do not claim to validate Responses SSE or JSON.
- Caddy application egress uses an ordinary, separately lifecycle-owned network.
- The Zulip helper has no egress.
- Readiness proves Caddy-to-helper admission locally through a no-upstream route and performs no refresh or persistent write.
- Caddy access logs and its header-bearing reverse-proxy error logger are disabled; this sacrifices per-request proxy diagnostics to prevent trusted profile-header disclosure.
  Logging acceptance for the launcher-owned Caddy/helper service interfaces and typed adapter follows Readiness and observability.
- Removed custom HTTP, DNS, header/framing, streaming, and response-limit code is unreachable and not retained as fallback.
- Flower R2 remains on its dedicated relay, including the lifecycle specification's existing connection-establishment retry blocker.

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
The privileged bridge remains bound to the validated repository; the shim resolves path-based agent inputs before sending the request.
Because git-bug does not discover repositories from `GIT_DIR` alone, its subprocess uses launcher-supplied `SANDBOX_GIT_DIR` as its working directory. Queue and workqueue paths remain anchored to the selected workspace, not that Git directory; the proxy does not rediscover host metadata with `jj` or fabricate `.git` in the workspace.

The editable Flower source supplies the unprivileged client rather than the launcher or proxy image.
Editing or bypassing it changes only the requests sent; server validation and metadata protection remain authoritative.

For `--body-file`, the shim reads the file with the agent's authority, sends the bounded contents in the request, and rewrites the argument to `--body-stdin` before privileged execution.
The proxy therefore never follows an agent-selected body path or reads a file visible only in its container.
An invocation that already uses `--body-stdin` forwards bounded standard input unchanged.
A direct socket request that still contains `--body-file` is invalid, so bypassing the shim cannot recover the privileged path-reading behavior.

The protocol rejects `bb bug push` and `bb bug raw` before execution.
Publishing refs remains a maintainer command outside the sandbox; the proxy receives neither network access nor push credentials, and the agent receives no write-capable Git credentials, writable SSH agent, or reusable provider token that could bypass the proxy through Git or a hosting API.
The Caddy authenticated-egress instances have no source-hosting publication route, so their bounded request authority does not grant publication authority.
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
Repository binds preserve filesystem identity between each authorized worktree and its resolved metadata.
The trusted launcher supplies `JJ_PROXY_REPO` as the active root and `JJ_PROXY_WORKSPACES` as a JSON array whose entries contain exactly
`root`, `git_dir`, `common_dir`, `jj_repo`, and `lock`.
Derive this set from the #link("launcher-interface.typ")[launcher workspace descriptions], deduplicating identical roots.
Validate it before readiness; guest cwd, selectors, and shared-store membership cannot add roots.
A fail-closed Landlock policy admits the authorized worktrees, resolved metadata, request locks, private configuration, socket directory, and trusted runtime files.
Mutation execution may write ordinary files and metadata in the authorized workspaces.
Inspection children apply a separate read-only policy and `--ignore-working-copy`, even for explicit inspection of an authorized root.
Protocol version 2 carries a physical absolute invocation cwd under `/src` in both modes.
The server derives mutation authority from exact resolved workspace roots, not cwd spelling or path-prefix membership.
Other `/src` siblings remain inspection-only; independent guest repositories remain native.
Execution is permitted only beneath `/trusted/bin`, giving the working tree the same effective `noexec` property under Docker and Podman without unsafe syscall bindings or a hard-coded kernel ABI.
The `bug` protocol is narrower than Jujutsu's grammar: it forwards one bridge subcommand, rewrites body input, rejects `push` and `raw`, and leaves issue-operation validation to the trusted bridge.

All mutation-mode JJ requests acquire the target backing repository's persistent lock before any author prehook or mutating command.
Hold it through command execution and applicable author reset, including requests without hooks and secure-config preparation at startup.
Distinct proxies sharing a backing repository serialize; independent repositories remain concurrent.
Hold at most one repository lock, never for the session lifetime or while waiting for another repository lock.
Lock wait and execution share a bounded request deadline within the client's response timeout.
A wait timeout or cancellation runs no hook or command; stop and reap timed-out children before releasing ownership.
Descriptor close or process death releases ownership; read-only inspection needs no mutation lock.
The #link("../../jj-proxy/design.typ")[JJ contract] owns target-scoped hooks, native cwd/fileset semantics, and unknown-outcome handling.

The generic manifest does not replace `jj-proxy`'s command-specific validation.
A future proxy command with caller-controlled arguments must define a complete accepted grammar and reject executable selection, alternate repositories, configuration overrides, and other privilege-crossing surfaces.

== Lifecycle

The #link("trusted-service-lifecycle.typ")[trusted-service lifecycle] owns planning, identity, readiness, publication, joining, cancellation, cleanup, and recovery across command proxies, Caddy authenticated-egress instances, and host capability relays.
This specification retains command- and protocol-specific authority: fixed execution policy, request validation, credentials, mounts, network access, serialization, retries, and outcome semantics.
A service-specific implementation must not duplicate lifecycle ownership or use generic lifecycle failure as permission to fall back to a more privileged path.

== Acceptance checks

- The agent cannot directly modify `.git`, `.jj`, external backing metadata, or `.agents/sandbox` through any alias in either writable checkout
- Ordinary files in the active workspace and launcher dotfiles remain writable; other source siblings remain inspection-only
- Exact trusted workspace roots select JJ mutation access; unlisted linked workspaces do not inherit authority from a shared store
- Distinct JJ proxies serialize complete mutation-mode requests, including hooks, on the same persistent backing-repository lock
- Independent repositories remain concurrent; the request lock does not promise coordination with arbitrary host writers or file edits
- The generic host router runs `bb bug` locally while it owns the host lock and uses the recorded runtime to reach the proxy while a sandbox launcher owns that lock
- Proxied reads and writes work without giving the agent access to `.git/git-bug` or queue control state
- A `git` built-in mount supports colocated and non-colocated Git-backed Jujutsu workspaces, including backing Git directories outside the selected worktree; Git-bug reads and writes the selected refs while queue and workqueue state stay in the selected workspace
- Unknown, duplicate, conflicting, or unsafe built-in mount declarations fail before startup; a missing Git backing store never falls back to a workspace `.git` path
- `--body-file` contents cross the proxy as bounded standard input, and the proxy never opens the supplied path
- `bb bug push` and `bb bug raw` are rejected by the proxy, and push remains a maintainer-only command
- The agent cannot publish refs through direct Git, SSH-agent, credential, or provider-API access
- The agent and agent root cannot read any authenticated-egress access token, refresh token, basic-auth component, refresh exchange, or credential store through files, environment, process inspection, logs, network responses, or the outer daemon
- Pi streams model requests through its fixed HTTP route, while Zulip clients use only the typed read-only adapter; neither receives reusable credentials
- Unknown methods, paths, origins, oversized request bodies, alternate authority, and client-supplied authentication fail closed; safe end-to-end headers otherwise pass unchanged
- Caddy rejects malformed targets and protocol-invalid framing and headers; its fixed upstream prevents callers from selecting arbitrary destinations
- Host Pi uses native model authentication; the guest receives no model credentials or provider overrides
- A route failure does not expose its credential or affect another credential-domain instance
- Caddy or profile-helper unavailability and authentication failure never fall back to direct authenticated provider access or mounting credentials in the agent
- An authenticated-egress session token remains available to validated joiners after the publishing launcher exits, fails after its Caddy service instance ends, authorizes only that accepted service, and cannot authenticate directly to an upstream provider
- Logs and diagnostics for the launcher-owned Caddy/helper service interfaces satisfy the permitted fields and sensitive-content exclusions in Readiness and observability
- Non-idempotent requests are not retried, and cancellation reports an outcome-unknown remote mutation where success cannot be established
- Passwordless sudo remains functional inside the agent without granting access to sibling containers or their mounts
- The agent cannot append arguments, choose another executable, alter mounts, inject environment variables, or redirect a command outside its trusted repository authority
- Modified working-tree copies of `bb.edn`, bridge source, git-bug, or proxy scripts do not affect trusted execution
- An invalid, ambiguous, unavailable, or wrong-platform resolver result fails before its consumer starts
- Resolver freshness, sharing, refresh, and capability omission satisfy the launcher interface's acceptance checks
- Joins reuse accepted configuration and images without running resolvers, even after sandbox configuration or source edits; existing agents, sockets, and services remain untouched
- `/reload` updates per-agent instructions, skills, and extensions without reloading sandbox configuration or shared proxies
- Loss of a command proxy or Caddy authenticated-egress instance reports request failures without terminating attached agents or falling back to local privileged execution or direct provider credentials
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
