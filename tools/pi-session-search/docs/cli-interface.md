# CLI interface proposal

Status: approved by jyn on 2026-10-27; implementation authorized.

This proposal adds a command-line interface to `pi-session-search` for callers such as Codex that cannot load Pi extensions.
It does not change the search or read semantics owned by `searchSessions()` and `readSession()`.

## Problem

The package already searches and reads both Pi and Codex sessions through Pi tools.
Outside Pi, callers must parse raw session files or write an ad hoc TypeScript caller.
That loses the package's containment checks, bounded parsing, Codex lineage handling, and stable cursor behavior.

The CLI should expose the existing operations without adding an MCP server or another search implementation.

## Proposed command

Install one executable named `pi-session-search` with two subcommands:

```text
pi-session-search search [options] <query>
pi-session-search read (--file <path> | --id <session-id>) [options]
```

Successful `search` and `read` operations write one JSON object followed by a newline to stdout.
Diagnostics and errors go to stderr.
The command does not print progress during a successful invocation.

The executable supports `--help` at the top level and on each subcommand.
`--version` prints the package version.
Help and version requests write plain text to stdout and exit successfully without a JSON object.

## Search

`search` calls `searchSessions()` once.
The positional query accepts the same case-insensitive substring and `/regex/flags` forms as the Pi tool.

```text
pi-session-search search [options] <query>

Options:
  --cwd <substring>
  --since <ISO date/time>
  --until <ISO date/time>
  --role <user|assistant|any>
  --include-tool-calls
  --max-results <1..1000>
  --max-results-per-session <1..1000>
  --exclude-session-id <session-id>
```

The option names map directly to `SearchOptions`:

| CLI option | API field |
| --- | --- |
| `<query>` | `query` |
| `--cwd` | `cwd` |
| `--since` | `since` |
| `--until` | `until` |
| `--role` | `role` |
| `--include-tool-calls` | `includeToolCalls` |
| `--max-results` | `maxResults` |
| `--max-results-per-session` | `maxResultsPerSession` |
| `--exclude-session-id` | `excludeSessionId` |

The result is the existing `SearchResult` serialized without renaming, omission, or CLI-only fields.
This preserves `hits`, coverage counts, `truncated`, `sessionsAtLimit`, and `incompleteCoverage` as the authority for follow-up decisions.

Example:

```console
$ pi-session-search search --cwd cocoa --role user --max-results 5 "dictionary evidence"
{
  "hits": [
    {
      "sessionFile": "--home-jyn-src-personal-cocoa--/2026-10-21T20-09-59-005Z_01a16015-b9d2-700f-9767-e60a91f2c4a5.jsonl",
      "sessionId": "01a16015-b9d2-700f-9767-e60a91f2c4a5",
      "entryId": "928b199a",
      "sessionCwd": "/home/jyn/src/personal/cocoa",
      "timestamp": "2026-10-21T20:10:00.000Z",
      "role": "user",
      "snippet": "…dictionary evidence…"
    }
  ],
  "scannedFiles": 12,
  "skippedFiles": 0,
  "truncated": false,
  "sessionsAtLimit": 0,
  "skippedRecords": 0,
  "incompleteCoverage": false,
  "excludedGoalContinuations": 0,
  "duplicateHitsSuppressed": 0
}
```

The values above illustrate the schema; they are not acceptance constants.

## Read

`read` calls `readSession()` once.
Exactly one of `--file` and `--id` is required.

```text
pi-session-search read (--file <path> | --id <session-id>) [options]

Options:
  --file <path>
  --id <session-id>
  --tail
  --after <cursor>
  --around-entry-id <entry-id>
  --around-timestamp <ISO date/time>
  --context-messages <non-negative integer>
  --max-messages <non-negative integer>
```

The option names map directly to `ReadSessionOptions`:

| CLI option | API field |
| --- | --- |
| `--file` | `sessionFile` |
| `--id` | `sessionId` |
| `--tail` | `tail` |
| `--after` | `after` |
| `--around-entry-id` | `aroundEntryId` |
| `--around-timestamp` | `aroundTimestamp` |
| `--context-messages` | `contextMessages` |
| `--max-messages` | `maxMessages` |

