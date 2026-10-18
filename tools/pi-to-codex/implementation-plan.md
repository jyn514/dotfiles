# Pi-to-Codex import implementation plan

## Objective and scope

Add `pi-to-codex FILE_OR_SESSION_ID [--cwd DIRECTORY]` to create a resumable Codex thread from one Pi session's selected branch.
Preserve conversation text, completed tool calls and results, and the current compacted model context.
Use history injection, then append native visibility and display records after the owned app-server exits and let Codex rebuild its index metadata.
The implementation does not depend on the import receipt/startup changes.

Non-goals: importing every branch, restoring pre-compaction messages to Codex's UI, transferring live workers or extension state, automatic model requests, and automatic launch of the destination session.
Accept an explicit Pi JSONL path or exact session UUID through Pi's public discovery API.
Existing paths take precedence; missing and ambiguous IDs fail before publication.

## Current behavior and evidence

- [`bin/codex-to-pi`](../../bin/codex-to-pi) converts mostly conversation text in the opposite direction; it does not provide an invertible tool-call representation.
- [`libexec/codex-import.py`](../../libexec/codex-import.py) repairs existing Codex sessions through `thread/list`; it neither converts Pi messages nor creates new threads.
- [`tests/chat-history/inspect-pi-session.mjs`](../../tests/chat-history/inspect-pi-session.mjs) checks Pi imports through its session loader and tree APIs.
- [`tools/codex-sandbox/tests/session_side_test.ts`](../codex-sandbox/tests/session_side_test.ts) demonstrates installed-SDK loading, compaction, selected branches, and paired tool calls.
- Installed Pi 1.1.0 publicly exports `SessionManager` and `convertToLlm` from its package root.
  `buildSessionContext()` selects the branch and retained context; `convertToLlm()` renders compaction summaries, branch summaries, shell executions, and custom messages.
  `SessionManager.open()` can migrate and rewrite older session files, so it must open a private copy.
- The Codex 0.162.1 probe accepted Pi's historical `read` call and paired result, plus its compaction summary, in the next request captured by a local mock provider.
  Subsequent native probes confirmed durable import without a new turn, but injection alone leaves `has_user_event=0` and the picker hides it.
  Appending one event for an existing imported user message, then resuming and closing the thread, makes it visible without a model request.
  This makes the picker entry visible but leaves UI turns empty.
  Native `task_started`, `item_completed`, and `task_complete` records supply the paginated UI transcript without duplicating model context.
  Temporary probe sources and artifacts are under `/tmp/pi-codex-probe.py` and `/tmp/pi-codex-probe-results`; reproduce required evidence in repository tests rather than depending on those files.
- The installed `ThreadResumeParams` schema labels `history` as `[UNSTABLE] FOR CODEX CLOUD - DO NOT USE`.
  This is an intentional dependency on an unsupported Codex interface, not a stable import API.

## Decision ledger

| Status | Decision |
| --- | --- |
| decided | Import one selected branch with tool calls and compaction; use Codex history injection. |
| decided | Preserve picker and transcript visibility through the hybrid approach: append a native user event and canonical display records after the creating writer exits, then resume and close through Codex. |
| conservative default | Accept a file path and use its recorded cwd unless `--cwd` overrides it. Fail before publication if the destination directory is unavailable. |
| conservative default | Use destination Codex configuration for the model and permissions; never copy Pi provider credentials, model selection, or permissions. |
| decided | Omit saved Pi system prompts with a diagnostic; use Codex instructions. |
| decided | Shorten tool-call IDs exceeding 64 characters without collisions, updating their results consistently. |
| conservative default | Create a fresh thread on each invocation; print its returned ID and a resume command. Do not add deduplication or a provenance database. |
| conservative default | Reject unmatched/duplicate tool-call IDs and unsupported message content before starting Codex; never silently truncate the selected context. |
| conservative default | Images and opaque provider reasoning/signatures are outside the first version's preservation contract. Reject unsupported images; report omitted provider reasoning metadata. |
| decided | Do not submit a new user turn to force persistence or visibility; verify the hybrid import after owned processes exit. |
| unresolved, non-blocking | The mock-provider probe does not establish hosted-provider acceptance. State that limit unless separately verified. |

## Boundaries and invariants

Pi owns the source format, migrations, branch selection, and compaction semantics.
Load its installed package through the public root export, following the `PI_PACKAGE_DIR` and installed-package pattern in `session_side_test.ts`; do not import private SDK source paths or use the older locked test SDK accidentally.
Node and the installed Pi SDK suffice; no new runtime dependency is planned.

The importer owns a private source snapshot, message conversion, and sequential temporary app-server processes.
The original session must remain byte-for-byte unchanged, including on migration, rejection, cancellation, and failure.
Codex creates the destination rollout and owns all index writes.
The importer appends only visibility and UI display events in its fresh, unpublished thread, after the creating writer exits.
Pi's selected context is the authority for both model history and displayed items.
Only injected response items supply model context; UI records must not add or duplicate context.
Completed historical dynamic-tool items preserve call order, arguments, output, and success status without replaying tools.
Display turns group retained messages at user-message boundaries; their synthetic IDs do not claim original turn identity or timing.
Do not generate whole rollouts, edit SQLite, call `codex-import`, stop a daemon, or modify other sessions.
Preserve compatibility at both persisted-data boundaries by using their owning consumers and testing against installed versions.

