# TicGit command broker

This is the selected host-side command broker, not a native TicGit server or an
OS sandbox. See `../codex-sandbox/spec/tic-proxy.typ` for governing authority and
outcome semantics, and [BUILD.md](BUILD.md) for pinned builds and launcher cache resolution.
Its admitted native execution remains trusted code with the host user's process
permissions; argument validation does not contain arbitrary native-code bugs.

## Artifact resolution

The launcher selects one bundle containing the pinned native fork, host Rust
broker, and static Linux guest client. One relative manifest binds the artifact
hashes and current proxy source/native/policy/host/guest identity. Writable build
output is copied into a verified content-addressed cache outside guest-writable
mount sources before execution; there is no global `installed.json` or manual
installation prerequisite. A cache miss uses the ordinary pinned builder and
the host-only native-source setting, configured once with the normal Pi
`--set-tic-native-source` option; see
[BUILD.md](BUILD.md#normal-launcher-resolution). The cache does not change per-launch broker or relay ownership.

## Launcher interface

```
tic-broker --config /private/launch.json --lifetime-fd READ_FD
```

The strict configuration fields are `version`, canonical `workspace` (worktree
root, not an ordinary subdirectory), canonical `common_dir`, absolute canonical
`native_executable`, `native_sha256`, accepted `user_name`, `user_email`,
`namespace`, and fresh `token`. The JSON must be an owner-owned regular `0600`
file outside guest writable mounts. Installed executable and sibling native
manifest are trusted protected artifacts. The native manifest binds the complete
native revision, policy version, and publication-time SHA-256; launcher
configuration must match the binding metadata. Artifact bytes are verified at
build/cache publication, not repeatedly during warm startup or before native
requests. Protected paths outside guest-writable mounts supply runtime authority;
host-manual rewrites of the immutable cache are not a supported integrity check.
Configuration and native authority are fixed for the process lifetime.

Startup checks the native binding metadata and configuration-free repository preflight,
then binds only an ephemeral `127.0.0.1` port. It opens no SQLite database. Broker
stdout is **only** one JSON readiness line, bounded to 1024 bytes, with `version`,
`address`, `native_revision`, and `policy_version`. Startup failures go to stderr;
no token/request/environment is logged. Native stdout/stderr never share this
readiness channel. Native children receive piped stdin/stdout/stderr, no terminal
stdio, the accepted workspace cwd, a cleared environment, fixed Git identity and
namespace overrides, and per-request private HOME/XDG/state paths. Native stdin
receives exactly the normalized UTF-8 request bytes and then EOF.

The inherited lifetime read FD is marked CLOEXEC. Only its launcher owns the
write end; no unrelated child should inherit that write end. EOF stops admission,
closes the listener, cancels and reaps owned native children, joins request
workers, and removes private directories. There are no persisted PIDs, process
adoption, cross-broker writer registry, SQLite opens, or native descendant
watchdogs. Broker death is an unknown in-flight outcome, not replay permission.

## Request execution

One connection carries the strict typed `token`/`request` authenticated envelope
and one response. Both use four-byte big-endian byte lengths. The
application request is `{version,command,argv,stdin}` with fixed `command: "tic"`.
The request and response wire version is `2`; configuration, readiness, and
inspect-context schemas remain version `1`, as does command policy. The client
keeps its write side open while awaiting the response. The broker validates one
complete bounded frame without waiting for request EOF, rejecting duplicate or
unknown fields, unsupported versions, malformed JSON/UTF-8, and oversize input.
There is at most one native execution and one framed response, then close;
additional frames are never parsed or executed. Requests select no endpoint,
executable, cwd, repository, identity, namespace, or environment.
The broker validates native parsed arguments independently of the guest shim.

Request frame: 8 MiB; response frame: 32 MiB; stdout: 4 MiB; stderr: 256 KiB;
argv: 128 tokens, 64 KiB per token, 256 KiB aggregate decoded UTF-8. Admission has
one absolute 10-second budget from broker acceptance. Execution, including stdin
delivery and output collection, has 30 seconds from spawn. Delivery has 3 seconds.
Termination allows 2 seconds before forced kill and wait/reaping. The client has
one 45-second budget, beginning before input collection or connection. Native
exit/UTF-8 output are otherwise preserved; output is not terminal-escaped here.

At most eight request workers run concurrently. There is no application queue:
at capacity the listener accepts and immediately sends best-effort `125` without
executing, rather than waiting behind a child and granting a fresh deadline.
Native SQLite concurrency, contention, partial mutations, and interleaving retain
native semantics; the broker adds no command lock or transaction.

Admission rejection is `2`, execution expiry `124`, and transport/output/client
deadline failure `125` when deliverable. Incomplete/admission-deadline transport
failure is `125` without execution. A stalled response cannot reliably deliver
its own error status. Failures never fall back, reroute, replay, migrate stores,
or remove SQLite sidecars. Inspect outcomes before retrying creation/promotion.

## Evidence and unresolved acceptance

Rust integration tests exercise the real archived native fork against disposable
main/linked repositories and independent human writers, including concurrent
writes and shared history. Owned fake executables test environment/stdio,
framing/authentication/policy rejection, byte limits, blocked native stdin,
deadlines, overload, graceful FIN, lifetime shutdown, forced termination, and reaping.
Repository and policy/client suites are owned separately within this crate.
Readiness tests verify that absent databases remain absent and unsupported
repositories fail before publication.

Readable EOF, unexpected post-frame bytes, or a socket error observed before or
while executing cancel the exchange. Ordinary FIN therefore signals client
disappearance; the Tic client does not require abortive close. Cancellation can
race the single spawn or native completion and may leave partial or complete
mutations. Trailing input is terminal, not a second command; unlike the old EOF
admission protocol, it does not guarantee zero executions. A framed response
still requires response EOF. Shared bridge reset/half-close handling remains
available for its other consumers.

TicGit defaults on for new sessions; explicit `capabilities.tic: false` opts out.
Startup failure warns and lets Pi start without TicGit for that session, including
when `true` was explicit. No unavailable launch projects its endpoint, token,
client mount, or network attachment; the fixed guest entrypoint never searches
PATH for native TicGit. Its private read-only runtime bind covers accepted older
images too, without rebuilding or reselecting them. It is independent of Tic
artifact resolution and uses existing launch-owned scratch cleanup.
Once a broker is ready, request failures still fail
without fallback, replacement, or replay.
Ordinary host `ti` remains independent of broker/runtime availability.

### Acceptance checkpoint — 2026-10-25

One actual Linux/Docker launch through normal `pi` passed a bounded guest smoke in a fixture with matching Git/JJ roots.
It covered help, relative-file/stdin/guest-only-file creation, comment/show/list/history, Unicode ticket content and setup rejection.
This does not complete Linux provider acceptance; macOS composition remains untested.
Actual main/linked shared-store, sidecar, contention and overlapping-writer checks remain unfinished.
Frozen settings after host changes, remaining adversarial/input/bounds cases, provider lifecycle/failure cleanup and stopped-VM human use also remain unfinished.
The default-on selection does not close these gaps.

The actual host-built client differs from the local test bundle; expected fixture native/source metadata is not selected-build attestation.
The selected protected host cache manifest still needs inspection; see [BUILD.md](BUILD.md#disposable-normal-pi-acceptance).
No actual host-after startup timing or separate warm-launch report has been supplied.
A later manual ticket read is not warm-launch evidence, and local measurements with fake provider operations are not Pi/provider startup timings.

The final local unfiltered Rust broker group passed, but a complete current Cargo-target run is not established.
An optional replay stopped before compilation/tests because mutable Cargo outputs no longer matched the immutable final bundle.
The original greater-than-200-second broker-test stall remains unexplained.
A test-only whole-request-write deadline now bounds a demonstrated harness gap; later passing runs do not establish the historical stall's cause.
TUI reader evidence uses the prior native source, unchanged by the final metadata-only pin update, not a fresh final-artifact TUI replay.

## Trusted local repository inspection and configuration capture

The launcher first asks the installed broker to validate the accepted repository and identify the actual invocation Git directory.
This local operation is not reachable through the authenticated command protocol:

```
tic-broker inspect-context --workspace CANONICAL_INVOCATION_ROOT --common-dir CANONICAL_EXPECTED_COMMON
```

The producer runs pure repository preflight first, then uses the same configuration-free, explicit-root locator to return repository metadata.
It emits one JSON line with exactly six fields: `version`, `policy_version`, `native_revision`, `workspace`, `common_dir`, and `invocation_git_dir`.
All three returned paths are canonical; linked worktrees retain their private invocation Git directory and shared common directory.
The complete output is at most 64 KiB including its newline.
Failure publishes no JSON, and diagnostics use fixed bounded classes without paths, file contents, or environment dumps.

Inspection checks accepted local repository metadata, including local configuration safety, but does not load effective system/global/XDG configuration, follow host includes, or capture identity settings.
It does not open a gix repository, traverse object or ref graphs, open SQLite, or invoke Git, a shell, or an editor.
The locator reads only the explicit repository candidate's checked HEAD and layout controls; it does not search parents or follow HEAD's symbolic target.
Environment repository selectors and configuration-source overrides cannot redirect this metadata-only operation and are not a reason for it to reject otherwise supported roots.

The launcher then uses the returned invocation Git directory for fixed host `git config --get` queries of `user.name`, `user.email`, and `meta.namespace`.
Git owns normal configuration precedence, system/global/XDG and worktree sources, host includes, and environment configuration overrides.
It also owns conditional-include handling, including any ref reads those queries require.
Capture follows ordinary Git behavior; the producer does not implement configuration precedence or replacement-ref handling.

The launcher freezes the resulting identity and namespace for the launch.
Later native request execution still clears inherited configuration/environment, disables host system/global sources, and injects only the accepted frozen values.
Changing host settings after capture cannot silently change an active launch.
