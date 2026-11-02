# Explicit evidence collection

Status: proposed design; no implementation or dependency installation is authorized
by this document. The tool names and interaction are selected; the report-input
contract, storage layout, and executor integration remain open.

## Problem and scope

A successful command does not establish that it tested the required behavior.
Raw tool output is useful evidence today, but interpreting it repeatedly costs
context and can lose distinctions between execution failure, test failure,
skipped cases, and missing reports.

Automatically parsing every command would introduce another failure: a plausible
but incorrect summary could make the model more confident than the output warrants.
Instead, collection is explicit and the caller declares the expected format.

The capability belongs to the harness and works across repositories. Projects
keep their existing commands and build systems. The initial surface is two model
tools and one human command—not a test framework, grading system, or trial manager.

## Model and human interfaces

The intended model interface is:

```text
collect_evidence(bash_command="pytest -q", format="pytest")
show_evidence(id="e42")
```

`collect_evidence` executes exactly the supplied command through the configured
backend, retains its output and execution metadata, and attempts the declared
interpretation. It returns an evidence ID and a compact result. It does not guess
a format, add silent flags or environment changes, or retry execution. Command
effects remain subject to the same authorization as ordinary `bash`.

The example does not promise that `pytest -q` emits a supported report. If the
required input is absent, a valid result is:

```json
{
  "id": "e42",
  "execution": {"kind": "exited", "exit_code": 0},
  "parsing": "unparsed",
  "reason": "No supported report was available"
}
```

When parsing succeeds, the result contains reported outcomes and references to
the source records. It does not contain an overall correctness verdict. A report
can say tests passed while a later command step fails; preserve both facts.

`show_evidence` retrieves the command, execution location, tested repository state,
execution outcome, interpretation and diagnostics, and retained raw output.
It does not rerun or reparse with a different parser silently. Display limits must
be visible, and retained output must remain retrievable.

For the human:

```text
/evidence       List collections on the active session branch
/evidence e42   Inspect one collection and its output
```

Both readers use the same evidence record. The command is a viewer, not another
execution or approval workflow. A missing record or artifact is reported as
unavailable, never as an empty successful run.

## Evidence contract and ownership

Each collection retains:

- Its ID, originating session/tool call, command, execution backend, and working
  directory.
- Repository state observations before and after execution, including dirty state
  when available. A commit ID alone does not identify an uncommitted test input.
- Start/end times, duration, and the executor's outcome: exited with a code,
  failed to start, timed out, cancelled, or unknown.
- Raw output/report references and any capture loss or truncation.
- Declared format, parser identity/version, reported observations, source
  references, and parsing diagnostics.

Unknown fields stay unknown. State snapshots do not establish every dependency,
environment value, or external input read by the command. A state difference
makes reuse of the evidence questionable; it does not prove a behavioral failure.

Ownership is one-way:

1. **Executor:** owns process lifetime and supplies actual execution facts and
   output. For guest commands, these facts come from the guest—not the host
   checkout or the connector's exit status. Never fall back to host execution.
2. **Parser:** derives observations from the declared input. It does not launch
   commands, repair reports, select tests, or decide acceptance.
3. **Collector:** binds execution, input artifacts, and interpretation to one ID
   and publishes the record. Raw data and execution facts remain distinguishable
   from parsed observations.
4. **Viewers:** read the published record without becoming another writer.

Pi's mutable tool-result hooks are not an authoritative process receipt. Capture
must precede result rewriting and display truncation. Reuse Pi's configured
execution facilities rather than introduce a parallel shell implementation;
confirm the required structured outcomes exist at that boundary before coding.

Evidence is harness-recorded rather than model-written prose, not a claim of
tamper-proof storage or an independent acceptance judgment. Raw reports are still
program-produced data. Neither an explicit format nor valid JSON proves the
producer tested the right behavior.

## Parsing and failure behavior

Prefer machine-readable reports over terminal-output heuristics. Each supported
format needs a defined input source, record schema, completeness condition, and
supported producer versions. An unknown format is rejected before execution;
a known format with unsuitable output produces a receipt without interpretation.

Bind reports to the execution that produced them. An existing file at the expected
path is not proof that this run produced it; uncertain report origins remain
uninterpreted.

Streaming is optional, not a prerequisite for the first useful version. Where the
producer supports it, consume complete records incrementally and mark live
observations provisional. Only claim a complete report when its format's completion
condition holds. Cancellation, malformed records, missing required fields,
conflicting records, or lost output must not become a complete passing summary.
Do not turn missing outcomes into passes or missing counts into zero.

