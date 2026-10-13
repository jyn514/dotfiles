= TicGit command proxy

*Status:* Draft design; not implemented.
The `tic` capability follows the existing `jj-proxy` pattern: admit a native argument vector, run the pinned CLI, and return its output.
One persistent service per Git common directory serves host `ti` and every opted-in worktree through one serial request loop.
Ordinary host `ti` therefore requires the accepted container runtime even when no sandbox is running.
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

A host invocation and an agent in another worktree connect to the same service, not separately owned proxies.
The trusted host launcher starts it on demand and keeps it after the final sandbox session exits.
Explicit store shutdown and maintenance are the only transitions back to native host administration.
This removes the native/proxy handoff, multi-proxy invocation lock, and index of workspace service owners.

Keep native `ti` rather than building a replacement ticket API around `ticgit-lib`.
Native TicGit owns ordinary option parsing, field validation, ticket-prefix resolution, filters, persisted data, and rendering.
In particular, `--markdown`, `--json`, and ordinary text output remain native behavior.
The proxy owns authority checks and generic token scanning, not an independently maintained TicGit grammar.

Use the same separation as `tools/jj-proxy/client`, `src/policy.rs`, and `src/main.rs`:
a forwarding client, a compact command policy, and a serial native-command server.
Reuse the generic sandbox transport and lifecycle, not Jujutsu-specific author updates, inspection routing, or execution permissions.
Do not introduce a shared proxy framework as a prerequisite.

== Native baseline and execution boundary

Build `schacon/ticgit` revision `d0bda85fa593e5d4488dd13af1216b0d2766d6dc`, version `0.3.1`, with its unchanged Cargo lockfile.
It selects `git-meta-lib` `0.1.10` and requires Rust at least `1.88`.
The relevant native owners are `commands/new.rs`, `commands/edit.rs`, `commands/mod.rs`, `commands/setup.rs`,
`session_state.rs`, and `git-meta-lib`'s `session.rs` and `db/mod.rs`.
An upgrade requires reviewing the admitted commands' file, subprocess, setup, and network effects, and regenerating grammar metadata.
Pin the toolchain and image through existing image resolution; do not install or update tools at runtime.

Select `tic` as an opt-in version 2 repository manifest command using the existing image binding.
Its fixed entrypoint is `tic-proxy serve`, with `workdir` set to `.` and `network` set to `false`.
The manifest selects agent access; the launcher acquires the store-scoped service instead of starting a workspace-owned instance.
Host setup installs the trusted `tic` service definition and image binding so host-first startup does not require a sandbox manifest opt-in.
Both entrypoints use the same trusted planner and existing image resolver; requests cannot supply service definitions or images.
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
Do not hand-maintain each family's ordinary flags, validate their values, or rebuild ordinary argv.
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

=== Generated grammar metadata

At image build time, compile a metadata extractor against the same pinned TicGit CLI definitions and locked Clap dependencies as native `ti`.
The extractor reads the built Clap command tree through its reflection APIs; do not scrape Rust source, help output, or shell completions.
A build-only companion target may compile the existing private CLI modules; native `ti`'s source and runtime behavior remain unchanged.
This integration depends on TicGit's internal source layout and must be reviewed when the native pin changes.
Generate command and option names and aliases, positional order, value arities, and all settings needed to classify tokens under the pinned parser.
Keep command admission and security-sensitive field selection in the separate trusted policy, not the generated grammar.
Do not reproduce ordinary value validators, required-field checks, or option conflicts in the scanner.

Package one generated artifact for the server, guest client, and host shim; do not maintain separate grammar descriptions.
Bind its schema and native-build provenance to the immutable image and load it once from trusted packaged data.
Requests cannot select or replace metadata, and runtime startup never generates it.
Generation failure or unsupported token-classification settings fail the image build without consuming stale or partial output.
Missing, malformed, unsupported, or mismatched packaged metadata fails startup rather than selecting a hard-coded fallback.

The security scanner distinguishes options, their values, and operands using this generated metadata.
The client uses the same token classification only to locate transported file inputs; server admission remains authoritative.
The scanner retains each token's original argv position and any attached-value span so file substitution changes only the file value.
It must account for native option aliases, attached values, short-option clusters, and `--` so those forms cannot bypass the checks.
A literal operand or option value is data, not another option; preserve its position and bytes.
Reject forms the scanner cannot safely classify rather than guessing.
This scanner checks authority and transported files, not ordinary flag conflicts, required targets, field values, or ticket existence.

