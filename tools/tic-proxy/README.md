# TicGit command broker (default-off)

This is the selected host-side command broker, not a native TicGit server or an
OS sandbox. See `../codex-sandbox/spec/tic-proxy.typ` for governing authority and
outcome semantics, and [BUILD.md](BUILD.md) for pinned builds and installer input.
Its admitted native execution remains trusted code with the host user's process
permissions; argument validation does not contain arbitrary native-code bugs.

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
native revision, policy version, and SHA-256; launcher configuration must match.
Configuration and native authority are fixed for the process lifetime.

Startup verifies the native binding and configuration-free repository preflight,
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
and one version-one response. Both use four-byte big-endian byte lengths. The
application request is `{version,command,argv,stdin}` with fixed `command: "tic"`.
The client must write-half-close after its frame; the broker verifies EOF before
policy or execution, rejecting trailing bytes, duplicate/unknown fields,
unsupported versions, malformed JSON/UTF-8, and oversize input. Requests select
no endpoint, executable, cwd, repository, identity, namespace, or environment.
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
deadlines, overload, resets, lifetime shutdown, forced termination, and reaping.
Repository and policy/client suites are owned separately within this crate.
Readiness tests verify that absent databases remain absent and unsupported
repositories fail before publication.

The existing required write-half-close protocol makes a later graceful peer
full-close indistinguishable from its earlier FIN on ordinary TCP. Reset/HUP
cancellation and lifetime cancellation are tested; immediate cancellation on
**every** graceful disconnect is not established. Removing the application
backlog eliminates the reproduced stale queued-request execution, but does not
by itself resolve that protocol limitation. No alternate cancellation envelope,
wall-clock deadline field, or EOF relaxation has been introduced. This remains
an acceptance concern for governing-contract review, not a claimed guarantee.

Neither actual provider composition nor macOS execution is accepted by these
local Linux tests. Keep the capability default-off until those checks and all
remaining boundary review findings are resolved. Ordinary host `ti` remains
independent of broker/runtime availability.

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
