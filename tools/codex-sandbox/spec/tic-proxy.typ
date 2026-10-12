= TicGit command proxy

*Status:* Draft design; not implemented.
The `tic` capability follows the existing `jj-proxy` pattern: admit a native argument vector, run the pinned CLI, and return its output.
Concurrent sessions in linked worktrees and ordinary host `ti` use remain available; only ticket invocations contend.
It does not replace Flower's `bug` bridge, migrate tickets, or authorize implementation.
The #link("proxy-design.typ")[proxy design] owns transport, mounts, and host routing;
the #link("trusted-service-lifecycle.typ")[trusted-service lifecycle] owns startup, joining, cleanup, and recovery.
This document owns TicGit-specific admission, store selection, and outcome semantics.

== Problem and selected approach

TicGit stores ticket changes in `git-meta.sqlite` inside the Git common directory, with adjacent WAL and SHM files.
An agent needs ticket operations without direct write access to that metadata.
For example:

```sh
ti new -F /tmp/ticket.md --tags cleanup --markdown
ti show TICKET_ID --markdown
ti comment -t TICKET_ID -- 'The retained relays are outside this issue.'
ti close TICKET_ID --markdown
```

The guest client reads `/tmp/ticket.md`, sends its bounded contents with the arguments, and substitutes a file-input placeholder.
The trusted server stages the contents privately, substitutes its own path, and runs native `ti new`.
Native TicGit parses the title and description and produces the Markdown output.
The proxy returns that output and the native exit status; it never opens the guest-supplied path.

Keep native `ti` rather than building a replacement ticket API around `ticgit-lib`.
Native TicGit owns ordinary option parsing, field validation, ticket-prefix resolution, filters, persisted data, and rendering.
In particular, `--markdown`, `--json`, and ordinary text output remain native behavior.
The proxy owns authority checks, not a second implementation of the CLI grammar.

Use the same separation as `tools/jj-proxy/client`, `src/policy.rs`, and `src/main.rs`:
a forwarding client, a compact command policy, and a serial native-command server.
Reuse the generic sandbox transport and lifecycle, not Jujutsu-specific author updates, inspection routing, or execution permissions.
Do not introduce a shared proxy framework as a prerequisite.

== Native baseline and execution boundary

Build `schacon/ticgit` revision `d0bda85fa593e5d4488dd13af1216b0d2766d6dc`, version `0.3.1`, with its unchanged Cargo lockfile.
It selects `git-meta-lib` `0.1.10` and requires Rust at least `1.88`.
The relevant native owners are `commands/new.rs`, `commands/edit.rs`, `commands/mod.rs`, `commands/setup.rs`,
`session_state.rs`, and `git-meta-lib`'s `session.rs` and `db/mod.rs`.
An upgrade requires reviewing the admitted commands' file, subprocess, setup, and network effects.
Pin the toolchain and image through existing image resolution; do not install or update tools at runtime.

Select `tic` as an opt-in version 2 repository manifest command using the existing image binding.
Its fixed entrypoint is `tic-proxy serve`, with `workdir` set to `.` and `network` set to `false`.
Declare the existing Git mount:

```json
{"builtin":"git","proxy":"read-write","agent":"read-only"}
```

The guest receives protected read-only Git metadata and the read-only socket-volume mount at `/run/sandbox-proxies/tic/`.
The proxy receives the existing read-only repository view, no writable working tree, and private temporary storage.
Neither side receives an outer daemon socket through this capability.
The proxy receives no host HOME, credentials, or SSH agent.
Its immutable image contains the server, native `ti`, required fixed runtime binaries, and the conventional generic forwarding client.
Use a read-only root filesystem and fail-closed filesystem and execution restrictions following the JJ pattern,
but permit writes only to the accepted Git metadata and request-private storage, not `.jj` or ordinary files.
Executable lookup never uses the working tree.

The launcher supplies the canonical Git common directory as `SANDBOX_GIT_DIR` through its existing Git built-in mount.
The server fixes native cwd there and verifies that native store discovery selects the accepted database.
Requests cannot choose cwd, repository, environment, executable, or configuration.
Invoke native `ti` directly, with no terminal, closed child stdin, an empty inherited environment, and fixed private HOME/XDG paths.
Use a fresh, initially absent `TICGIT_STATE_FILE` in each private request directory.
Native current-ticket writes never select a later request's target.
Without an explicit target, native `resolve_ticket()` reports that no current ticket exists before changing tickets.
Do not duplicate that target check in proxy admission.