Valid observations from an incomplete report may be retained, but incomplete totals
must be labelled as such. Ignore future fields or event types only where the
producer's compatibility contract permits it; malformed known records are different.
Parsing failure does not erase execution evidence. Command failure does not prevent
recording its output. The executor's outcome is never inferred from printed text.

Collection is a foreground, cancellable tool call, not a background job system.
A lost guest connection leaves the remote outcome unknown unless termination is
confirmed. Do not rerun to obtain a cleaner record. If persistence fails, expose
that failure and do not claim the evidence is durably retained.

Bound parser work and report any resource-limit interruption. Preserve normal
command output rather than hide it behind a summary. Raw logs remain private;
do not dump environment secrets, send logs to another model, or publish them as
part of collection. A model-written script's summary is not independently observed
test execution.

## Reuse candidates

These are source-reviewed candidates, not integration-validated dependencies.
Pins identify the inspected code, not a selected installation version.

- **[pytest-reportlog](https://github.com/pytest-dev/pytest-reportlog/blob/cd0788f2c81d8f235ce4b2be2df8afa844a2bcf8/README.rst):**
  MIT-licensed producer. `--report-log=FILE` emits JSONL test/collection events and
  flushes each record, allowing live consumption without interpreting terminal
  formatting. It must be available in the Python environment running Pytest.
  Prefer reusing this producer if that installation constraint is acceptable.
- **[testmcp](https://github.com/r-marques/testmcp/tree/c49b6200905071b3f85cdb0adb2caed1fe8b8b3f):**
  useful execution-ID and drill-down precedent. Its package declares MIT and an
  MCP executable, not a public parser-library interface. Do not adopt the whole
  server's command construction, fallback execution, or in-memory retention.
  Its [Pytest parser](https://github.com/r-marques/testmcp/blob/c49b6200905071b3f85cdb0adb2caed1fe8b8b3f/src/adapters/pytest.ts)
  skips malformed JSON lines and defaults missing outcomes to `passed`; it cannot
  be reused unchanged under this design. Extraction requires a source/license
  review, a maintained ownership decision, and tests for the changed contract.
- **[jc](https://github.com/kellyjonbrazil/jc/tree/73fa7d5572dd730076723bd6280786bb9101d32f):**
  MIT-licensed Python library/CLI with explicit parsers and command metadata.
  Reuse it only for a concrete supported format; do not add it merely to create a
  general parser layer. The inspected parser set has no Pytest-specific parser.
- **[Showboat](https://github.com/simonw/showboat/tree/d531261b8faf0c388b02c7891d50f1f47c3e2b52)**
  records executable commands and output in readable documents.
  **[Jenkins realtimeJUnit](https://www.jenkins.io/doc/pipeline/steps/junit-realtime-test-reporter/)**
  collects report files during execution. These support retained evidence and
  live report collection as patterns; importing their complete applications is
  not proposed.

Keep receipt binding, storage, and the three interfaces harness-owned. Reuse report
producers and suitable parser libraries rather than rebuild test frameworks.
Any selected dependency needs a pinned installation through the owning runtime's
existing package mechanism and real producer-to-consumer verification.

## Decisions before implementation

1. **Report input.** `format="pytest"` is not yet a precise format contract.
   Structured producers write files; the two-argument API does not identify one
   or enable its producer. Decide the report-source parameter and format names,
   or explicitly choose a limited stdout format. Do not silently add report flags
   to arbitrary shell commands. This is also where the plugin-versus-existing
   JUnit-report tradeoff belongs.
2. **Persistence and retrieval.** Choose private storage for raw artifacts and
   versioned receipt metadata. Records should remain inspectable across reload
   and resume; define retention and large-output retrieval before promising it.
   Pi custom session entries can hold references without entering model context,
   but ephemeral sessions are not durable storage.
3. **Execution integration.** Establish how collection reuses the active local or
   guest backend and obtains structured outcomes, output, and repository state.
   Parser reuse does not solve this boundary.

No implementation starts by resolving these questions implicitly.

## Acceptance evidence

Verify the full `collect_evidence` → `show_evidence` and `/evidence` path using
real supported producers in local and guest execution. Include passing and failing
cases, skips, startup failure, malformed/missing or stale reports, cancellation,
transport loss, concurrent collections, dirty inputs, and changed state after a run.
Verify reload/resume and unavailable-artifact behavior once storage is selected.

For streaming, vary chunk boundaries and interrupt a report after valid records.
Exercise setup and teardown failures, not only failed test bodies. Confirm native
execution failure remains visible even when the test report contains only passes.
A parser fixture or aggregate green test count alone does not establish integration.

Excluded: passive parsing of all tools, expected-case registries, protected test
management, automatic acceptance or grading, experiment runners, new permission
policies, and changes to compaction provenance.