== File input and protocol

The client locates native `-F PATH` and `--file PATH` forms to transport file contents; it does not decide command admission.
It reads the file in the guest, enforcing the payload bound incrementally, replaces its argument value with `-`,
and sends the contents in the request's `stdin` field.
Client input checks provide early failures and bound local memory use; they do not replace server validation.
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

The server decides whether the command admits file input and accepts payload only with exactly one admitted file option whose value is `-`;
other commands require empty `stdin`.
After decoding, the server enforces the argument count, individual and aggregate UTF-8 byte limits, and decoded payload UTF-8 byte limit
from #link(<tic-bounds>)[Bounds and uncertain outcomes] before staging files or spawning a native child.
The request-frame limit does not replace these decoded-input checks.
An empty transported file is valid transport input and reaches native validation unchanged.
Stage it as a mode-`0600` file in a private request directory, substitute that server-owned path, and preserve the contents.
Remove request-private files only after all native children stop.
Neither the wrapper nor the server parses the ticket body or recreates native Markdown rendering.

== Prepared store

The host initializes the store, performs required sync/import, and fully materializes TicGit project metadata before first use.
Initialization, upgrades, sync, import, serialization, and recovery require explicit coordinated shutdown of the store service.
Ordinary host ticket inspection and mutation instead use the service route below.

The service validates the store before endpoint publication, while the supervisor holds exclusive store creation coordination.
Read-only SQLite validation must include committed WAL state; the main database file alone is not the complete store.
Committed WAL left by an earlier service instance does not require a host checkpoint before normal startup.
Allow SQLite synchronization sidecars in protected metadata if needed for reading, but do not migrate, checkpoint, repair, or change ticket data.
Store preparation uses only the bounded preparation deadline.
Require SQLite `user_version` `1` and the initialized project `ticgit:schema-version` string `"1"`.
Reject unresolved promised TicGit project keys or missing referenced blobs: native bulk reads can otherwise silently omit tickets.
Check database and existing WAL/SHM files without following symlinks; require regular files with one hard link.
The generic mount validation rejects metadata indirection and agent-writable aliases.
Publish only after validation; no other service or host administrator may access the store during preparation.
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

== Persistent ownership and routing

Workspace-session identity remains the pair of canonical workspace root and Git common directory.
Other proxies remain workspace-session resources; TicGit alone uses the proposed `persistent-store` lifecycle scope.
Its sole logical identity is the canonical Git common directory, independent of any workspace or attached agent.
The generic supervisor owns one accepted service record, resource registry, endpoint publication, and cleanup for that store.
Workspace records reference its accepted owner and implementation identity rather than copying its endpoint or acquiring cleanup ownership.

=== Acquire or join

Use one private host state directory keyed by the canonical Git common directory.
Its service and recovery records survive host restart; a lost transient runtime directory cannot authorize a replacement writer.
Its stable host-kernel coordination lock serializes service creation, publication, explicit shutdown, and host administration.
Never unlink or replace this lock file.
The trusted host launcher, not the request server or guest client, acquires it and uses the generic supervisor:

- With generic discovery/recovery proving a fresh or fully cleaned store scope, plan and resolve one instance,
  durably record its fresh resource owner before effects,
  prepare the protected store, and publish its ready endpoint atomically.
  Newly created resources are registered before any database-using process starts.
- With a published instance, validate its store identity, owner, runtime, image, endpoint, and readiness before joining.
  Use its accepted definition and image; current worktree declarations cannot replace it or create a second instance.
- With preparing, stopping, failed, unavailable, malformed, or inconsistent state, wait within the existing acquisition deadline or fail.
  Never treat uncertain state or an unavailable runtime as permission to create another service.
  Owner-validated recovery must finish before a fresh instance can access the database.
  A missing record alone does not prove freshness; unaccounted store resources block startup and require recovery, not guessed deletion.

Accepted identity includes the runtime owner and policy, VM generation where applicable, native baseline, image,
configuration overlay, and lifecycle-state schema.
An incompatible runtime or worktree rejects only that join; it cannot start an alternative writer.
For sandbox attachment, register a generic endpoint dependency under store coordination before any guest mount is created.
The dependency reserves the accepted owner against shutdown while attachment is preparing, not just after workspace publication.
Finish acquisition and dependency registration before taking workspace-session coordination; never wait for workspace locks under store coordination.
Release store coordination before sending an application request.
Startup uses the existing bounded image-resolution and service-startup deadlines; the request exchange begins only after endpoint acquisition.
Cancellation or failure before publication joins startup workers and cleans that unpublished attempt through the generic supervisor.
Cleanup failure keeps its durable recovery record; cancellation after publication does not stop the persistent service.