Fix `GIT_EDITOR` to a trusted executable that exits unsuccessfully with a noninteractive-use diagnostic.
The pinned `soe` library gives this variable highest precedence and propagates editor failure rather than trying its built-in editor.
Its external-editor path uses `sh`; supply a fixed trusted shell with only the fixed editor command and private temporary path as inputs.
Caller text never becomes shell code.
Admitted commands capture editor input before writing ticket changes.
Let native TicGit report missing/blank non-file titles, missing comment bodies, and editor requests through this failing editor.
Blank transported titles instead fail native file parsing without invoking an editor.
Do not reproduce those argument checks in the proxy.
Keep child stdin closed and provide no terminal; requests cannot override the editor or environment.

At startup, snapshot accepted authorship, repository format, and `meta.namespace` into a private read-only configuration overlay.
Exclude includes, remotes, hooks, signing commands, filters, credential helpers, and other executable or network configuration.
The overlay never changes host configuration.
`meta.namespace` selects serialized metadata refs; it does not partition the SQLite database.
Initially admit only SHA-1 repositories with the files ref backend.

== Compact command policy <tic-admission>

As in `jj-proxy/policy.toml`, a trusted declarative policy lists allowed command prefixes and forbidden security-sensitive options.
Load it once from the immutable image; requests cannot select or edit it.
The server validates direct socket requests, not merely wrapper-produced requests.

Admit these native command families:

- Inspection: `list`, `show`, `history`, `recent`, `stats`, and `next`.
- Mutation: `new`, `edit`, `comment`, `state`, `claim`, `close`, `tag`, `assign`, `priority`, `points`, `milestone`,
  `code`, `depends`, `subissue`, `meta`, and `spec`.

An empty argument vector means native `list`.
Admit the native aliases `ls`, `dep`, and `status` with the corresponding command policy.
The accepted grammar is the pinned native CLI restricted by this policy and the authority checks below.
Do not enumerate each family's ordinary flags, validate their values, or rebuild ordinary argv.
Pass admitted arguments unchanged except for transported file inputs.
Native TicGit rejects unknown or conflicting ordinary options and renders completed results.

The command policy excludes `init`, `setup`, `update`, `pull`, `push`, `sync`, `import`, `tui`, `agent`, `checkout`,
`users`, `mine`, `views`, `writeup`, and `review`.
Initialization, upgrades, sync, import, serialization, and recovery remain coordinated host operations.
Help and version use packaged information without opening the store.
Help describes the admitted subset, request-private current-ticket state, and file-based rather than interactive editing.

Command-specific inspection rejects `new --checkout`, named list views, writeup targets,
repository/configuration/executable overrides, and file options not replaced by the transport placeholder.
Admit transported file input only for native `new`, `edit`, `meta`, and `spec` as described below.
Missing targets and editor-triggering forms are native errors, not proxy admission failures.

The security scanner must distinguish options, their values, and operands using the pinned CLI's token rules.
It must account for native option aliases, attached values, short-option clusters, and `--` so those forms cannot bypass the checks.
A literal operand or option value is data, not another option; preserve its position and bytes.
Reject forms the scanner cannot safely classify rather than guessing.
This scanner checks authority and transported files, not ordinary flag conflicts, required targets, field values, or ticket existence.

== File input and protocol

The client accepts native `-F PATH` and `--file PATH` forms for the admitted file-input commands.
It reads the file in the guest, enforcing the payload bound incrementally, replaces its argument value with `-`,
and sends the contents in the request's `stdin` field.
For `-F -`, read bounded guest stdin instead.
The placeholder is a proxy convention, not native TicGit stdin support.

Use the existing framed JSON transport with protocol version `1` and exactly these request fields:

```json
{"version":1,"command":"tic","argv":["new","-F","-","--markdown"],"stdin":"TITLE\n\nBODY\n"}
```

Require `command` to equal `tic`.
The response has exactly `version`, `exit`, `stdout`, and `stderr`.
Apply the generic framing, field validation, EOF, process cleanup, and fail-closed rules.
Reject NUL bytes in arguments.
No request field names a host file or selects execution authority.

The server accepts payload only with exactly one admitted file option whose value is `-`; other commands require empty `stdin`.
An empty transported file is valid transport input and reaches native validation unchanged.
Stage it as a mode-`0600` file in a private request directory, substitute that server-owned path, and preserve the contents.
Remove request-private files only after all native children stop.
Neither the wrapper nor the server parses the ticket body or recreates native Markdown rendering.

== Prepared store

The host initializes the store, performs required sync/import, and fully materializes TicGit project metadata before first use.
Initialization, upgrades, sync, import, serialization, and recovery require all services for this store stopped through the generic supervisor.
Ordinary host ticket inspection and mutation instead use the routing contract below.

