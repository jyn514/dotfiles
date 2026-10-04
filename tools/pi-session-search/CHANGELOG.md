# Changelog

All notable changes to `pi-session-search` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Migrate the host peer and type imports to `@earendil-works/pi-coding-agent`
  1.0.2. Node.js >=22.19.0 is now required, matching that host's manifest.
  Users of the deprecated `@mariozechner/pi-coding-agent` must migrate their
  CLI before installing or reloading this extension.
- Pin TypeScript and Node.js type declarations as development dependencies so
  `npm run typecheck` works without a host-installed compiler.
- Stream session records instead of loading entire transcripts.
- Keep `PI_SESSION_SEARCH_MAX_BYTES`, but redefine it as the per-record
  raw-byte cap (default 5 MiB, 5,242,880 bytes, excluding the LF delimiter).
  Existing file-size overrides should be revisited because the setting now
  limits one record's memory use; there is no whole-file size cap.
- Skip records exceeding the configured cap before decoding/parsing, then
  resume at the next record. Search results include `skippedRecords` and
  `incompleteCoverage`; window reads and `/find-sessions` show
  incomplete-coverage warnings. Skipped records are excluded from window
  counts and indexes.
- Search retains only hits and stops at the hit limit or cancellation. Window
  reads use two passes: the first counts eligible messages and selects the
  nearest timestamp (first in file order on ties), and the second retains only
  the requested window. Both use the initial file length.
- Support cancellation during streaming for both tools. `contextMessages` and
  `maxMessages` accept non-negative safe integers, including `0`; defaults are
  6 and 30.

## [0.1.0] — 2026-05-04

Initial public release.

### Features

- **Tool `search_sessions`** — the active LLM can grep prior pi session
  transcripts (`~/.pi/agent/sessions/*.jsonl`) for a substring or
  `/regex/flags` query without resuming the session. Filters by `cwd`,
  time range (`since`/`until`), `role`, and `includeToolCalls`.
- **Tool `read_session`** — read a window around a specific timestamp in
  a previously-found session, for pulling more context after a hit.
- **Slash command `/find-sessions`** — the same search, surfaced as a
  user command for manual exploration. Supports `--cwd=`, `--role=`,
  `--since=`, `--until=`, `--max=`.

### Hardening

- Per-subdirectory and per-file `realpath` containment so a `.jsonl`
  symlinked outside the configured sessions root is detected and
  skipped (counted as `skippedFiles` in the result).
- Stat-cap on `read_session`: refuses any file larger than
  `PI_SESSION_SEARCH_MAX_BYTES` (default 5 MB) with a clear error.
- `maxResults` enforced as integer in `[1, 1000]` at both the schema
  and runtime layers; explicit invalid values reject loudly rather
  than silently coercing to the default.
- Regex-flag handling: the `/.../flags` form respects user case-
  sensitivity intent but strips `g` (which removes match-position
  bookkeeping) and `y` (sticky/stateful).
- Per-message haystack capped at 256 KB before regex matching to bound
  best-case ReDoS. **Not** a guarantee against a truly catastrophic
  pattern — see README for the full trust model.

### Notes

- Licensed under Apache License 2.0.
- 47 unit and integration tests covering helpers and an end-to-end
  fixture sessions directory, including symlink-escape attempts.
- See `README.md` for the trust model, environment variables, and the
  explicit "do not expose to a model operating on untrusted input"
  warning around historical-session exfiltration.