A sandbox opting into `tic` must acquire this service before exposing its validated socket volume.
Several worktrees may attach concurrently without merging their other proxy sets.
Session exit, failed workspace startup after store publication, and final-holder cleanup release only that session's dependency and reference.
Release the dependency after its guest mount holders stop and workspace coordination is released.
They never stop a published store service or remove its resources.

=== Ordinary requests

The host `ti` shim reads host file inputs with the caller's authority and uses the same protocol and admission policy as agent requests.
It acquires or joins the store service even without a running sandbox or a manifest opt-in in the caller's worktree.
The trusted host router resolves and validates the endpoint from the single accepted store record.
Neither callers nor workspace records select endpoints, containers, images, or runtime owners.
Host `ti` always uses that route; there is no ordinary native-host execution path.
Runtime, connection, protocol, and native-command failures never trigger local fallback or replay.

The server retains JJ's sequential accept-and-execute loop, without an application queue or worker pool.
It runs one complete native operation, including reads and descendant cleanup, before starting another.
This sole execution owner replaces a multi-proxy invocation lock; SQLite transactions alone would not serialize whole native commands.
Do not start work after a lost connection or expired framing/admission deadline.
The client bounds its complete exchange, including socket waiting.
Serialization prevents overlapping operations, not partial mutations or uncertain delivery.

=== Explicit shutdown and administration

A trusted host stop-and-admin operation holds store coordination through dependency checks, admission revocation, administration, and child cleanup.
First check preparing endpoint dependencies and attached socket-volume holders through generic resource ownership.
If any remain, report the required detach and fail without stopping the service or admitting administration.
Otherwise disable endpoint acquisition, then ask the generic supervisor to stop the service and reap every database-using descendant.
Do not silently terminate unrelated workloads.
Failed cleanup, a surviving native child, or an unavailable runtime blocks host administration and replacement startup.
Server death alone never proves that its native child stopped.

Only after owner-validated shutdown may this operation invoke native host initialization, upgrades, sync, import,
serialization, or recovery with the human's authority.
The administrator child inherits the host coordination lock so wrapper death cannot admit another service while it writes.
Keep the store record non-routable through descendant cleanup; release coordination only after administration has stopped.
Do not restart the service automatically; the next ordinary request plans a fresh instance through normal acquisition.
Direct native `ti` outside this coordinated operation is unsupported, even when no agent is running.

The existing supervisor remains the only lifecycle and recovery owner; add this scope there, not a TicGit daemon manager or health monitor.
A failed published instance stays recorded until explicit owner-validated recovery; requests cannot restart or replace it in place.
Recovery preserves the database and WAL and never replays the failed operation.

== Bounds and uncertain outcomes <tic-bounds>

Fix the protocol bounds in the image:

- Request frame: 8 MiB; arguments: 128 tokens, 64 KiB each, 256 KiB aggregate decoded UTF-8.
- File payload: 1 MiB decoded UTF-8; stdout: 4 MiB; stderr: 256 KiB; response frame: 32 MiB.
- Framing, EOF, and admission: 10 seconds from connection acceptance; native execution: 30 seconds from child start.
- Server response delivery: 3 seconds from the start of response writing, using one absolute deadline for the complete frame.
- Client exchange: 45 seconds from connection attempt, including waiting, framing, response delivery, and cleanup.
- Child termination grace: 2 seconds before forced process-group termination and reaping; store preparation: 30 seconds.

The client deadline permits one accepted request's framing, execution, cleanup, and response delivery; contention can exhaust it before execution.
The server enforces its response-delivery deadline independently of the client.
A peer that does not read cannot block the serial loop indefinitely.
On delivery timeout or failure, close the connection and proceed only after all native children stop; the operation may already have mutated the store.
Preserve valid UTF-8 native output; invalid UTF-8 is an output failure, not silent replacement.
Completed native execution preserves exit status, stdout, and stderr.
Admission rejection returns `2` without spawning a child; transport/output/client-deadline failures return `125`, and execution timeout returns `124`,
when a response can be delivered.
Inside the sandbox, missing or failed proxy transport never falls back to a local CLI.
On the host, native execution is permitted only inside explicit coordinated administration, never as an ordinary route or failed-request recovery.

