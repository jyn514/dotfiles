#set page(paper: "a4", margin: 2.2cm)
#set text(size: 10.5pt)
#set par(justify: true)
#set heading(numbering: "1.")

= Prompted R2 Keychain relay for sandboxed local CI

#emph[Status:] Implemented in dotfiles and Flower, September 12, 2026; live R2 upload remains untested. \
#emph[Owners:] `tools/codex-sandbox` owns relay lifecycle and transport; Flower owns local CI policy and Woodpecker invocation. \
#emph[Consent evidence:] The disposable access-key item prompted for two consecutive successful reads, denial, and a successful read after denial; jyn confirmed that Always Allow remained unselected.
On September 12, jyn waived the remaining manual checks and authorized implementation.
Cancellation, secret-key prompts, lock/unlock, terminal restart, and production ACL equivalence remain unverified.

== Problem

Flower's local Woodpecker runner executes inside an untrusted Linux container. The R2 credentials live in macOS Keychain with confirmation required for each read. The container cannot invoke `/usr/bin/security`, and the current sandbox exposes no Keychain proxy.

Injecting credentials when the container starts would remove per-use consent and leave reusable credentials available throughout the session. A generic host-command proxy would grant a much broader authority than local CI needs.

The relay must therefore make each credential retrieval an explicit host-mediated operation, show the Keychain confirmation UI, and fail closed when the host, user, or transport refuses access.

== Goals

- Let `bb test ci` request Flower's two R2 credentials from a macOS host while running inside the sandbox.
- Preserve Keychain's confirmation prompt for every requested item.
- Keep credentials out of process arguments, repository files, generated YAML, logs, diagnostics, and persistent proxy state.
- Keep the proxy capability fixed at sandbox startup and specific to Flower's R2 service and account names.
- Treat denial, cancellation, missing items, unsupported hosts, timeout, and relay failure as "warn and skip upload," not CI failure.
- Preserve explicit `R2_ACCESS_KEY` and `R2_SECRET_KEY` environment variables as the highest-precedence local override.

== Non-goals

- Prevent approved sandbox code from observing credentials after the host returns them. Woodpecker runs in the sandbox, so this cannot be guaranteed without moving Woodpecker or the upload itself to the host.
- Provide arbitrary Keychain lookup, generic host command execution, secret enumeration, secret creation, or secret mutation.
- Share runtime capabilities with the Codex authentication sidecar, editor relay, Agent Podman relay, or repository metadata proxies.
- Change hosted Woodpecker secret handling.

== Threat and trust model

The agent container, its root user, repository code, and local Woodpecker process are untrusted. The macOS launcher and the new relay are trusted. Keychain and its configured item access controls are the consent authority.

The human approves or rejects each Keychain read. Approval authorizes disclosure of that one item to the requesting sandbox session. It does not establish that the downstream process is benign. The prompt should identify `/usr/bin/security` under the current Keychain configuration; the relay cannot truthfully claim that macOS authenticates Woodpecker as the caller.

The design protects against silent background retrieval, cross-session socket reuse, arbitrary service or account selection, accidental diagnostic disclosure, persisted plaintext, and fallback to direct host access. It does not protect credentials from malicious code already running in the approved sandbox after disclosure.

== Selected architecture

Add a `HostKeychainBridge` beside the existing `HostEditorBridge` in `tools/codex-sandbox`.
Use a host TCP listener, isolated per-launch link and egress networks, a restricted `socat` relay container, an allowed-peer set installed after relay startup, and a 256-bit session token.
Keep each bridge's listener, token, relay container, networks, limits, and environment variables separate.
Reuse `create_relay_network` and the launcher's resource cleanup paths, registering Keychain resources separately.
The current `prepare_gateway` and `start_gateway` combine editor and Podman transport; they are not a standalone editor-relay lifecycle to reuse.
Reuse the editor's framing convention, but keep Keychain authentication, admission, deadlines, and cancellable reads in its own request handler.
`HostEditorBridge` handles requests synchronously, allows an unbounded editing phase, and tears down editor panes; extracting a shared bridge framework is not required for this change.

The guest sends a fixed operation, `flower-r2/read`. It supplies no Keychain service, account, executable, command, or destination parameters. The host maps the operation to:

```text
service: dev.jyn.flower.r2
accounts, in order: access-key, secret-key
command: /usr/bin/security find-generic-password -s SERVICE -a ACCOUNT -w
```

The host returns both credentials together under the lifecycle rules in @request-lifecycle.
Flower consumes the socket response internally as described in @flower-client.

== Boundary declaration