## Design and lifecycle

1. Validate arguments, SDK availability, source readability, and destination cwd.
   Copy the source into a private temporary directory with `cp`, verify it with `cmp`, and reject a changed or truncated snapshot using the standard JSON parser before loading it.
   Open only that copy with `SessionManager.open()` so migrations cannot rewrite the original.
2. Obtain `buildSessionContext()` and pass its messages through public `convertToLlm()`.
   Preserve its rendered summary and retained messages instead of reconstructing compaction entries or restoring discarded history.
   This is a session-file context import; it does not execute extensions to reproduce transient live prompt hooks.
3. Convert the resulting context to Codex response items in occurrence order.
   Map user and assistant text to their corresponding message content types.
   Map tool calls to `function_call` with JSON arguments and results to `function_call_output`, preserving pair identity and result order even when parallel calls finish out of order.
   Preserve successful text output verbatim; encode failed results as a JSON output string containing `isError: true` and their original text content.
   Do not replay tools, rename Pi tools to Codex tools, merge identical messages, or invent signed reasoning records.
   Reject unsupported blocks and invalid call/result relationships before creating a destination thread.
4. Start `codex app-server --stdio`, initialize the protocol with the capabilities required by the installed schema, and submit `thread/resume` with `history` and the resolved cwd.
   Supply a fresh random placeholder for the required `threadId` field so it cannot rejoin an existing running thread; use the returned thread ID as authority.
   Do not submit `turn/start` during import.
5. Close the creating server, validate the returned rollout's thread ID, paginated header, and monotone ordinals, and append one user event for the first imported user text plus canonical display turns and items.
   Resume by ID through a second server and close it so Codex persists the derived display metadata.
   A third server verifies the ID in database-only listing and verifies displayed item identity and cardinality through `thread/read`; no model request is made.
   Close and reap only owned servers, remove the private snapshot, and then report success.
   Stdout identifies the created thread and gives `codex resume ID`; stderr carries progress and diagnostics.
   Failure before injection leaves no destination state.
   If injection may have succeeded, report the returned ID when known and explain that retrying can create another thread; do not automatically replay an ambiguous request or delete Codex-owned files.
   Preserve the primary error if cleanup also fails.
   Cancellation stops the owned child with bounded escalation and removes temporary files without touching the source, shared daemon, or another session.

## Implementation steps and logical commit

1. Reproduce hybrid import durability and picker visibility in an isolated native-CLI test.
   Inject history, exit the server, and use a second server to read/list/resume the returned ID.
   A subsequent test-only turn against a local mock provider must contain the original imported context.
   Keep rejection of unknown visibility-record formats in the importer and its failure tests.
2. Add `tools/pi-to-codex/pi-to-codex.mjs`, with a small importable conversion function and CLI orchestration in the same owner.
   Add `bin/pi-to-codex` as a symlink, following `bin/codex-archive-old`; avoid a general app-server framework or refactoring unrelated import work.
3. Add `tools/pi-to-codex/tests/pi_to_codex_test.mjs` using Node's existing test runner and the installed Pi SDK.
   Register it through `tests/native/test_native_pi_to_codex.py`, following existing `run_native_suite` adapters so `dev/test` discovers it.
4. Add `tools/pi-to-codex/README.md` for usage, supported content, unstable API/version requirements, error recovery, and import-versus-archive limits; link it from `tools/README.md`.
   Review `install.conf.json` for command exposure; change bootstrap mappings only if the existing bin installation does not cover the symlink.
   Sandbox-image packaging is outside the initial host command's scope.

Land behavior, tests, adapter, command link, and documentation together as one commit: **Import selected Pi sessions into Codex**.
No preparatory shared-client extraction is justified by this change.

## Verification

Run tests through `dev/test-environment` with installed Pi dependencies, including the new native adapter.
Use SDK-created sessions and a real Codex binary with an owned local mock provider; do not access production sessions or make paid model requests.

| Acceptance case | Required observable result |
| --- | --- |
| Import without a new turn, then exit/reopen | Returned ID remains indexed and resumable; next mock-provider request contains imported context. |
| UI transcript after reopen | Native history API returns completed turns with retained text occurrences and historical tools, including arguments, output, and success status. |
| Selected branch, branch summary, multiple compactions | Imported context matches Pi's finalized context; abandoned branches and dropped messages stay absent. |
| Repeated identical text and parallel calls/results | Occurrences retain their order and cardinality; every result still references its own call. |
| Failed result, Unicode text, escaped/nested arguments | Error status, text, and argument values survive conversion. |
| Truncated source, image block, unmatched/duplicate call IDs | Clear nonzero error before any destination thread is created; source remains unchanged. |
| Legacy source requiring migration | Only the private copy is migrated; original bytes remain identical. |
| Protocol rejection, early EOF, cancellation, failure after injection | Owned resources are cleaned up, partial publication is reported, and no automatic duplicate retry occurs. |
| Other Codex session running; repeated invocation | Existing session remains usable; each successful invocation returns a distinct new thread ID. |

Add bounded generated conversion cases for JSON argument values, repeated text, and permutations of completed parallel results.
Check pairing and occurrence invariants independently of the converter, retaining deterministic failing inputs; no new property-testing dependency is needed.
Ordinary integration tests must cover the actual public command and a fresh process, not only an imported conversion function.