Each proxy validates the store under the same runtime invocation lock used by requests.
Read-only SQLite validation must include committed WAL state; the main database file alone is not the complete store.
Another live proxy's WAL does not require stopping that session or running a host checkpoint.
Allow SQLite synchronization sidecars in protected metadata if needed for reading, but do not migrate, checkpoint, repair, or change ticket data.
Lock contention during startup uses only the bounded preparation deadline.
Require SQLite `user_version` `1` and the initialized project `ticgit:schema-version` string `"1"`.
Reject unresolved promised TicGit project keys or missing referenced blobs: native bulk reads can otherwise silently omit tickets.
Check database and existing WAL/SHM files without following symlinks; require regular files with one hard link.
The generic mount validation rejects metadata indirection and agent-writable aliases.
Release the validation lock after checking the store; later operations take it again.
Protected mounts and the host-administration restriction preserve file identity and store compatibility between requests.
Later sidecars stay inside the protected directory.
Do not duplicate the native schema with a table/column/index catalogue or require a full integrity scan at startup.
Other database failures use native diagnostics; preparation does not promise to detect all damage.
An absent, uninitialized, unsupported, or incompletely materialized store requires host repair, not automatic recreation.

Blocking the `setup` command is insufficient: native `open_store()` calls `auto_setup_if_needed()` even for ordinary operations.
Run in the common Git directory so working-tree `.git-meta` is outside native cwd.
Reject any `.git-meta` entry there before publication, including symlinks.
The immutable runtime contains no `git-meta` command helper.
Configuration isolation and disabled networking are additional controls; local-URL setup is not considered safe.
Readiness validates the prepared store and policy and binds the socket; it never runs a mutating native probe.

== Invocation locking and host routing

Workspace-session identity remains the pair of canonical workspace root and Git common directory, as in the existing launcher.
Linked worktrees share one database but keep independent sandbox sessions and proxy endpoints.
The common-directory store index below does not replace workspace-session identity or merge their proxy sets.
Use two existing coordination patterns for different purposes:

/ Runtime invocation lock: Serialize complete native operations, including reads, across every proxy for the store.
Use one stable `tic-proxy.lock` file in the protected Git common directory, opened without following symlinks and validated as a regular file
with one hard link.
Before opening the store or spawning native `ti`, acquire a nonblocking exclusive advisory lock.
Contention returns `125` with a store-busy diagnostic and no native child or ticket changes from this request.
Do not queue or automatically retry that lock attempt.
Use a lock whose ownership survives descriptor inheritance, such as `flock`, not a process-owned lock released when the server dies.
The child inherits the locked descriptor and retains it through execution; the parent retains its copy through descendant cleanup.
A crashed server cannot release exclusion while its native child continues writing.
Never unlink or replace the lock file, including on session cleanup.

/ Host admission and discovery: Key a private host runtime directory by the canonical Git common directory, not the worktree.
Its stable host-kernel coordination lock protects launcher registration, host route selection, and inactive-store local execution.
A launcher-owned, atomically updated store index contains references to generic service-owner records,
not copied endpoints or a second lifecycle state machine.
Create its empty initialized form under host coordination only after generic discovery/recovery proves the store inactive.
Keep its schema and store identity durable; do not delete it on final cleanup.
The launcher registers each reference under that lock as its first adapter step in `preparing`, before any store access,
then releases host coordination while the service prepares and runs.
Remove it only after the generic supervisor proves that owner's database-using services and children stopped.
Cleanup failure retains the reference; stale or uncertain ownership requires generic recovery.
This is not a lifetime exclusive lease: multiple workspace sessions may register and remain active.

For the first version, all registered proxies for one store must use the same accepted runtime owner,
VM generation where applicable, pinned native baseline, and underlying invocation-lock file.
Reject an incompatible runtime before it accesses the store, not another worktree merely because it has a live session.
Container locks are not assumed to coordinate with native host processes or another VM/kernel.
SQLite transactions alone do not serialize whole multi-step ticket operations.

The host `ti` shim reads host file inputs with the caller's authority and uses the same request protocol.
Discover active services even if the caller's worktree does not currently declare `tic`; accepted service records, not current manifests,
authorize the active route.
Extend the existing host router's discovery to all `tic` service references for the Git common directory:

- If a published service is available, validate its generic owner, accepted image, store identity, and endpoint, then route there.
  The selected server applies the same admission policy and runtime invocation lock as for agent requests.
  Any valid endpoint for that store is sufficient; do not attach the host caller to another workspace's other proxies.
  Release host coordination before waiting for the proxy response; later endpoint loss is a request failure, not permission to execute locally.
- If services are preparing, stopping, unavailable, or recovery-owned without a usable endpoint, wait within the existing routing deadline or fail.
  Runtime, transport, store-busy, and native-command failures never trigger local fallback or another-endpoint replay.
- Run native host `ti` locally only after complete discovery and owner-validated recovery establish that no service or surviving child can access
  the store.
  Retain the host coordination lock through local execution and child cleanup; the native child inherits it so wrapper death cannot admit startup
  while that child writes.