/ Keychain state: macOS Keychain is the sole persistent credential owner and writer. Neither the relay nor Flower writes Keychain items.

/ Relay policy: `tools/codex-sandbox` is the sole owner of operation names, fixed Keychain selectors, request authentication, deadlines, and endpoint lifecycle.

/ Local CI policy: Flower is the sole owner of credential precedence, warning-and-skip behavior, temporary pipeline transformation, and Woodpecker child-environment construction.

/ Publication: retrieving credentials is not publication. R2 publication begins only when the Woodpecker upload step sends an object and retains its existing success or failure semantics.

/ Representations: raw passwords exist as Keychain values, host-process byte buffers, one framed response, guest-process byte buffers, and Woodpecker child-environment values. Redacted status values are separate projections and must never retain the raw strings.

/ Identity: a request is identified by relay protocol version, operation `flower-r2/read`, the private relay address, allowed relay peer, and constant-time-checked 256-bit session token. Repository paths, current directory, and ambient account names do not select authority.

/ Recovery: there is no durable transaction to recover; @flower-client owns unavailable outcomes and the no-retry policy.

== Components

=== Host relay

A small host-native process should:

- bind an ephemeral host port, authenticating allowed peers and the session token before reads;
- authenticate the session capability before any Keychain request;
- accept exactly one versioned operation with no caller-selected payload;
- invoke `/usr/bin/security` with a scrubbed environment and fixed argv;
- capture stdout privately, cap it to a small credential-sized limit, and remove one trailing line ending;
- enforce the deadlines and child cleanup in @request-lifecycle;
- protect credential material according to @secret-handling;
- return the response defined by @relay-protocol.

The relay must not accept shell text, arbitrary argv, environment additions, Keychain paths, service names, account names, or a flag that disables confirmation.

Each bridge admits at most one connection from request receipt through child cleanup and response delivery.
The accept loop continues while that connection is active and immediately closes excess connections without reading their payloads, spawning handlers, or queuing credential requests.
Use a bounded listener backlog of one; transport rejection maps to unavailable in Flower.
Admission is per bridge, not a host-wide prompt lock.
This bounds concurrent work and prevents an application queue of prompts; it does not prevent an authenticated guest from submitting fresh requests after completion.

=== Launcher integration

`codex-sandbox` should declare this as a host bridge reached through a restricted relay container, not as a sibling command-proxy container. At startup it should:

+ enable the bridge only on macOS when `/usr/bin/security` exists;
+ create separate private link and egress networks through `create_relay_network`, start the host listener, then start a restricted `socat` relay with all capabilities dropped, no-new-privileges, a read-only filesystem, and explicit PID, memory, and CPU limits;
+ inject only `CODEX_SANDBOX_KEYCHAIN_ADDRESS` (the relay's numeric IPv4 link address and port) and `CODEX_SANDBOX_KEYCHAIN_TOKEN` into the agent container;
+ install the relay's link and egress addresses into the host listener's peer allowlist before accepting requests;
+ record capability availability, protocol version, relay PID, and lifecycle owner without recording secret values;
+ register relay containers and networks with the launcher's cleanup paths, preserving resource ownership checks and recovery records; when the attached session ends, stop the Keychain listener and active child, join its thread, then remove its container and networks;
+ fail closed if any relay resource, peer identity, token, or protocol version is incomplete or belongs to another launch.

A joining session gets its own capability and consent requests. It must not inherit another session's successful credential response.

=== Flower local CI client <flower-client>

Implement the socket client inside Flower's local CI runner, with this credential precedence:

+ complete explicit environment credentials;
+ the internal socket client when `CODEX_SANDBOX_KEYCHAIN_ADDRESS` is configured, with failure terminal for this invocation;
+ direct macOS Keychain lookup when Flower itself is running on macOS outside the sandbox;
+ unavailable.

Partial explicit environment credentials remain incomplete: warn and skip upload without consulting another source.
The socket client connects only to the configured numeric IPv4 address, avoiding DNS resolution outside its deadline, reads `CODEX_SANDBOX_KEYCHAIN_TOKEN`, and validates the complete exchange against @relay-protocol before returning credentials as an internal value.
A missing token, malformed response, timeout, uncertain transport outcome, connection failure, or `unavailable` response warns and removes `upload-artifacts` from the temporary pipeline without failing CI or falling back to direct Keychain access.
Flower discards failed exchanges and never retries automatically, because another request can produce another consent prompt.
Successful credentials pass through `WOODPECKER_SECRETS` only in the Woodpecker child environment, subject to @secret-handling.

== Protocol <relay-protocol>

Reuse the editor bridge's framing convention: a four-byte unsigned big-endian length followed by one UTF-8 JSON object.
Each admitted connection accepts one request and attempts one terminal response; admission rejection and transport failure may close the connection without a response.

The request is complete when its declared frame length has arrived; the host does not wait for EOF before authenticating and reading Keychain.
The guest keeps both socket directions open until the response is complete and sends no further bytes.
Throughout credential reading, the host monitors the request socket: EOF, including a write-half-close, means cancellation; any additional byte means protocol failure.
Either event terminates the active child and prevents subsequent reads once detected.
TCP cannot establish that no bytes will arrive later, so rejection of extra bytes is not a pre-prompt guarantee and cannot undo a prompt or response already issued.
The host closes the connection after its terminal response; Flower validates one response frame followed by EOF within its overall deadline before using credentials.

The request object has exactly these fields and types:

```text
{"version": 1, "token": STRING, "operation": "flower-r2/read"}
```

A successful response is exactly:

```text
{"version": 1, "status": "ok", "access_key": STRING, "secret_key": STRING}
```

A non-success response is exactly:

```text
{"version": 1, "status": "unavailable"}
```

Set strict bounds: request at most 4 KiB, each credential at most 4 KiB after UTF-8 encoding, and response at most 12 KiB. Reject unknown or missing fields, non-string credentials, empty credentials, trailing bytes, wrong versions, invalid UTF-8, oversized frames, and partial EOF. Compare the token in constant time.

A replay is simply another consent request: the bridge holds no nonce cache and Keychain must prompt again. The private relay topology, peer allowlist, and session token prevent cross-launch use; the human prompt remains the final disclosure authority.

== Consent and request lifecycle <request-lifecycle>

Each Keychain item remains configured as "Confirm before allowing access."
Read access-key before secret-key, potentially producing two prompts.
Failure of either read ends credential retrieval; return both values only after both succeed, otherwise discard any value already read.

Detection of a guest disconnect cancels the active child and prevents subsequent reads.
Check for cancellation before spawning each child; a disconnect racing with spawn can still produce a prompt before detection.
Use monotonic deadlines: five seconds for the request frame, 120 seconds per Keychain read, and five seconds for response delivery, all capped by a 250-second overall host deadline.
That overall deadline covers request receipt through serialization, delivery, and cleanup; phase budgets do not extend it.
Flower's 255-second overall deadline covers connection through response EOF and socket cleanup.

Launch each `security` child in a new process group.
On detected disconnect, protocol failure, timeout, or shutdown, send `SIGTERM`, allow up to two seconds within the remaining overall budget, then send `SIGKILL` if necessary and reap the child.
Release admission only after child cleanup, socket closure, and timer cleanup; never resume credential reads after failure.

== Credential handling and diagnostics <secret-handling>

Keep plaintext out of repository files, generated YAML, and persistent relay state.
Do not serialize credentials as shell assignments, process arguments, or line-oriented `KEY=VALUE` text.
Zero mutable buffers where practical; Python strings, subprocess pipes, JSON values, and process environments cannot guarantee complete erasure.

Allowed host logs:

- relay start and stop;
- session identifier in the launcher's existing redacted form;
- protocol version and operation name;
- lifecycle status and elapsed time;
- non-secret failure classification, such as denied, cancelled, missing, unsupported, timeout, or failed, when supported by observed evidence;
- child exit classification, not child stdout or raw stderr.

Host failure classification is best-effort: retain an observed reason when available, otherwise report unavailable.
Do not build a classifier solely to distinguish denial, cancellation, and missing items for logs.

Allowed guest diagnostics:

- relay unavailable or incompatible;
- artifact upload skipped.

Forbidden everywhere:

- credential values or hashes;
- successful response frames;
- `WOODPECKER_SECRETS` contents;
- command lines containing credentials;
- Keychain stdout or unrestricted stderr;
- debug dumps of process environments or relay traffic.

== Rejected alternatives

/ Startup environment injection: rejected because credentials remain silently available for the whole container lifetime and no per-use confirmation occurs.

/ Mounting Keychain files or host home directories: rejected because it grants broad host state access and does not reproduce macOS Keychain authority inside Linux.

/ Generic `security` command proxy: rejected because arbitrary selectors and output modes expand the capability beyond Flower R2.

/ Reusing the Codex authentication sidecar: rejected because model-provider OAuth ownership and R2 publication have different principals, consumers, rotation, and failure policy.

/ Returning preapproved credentials from a long-lived cache: rejected because it weakens every-request consent. The relay may not cache successful values across requests.

/ Running all local CI on the host: viable but rejected for this change because it abandons the sandbox's reproducible toolchain and broadens host execution substantially.

== Verification

=== Host relay tests

- Exact operation succeeds only through an allowed relay peer with the correct session token.
- Arbitrary operation, payload, selector, argv, environment, oversized frame, duplicate field, and protocol version are rejected before spawning `security`.
- Mocked success reads accounts in order and returns both only after both succeed.
- First-item failure prevents the second invocation.
- Second-item failure returns no first-item value.
- Every failure response contains only `version: 1` and `status: unavailable`, regardless of the host's diagnostic classification.
- A complete request with both socket directions open starts reading without waiting for EOF.
- Stalled and partial request frames, malformed JSON, and stalled response delivery hit their declared deadlines.
- Extra request bytes detected during either read fail the request, terminate the child, and prevent subsequent reads; extra response bytes cause Flower to discard the credentials.
- Guest write-half-close is cancellation, including before the first read and between reads.
- Excess connections during an active request close without additional handlers or children; none becomes a deferred credential request after denial or completion.
- Disconnect detected before the first read, between reads, and during either read prevents subsequent reads and terminates the active process group; a disconnect racing with spawn still cleans up the child.
- A child that ignores `SIGTERM` receives `SIGKILL`; every terminal path reaps children, closes sockets, releases timers, and joins handler threads.
- Logs and errors remain free of canary credential values on every path.
- Session teardown removes relay resources and invalidates the token.

=== Launcher tests

- macOS startup publishes the relay; unsupported hosts omit it without weakening other proxies.
- Joined and restarted sessions cannot reuse stale endpoints or capabilities.
- Relay readiness and teardown follow existing launcher ownership and fail-closed conventions.
- Cleanup registration preserves Keychain resource ownership checks and recovery records; stopping the Keychain bridge leaves the editor/Podman gateway running, and stopping that gateway leaves the Keychain bridge running.
- Generated container arguments expose endpoint metadata but no credentials.

=== Flower tests

- Complete environment values bypass both relay and direct Keychain lookup.
- Partial environment values do not mix sources.
- Sandbox relay precedes direct macOS lookup.
- Configured relay metadata selects the internal socket client without an executable lookup; missing tokens and connection failures skip upload without direct Keychain fallback.
- Response EOF is required; trailing bytes, partial EOF, and missing EOF discard credentials within the deadline.
- `unavailable` and transport failure warn and remove the upload step without failing CI; unknown statuses are rejected as malformed responses.
- Successful values remain absent from argv, temporary YAML, diagnostics, and snapshots.
- The Woodpecker child alone receives `WOODPECKER_SECRETS`.

=== Manual macOS acceptance

In an owned test sandbox, run `bb test ci` with environment credentials absent. Verify two confirmation prompts, successful timing upload, immutable object prefix, and no credentials in process listings, generated files, terminal output, or relay logs. Repeat with denial at each prompt and confirm CI completes while upload is skipped. Finally end the sandbox and confirm the endpoint and relay process are gone.

== Implementation slices

The consent evidence and maintainer waiver above govern these slices.

+ Define the two-outcome protocol and Keychain request handler with mocked `security`, using the editor's framing convention; no launcher or Flower change.
+ Wire the separate Keychain bridge through existing network-creation and resource-cleanup primitives, adding endpoint publication, capability generation, readiness, and unsupported-host behavior.
+ Add the guest client and protocol conformance tests, still unused by Flower.
+ Update Flower credential discovery to prefer the relay inside the sandbox while retaining direct macOS lookup outside it.
+ Perform manual prompted success, denial, cancellation, timeout, disconnect, and teardown validation on macOS.

Each slice must be independently testable and fail closed. Do not combine the initial relay with a generic secret-service abstraction.

== Manual consent validation

Run `python3 tools/codex-sandbox/tests/r2_keychain_consent_probe.py` in an interactive macOS terminal.
It owns a disposable Keychain with dummy values and empty trusted-application lists, and asks the observer to confirm each dialog.
Its password is `r2-probe-password`; choose Allow once, never Always Allow.
Repeat from a restarted terminal session and verify that the production items have equivalent confirmation settings.
The probe reports observations for its disposable items; it does not certify production ACLs.

To finish the manual validation, confirm that every `/usr/bin/security find-generic-password` invocation prompts, including after approval, denial, cancellation, Keychain lock/unlock, and terminal restart.
Approval of one item must not silently authorize later reads.

If macOS cannot reliably preserve every-read confirmation, stop implementation.
Silent caching and startup injection remain unacceptable.