There is no automatic replay after any request byte is sent.
A native error, timeout, disconnect, or output failure can follow a partial or complete mutation.
Distinguish rejection before execution from a possibly executed operation; transport loss may prevent any diagnostic.
Do not claim rollback, add deduplication state, or recreate the database from serialized refs.
On execution failure requiring cancellation, terminate and reap the complete process group before the next command.
Cleanup preserves the database, WAL, and stable host coordination lock.
Store recovery stops the recorded service and every database-using descendant through its generic owner before host administration.
Inspect an uncertain `new` before a human decides whether to retry it.

== Acceptance evidence

Implementation must verify the boundary with disposable repositories and the actual pinned CLI:

- Compare client and direct-socket operations with equivalent native commands, including exact Markdown/JSON output,
  field changes, invalid values, ambiguous ticket references, and native file-body parsing.
- Generate metadata from the actual pinned CLI definitions and compare scanner classification with the native Clap parser without command dispatch.
  Exercise option aliases, attached values, clusters, `--`, option-looking data, and optional values such as `show --filter`.
  Verify original argv positions and attached-value spans, including exact preservation of non-file arguments during file substitution.
  Verify that a changed CLI option definition updates all grammar consumers through regeneration without scanner edits.
  Failed generation cannot publish an image or reuse stale metadata; missing, malformed, unsupported, or mismatched metadata fails startup.
  Verify authority/path/setup/sync rejection before spawning; ordinary option errors remain native.
  Missing targets fail natively against fresh state, even after another request selected a current ticket.
  Blank non-file titles, missing comment bodies, editor flags, and fileless editing invoke only the fixed failing editor.
  Blank transported titles fail native file parsing without an editor; both error paths leave ticket data unchanged.
- Prove that guest-only file input succeeds without opening caller-selected proxy paths;
  malformed/oversized frames fail, and client bypass does not bypass admission.
  Direct-socket requests exercise each argument-count, individual argument-byte, aggregate argument-byte, and decoded payload-byte bound
  at the limit and just above it while remaining within the request-frame limit.
  Over-limit decoded inputs fail before file staging or native child creation.
  Direct-socket file-input requests exercise disallowed commands, repeated file options, non-placeholder paths, and unexpected payloads.
- Submit a valid direct-socket request whose response exceeds socket buffering, then stop reading.
  Verify that the server closes the connection within its absolute response-delivery deadline and serves the next request after child cleanup.
  Partial response progress cannot reset the deadline; delivery failure never replays the operation.
- Prove read-only guest metadata through every visible alias, private configuration and execution restrictions,
  offline native execution, and unchanged code refs, host configuration, and working-tree files.
  Include malicious config includes, editor settings, and `.git-meta` inputs.
- Run simultaneous sessions in linked worktrees and issue host and agent requests from different worktrees.
  Verify one shared service and one active native operation, native output preservation, and no shared current-ticket state.
  Final session exit and failed workspace startup leave a published store service available to host requests.
- Race host-first startup against launches from multiple worktrees; prove one owner, one endpoint publication, and no duplicate writer.
  Reject incompatible runtime/VM generations, store aliases, images, and stale accepted-owner references before store access.
- Exercise acquisition during preparation, publication, endpoint loss, explicit shutdown, and abandoned-service recovery.
  Missing/corrupt existing state, surviving children, and unavailable runtimes must never authorize native fallback or replacement startup.
  Fresh state permits only normal planned startup, not local ticket execution; failed published instances require explicit recovery.
- Kill the server while its native child survives; prove new startup and host administration remain blocked until descendant cleanup.
  Race ordinary acquisition against stop-and-admin; prove admission revocation, inherited host-lock lifetime, no overlap, and no replay.
  Preparing attachments and socket-volume holders prevent unsafe cleanup; initialization/sync/recovery run only after complete service shutdown.
  Runtime-free host `ti` fails rather than bypassing the service.
- Test missing/incompatible/partially materialized stores, symlink/hard-link aliases, pending WAL, and native database errors.
  A fresh instance starts against a valid stopped store with committed WAL without requiring a host checkpoint.
  Startup and final-holder cleanup preserve unsynchronized ticket state without schema repair or deletion.
- Interrupt after a native field write and exceed output limits after mutation.
  Verify uncertain outcomes, no replay, process-group cleanup, and no execution after lost connections or expired admission deadlines.
- Real-container checks establish the generic mount, publication, join, network isolation, and recovery contracts.