Missing, corrupt, or inconsistent discovery state is not evidence of inactivity.
Do not wait for workspace locks or run generic startup, cleanup, or recovery while holding store host coordination.
Release it for recovery, then reacquire it and repeat discovery before permitting local execution.
Registration and local execution use the same host lock, so a new proxy cannot start between the idle check and a host mutation.
The router uses generic lifecycle records as execution authority; the index only locates them and does not supervise resources.
Native host `ti` invoked outside this shim bypasses coordination and is unsupported while proxies may access the store.
No new daemon or request-wide transaction is introduced.

Each proxy retains JJ's sequential request loop, without an application queue or worker pool.
Do not start work after a lost connection or expired framing/admission deadline.
The client bounds its complete exchange, including socket waiting.
The store lock prevents overlap across endpoints, not partial mutations or uncertain delivery.

== Bounds and uncertain outcomes

Fix the protocol bounds in the image:

- Request frame: 8 MiB; arguments: 128 tokens, 64 KiB each, 256 KiB aggregate decoded UTF-8.
- File payload: 1 MiB decoded UTF-8; stdout: 4 MiB; stderr: 256 KiB; response frame: 32 MiB.
- Framing, EOF, and admission: 10 seconds from connection acceptance; native execution: 30 seconds from child start.
- Client exchange: 45 seconds from connection attempt, including waiting, framing, response delivery, and cleanup.
- Child termination grace: 2 seconds before forced process-group termination and reaping; store preparation: 30 seconds.

The client deadline permits one accepted request's framing, execution, and cleanup; contention can exhaust it before execution.
Preserve valid UTF-8 native output; invalid UTF-8 is an output failure, not silent replacement.
Completed native execution preserves exit status, stdout, and stderr.
Admission rejection returns `2` without spawning a child; transport/output/client-deadline failures return `125`, and execution timeout returns `124`,
when a response can be delivered.
Inside the sandbox, missing or failed proxy transport never falls back to a local CLI.
On the host, local execution is permitted only by the inactive-store routing check, never as recovery from a failed request.

There is no automatic replay after any request byte is sent.
A native error, timeout, disconnect, or output failure can follow a partial or complete mutation.
Distinguish rejection before execution from a possibly executed operation; transport loss may prevent any diagnostic.
Do not claim rollback, add deduplication state, or recreate the database from serialized refs.
On execution failure requiring cancellation, terminate and reap the complete process group before the next command.
Cleanup preserves the database, WAL, and stable lock file.
Store recovery stops all associated services through their generic owners before coordinated host administration.
Inspect an uncertain `new` before a human decides whether to retry it.

== Acceptance evidence

Implementation must verify the boundary with disposable repositories and the actual pinned CLI:

- Compare client and direct-socket operations with equivalent native commands, including exact Markdown/JSON output,
  field changes, invalid values, ambiguous ticket references, and native file-body parsing.
- Exercise option aliases, attached values, clusters, `--`, and option-looking data.
  Verify authority/path/setup/sync rejection before spawning; ordinary option errors remain native.
  Missing targets fail natively against fresh state, even after another request selected a current ticket.
  Blank non-file titles, missing comment bodies, editor flags, and fileless editing invoke only the fixed failing editor.
  Blank transported titles fail native file parsing without an editor; both error paths leave ticket data unchanged.
- Prove that guest-only file input succeeds without opening caller-selected proxy paths;
  malformed/oversized frames fail, and client bypass does not bypass admission.
- Prove read-only guest metadata through every visible alias, private configuration and execution restrictions,
  offline native execution, and unchanged code refs, host configuration, and working-tree files.
  Include malicious config includes, editor settings, and `.git-meta` inputs.
- Run simultaneous sessions in linked worktrees and issue host and agent requests from different worktrees.
  Verify one active store operation, pre-execution store-busy failures, native output preservation, and no shared current-ticket state.
- Prove that a server crash leaves its live native child holding the invocation lock, and child cleanup permits the next operation.
  Reject another runtime/VM generation or a different lock-file alias before store access.
- Exercise host routing during preparation, publication, endpoint loss, final-holder cleanup, and abandoned-service recovery.
  Missing/corrupt index state, surviving children, and unavailable runtimes must never authorize local fallback.
  Race an inactive host invocation against proxy startup; prove inherited host-lock lifetime, no overlap, and no request replay.
  Initialization/sync/recovery require every associated service stopped, not just the caller's workspace session.
- Test missing/incompatible/partially materialized stores, symlink/hard-link aliases, pending WAL, and native database errors.
  A second proxy starts against a valid live store with committed WAL without requiring a host checkpoint.
  Startup and final-holder cleanup preserve unsynchronized ticket state without schema repair or deletion.
- Interrupt after a native field write and exceed output limits after mutation.
  Verify uncertain outcomes, no replay, process-group cleanup, and no execution after lost connections or expired admission deadlines.
- Real-container checks establish the generic mount, publication, join, network isolation, and recovery contracts.
