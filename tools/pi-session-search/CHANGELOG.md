# Changelog

All notable changes to `pi-session-search` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
