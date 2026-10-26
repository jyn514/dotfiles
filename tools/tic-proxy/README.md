# TicGit from a Pi sandbox

The TicGit proxy lets an agent run `ti` inside a Pi sandbox while native TicGit reads and writes tickets on the host.
For example, a guest `ti list` asks a host-side broker to run the approved native command and return its output.
The patched native TicGit uses the Git common directory's `git-meta.sqlite`, so main and linked worktrees share tickets.
An ordinary human `ti` command uses that same store independently of Pi, the broker, or a running VM.

SQLite stays on the host rather than being opened through the VM's shared filesystem.
The broker gives the guest selected ticket operations without giving it write access to protected Git metadata or a general host shell.
TicGit itself remains a local CLI, not a Ticket API server.

## Start using it

Start Pi normally on the **host**:

```sh
pi
```

By default, when no matching cached bundle exists, the launcher fetches the pinned native source and builds the native fork, broker, and Linux guest client.
It copies the verified bundle into a protected cache outside guest-writable mounts; no manual TicGit installation is required for the proxy.
Later launches reuse a matching cache without needing the native source checkout or network access.
See [build and cache setup](BUILD.md#normal-launcher-resolution) for prerequisites and source-resolution details.

Inside the guest, use ordinary commands:

```sh
ti --help
ti list
```

Guest help shows only the admitted commands and options.
The proxy supports ticket inspection and explicit, noninteractive ticket and writeup changes.
Setup, synchronization, reviews, interactive UI, and editor launches remain outside the guest interface; ordinary host commands remain independent.
The [proxy specification](../codex-sandbox/spec/tic-proxy.typ) defines the full admitted set under “Command and option admission.”

File input belongs to the guest, even though the command runs on the host.
For example, with `ti edit TICKET -F draft.md`, the guest client reads `draft.md` relative to its current directory and sends its contents as stdin.
Replace `TICKET` with the ticket to edit.
The host receives `edit TICKET -F -` and those UTF-8 bytes, not a pathname to open.
Use `-F -` to read caller stdin; the specification describes the full file-input contract.
Input-loading failure does not cause a host-file read instead.

TicGit defaults on for new sessions; explicit `capabilities.tic: false` opts out.
If its build, repository checks, or broker startup fail, Pi warns and starts without TicGit for that session, even if `tic: true` was explicit.
The guest `ti` guard then reports unavailable; it never searches for native TicGit as a fallback.
`/cd` prepares the destination's container images and TicGit binaries before leaving the current session.
An unsupported TicGit context warns rather than making Pi startup fail.
For a disposable acceptance fixture, follow the [Git/JJ root checks](BUILD.md#disposable-normal-pi-acceptance) before running any `ti` command.

## Failures and trust

A request failure never triggers fallback, broker replacement, or automatic replay.
A lost response, timeout, or disconnect can leave a partial or complete mutation: cancellation is not rollback.
Inspect tickets before retrying creation or promotion, or you may create duplicates.
Each connection permits at most one native execution; trailing input cancels the exchange but can arrive after that execution has begun.
Cleanup does not remove SQLite sidecars or interfere with independent human writers.

The broker checks commands independently of the guest client and fixes the host repository, executable, identity, and namespace for the launch.
It runs the native command without a shell, with bounded stdin/output, no terminal, and private per-request UI state.
Native TicGit still owns parsing, ticket validation, storage, concurrency, and transaction behavior.
The broker adds no command lock or whole-command transaction.

The native fork and its dependencies are trusted code running with the host user's process permissions.
Argument filtering is not OS confinement and does not contain arbitrary native-code vulnerabilities.
The [governing contract](../codex-sandbox/spec/tic-proxy.typ) owns the repository restrictions, execution bounds, transport, and lifecycle requirements.

## What has been verified

**The actual Linux functional smoke passed; full acceptance remains incomplete.**
The latest run through ordinary host `pi` verified that the guest could read and comment on a ticket created from the host's linked worktree.
Four host and four guest ticket creations succeeded; all eight tickets and their creation histories were read back from both worktrees and checked in the shared SQLite store.
Host-native `ti` also created a ticket after the owning Pi session exited.
The recorded protected host cache manifest identifies the selected build, and the guest client's hash matches that manifest.

A second ordinary Pi launch used an unsupported TicGit repository configuration.
Other guest tools remained usable, while `ti` reported unavailable with no endpoint, token, or database created.
Both Pi sessions exited successfully.
An earlier Linux/Docker smoke also covered help, relative-file/stdin/guest-only-file input, Unicode content, comment/show/list/history, and setup rejection.

These functional checks do not prove native-child cleanup, in-flight cancellation, strict writer interleaving, or SQLite sidecar identity.
Frozen settings after host configuration changes, human use with the VM stopped, and macOS composition remain unverified.
The remaining malformed-input and resource-limit cases have not all been exercised through a real provider.
No actual Pi startup timing after the optimization, or separate warm-launch report, has been supplied.
See [the acceptance procedure](BUILD.md#disposable-normal-pi-acceptance) for the repeatable workflow and its limits.

### Test evidence limits

Local Rust tests exercise shared tickets and independent writers; fake executables test request restrictions, transport limits, cancellation, and shutdown.
The final broker test group passed, but the full test suite was not rerun against the final bundle: an optional replay stopped before testing because mutable build outputs no longer matched it.
An earlier broker-test stall exceeding 200 seconds remains unexplained.
A test-only timeout now bounds a known harness gap, but does not explain that stall or establish a runtime defect.
TUI reading was tested with equivalent native source before the final metadata-only pin update, not by rerunning the final artifact.

## Launcher and contributor reference

[BUILD.md](BUILD.md) owns pinned builds, bundle/cache validation, test commands, and actual-provider acceptance setup.
The [proxy specification](../codex-sandbox/spec/tic-proxy.typ) owns the exhaustive command and wire contracts, exit statuses, limits, and outcome semantics.

Two local broker entrypoints serve the launcher, not guest callers:

```sh
tic-broker inspect-context --workspace CANONICAL_INVOCATION_ROOT --common-dir CANONICAL_EXPECTED_COMMON
tic-broker --config /private/launch.json --lifetime-fd READ_FD
```

`inspect-context` validates protected local repository metadata and returns canonical repository paths without loading effective host Git configuration or opening SQLite.
The launcher then uses the returned invocation Git directory for ordinary host `git config --get` queries of `user.name`, `user.email`, and `meta.namespace`.
Git supplies its normal configuration precedence, includes, and worktree handling during that capture.
The launcher freezes those values; native requests clear inherited configuration and receive only the accepted values, so later host setting changes do not alter an active launch.

The broker publishes one bounded JSON readiness line on stdout and listens on an ephemeral loopback port only after its checks pass, without opening SQLite.
The owning launcher holds the lifetime pipe's write end.
EOF stops admission, cancels and reaps owned native children, and removes private request resources; it leaves ticket data and other launches alone.
If the broker dies during a request, its outcome is unknown, not permission to replay it.