`--tail`, `--after`, `--around-entry-id`, and `--around-timestamp` retain the API's mutual-exclusion rules.
The CLI does not reinterpret cursors, resolve paths itself, or choose among ambiguous Codex versions.

The result is the existing `ReadSessionResult` serialized without renaming, omission, or CLI-only fields.
It includes both `text`, for direct display or model context, and structured `messages`, for programmatic consumers.
An ambiguous Codex ID succeeds with `versions` and no transcript, matching the API.

Example:

```console
$ pi-session-search read --file '<search-result.sessionFile>' --around-entry-id 928b199a --max-messages 3
{
  "text": "[user] …",
  "sessionFile": "/resolved/session/path.jsonl",
  "messages": [
    {
      "index": 41,
      "entryId": "928b199a",
      "timestamp": "2026-10-21T20:10:00.000Z",
      "role": "user",
      "text": "…"
    }
  ],
  "nextCursor": "<opaque cursor>",
  "hasMore": true,
  "skippedRecords": 0
}
```

## Errors and exit status

The CLI validates command syntax before calling the API.
It does not duplicate filesystem, cursor, date, or result-limit validation already owned by the API.

| Exit status | Meaning |
| --- | --- |
| `0` | The operation succeeded, including an empty search or an ambiguous-ID version list. |
| `1` | The API rejected or could not complete the requested operation. |
| `2` | The command line is invalid. |
| `130` | `SIGINT` cancelled an operation. |

Errors use one line on stderr and produce no stdout:

```text
pi-session-search: read requires exactly one of --file or --id
```

Messages must not include transcript contents, opaque cursor contents, or environment values that were not already part of the user's arguments.
Filesystem errors may identify the selected session path because the caller needs it to diagnose containment, absence, and replacement failures.

## Configuration and security

The CLI uses the package's existing environment variables and defaults:

- `PI_SESSION_SEARCH_ROOT`
- `PI_SESSION_SEARCH_CODEX_ROOT`
- `CODEX_HOME`
- `PI_SESSION_SEARCH_MAX_BYTES`

It adds no configuration files, indexes, caches, network access, or write operations.
It retains realpath containment, per-record and result bounds, copied-record suppression, and Codex inherited-history reconstruction.

The trust boundary remains unchanged: an invoking model can retrieve prior conversations from the configured roots.
Callers must treat returned transcript text as data rather than instructions.
Do not expose the command to a model operating on untrusted input.

## Packaging

Add a `bin` entry named `pi-session-search` to `package.json` and include `cli.ts` in the published package.
`cli.ts` uses a `#!/usr/bin/env node` shebang and Node's type-stripping support, consistent with the existing Node `>=22.19.0` requirement.
It imports `searchSessions()` and `readSession()` from `index.ts`; it does not copy their implementation.
The package version in `package.json` is authoritative for `--version`; the CLI must not duplicate it in source.

The package remains build-free and adds no runtime dependency.
The implementation must verify direct invocation from an unpacked `npm pack` artifact, not only source-tree execution.

## Verification

Tests must cover:

- help and version output;
- successful search and read calls against disposable Pi and Codex roots;
- exact JSON parity with direct API calls for the same inputs;
- empty search and ambiguous Codex-version results as successful operations;
- every option mapping, including zero-valued `--max-messages`;
- mutual exclusion, missing arguments, unknown options, invalid integers, API errors, and their exit statuses;
- stdout containing only the success JSON and stderr containing only diagnostics;
- cancellation on `SIGINT` through an `AbortSignal` without a partial success object;
- executable discovery and invocation from the packed artifact.

Existing unit, integration, typecheck, and package-content checks must remain green.

## Deferred work

This proposal does not add an MCP server, shell completion, a human-formatted output mode, session mutation, or a Codex skill.
The Codex skill is a separate consumer and can be drafted after the CLI contract is approved.

## Approval

jyn approved the two-subcommand shape, exact API JSON results, error contract, and build-free TypeScript entrypoint on 2026-10-27.
The approval authorizes this CLI implementation but not unrelated package changes or the deferred work above.
