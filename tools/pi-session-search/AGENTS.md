# Agent guidelines — pi-session-search

Guidance for AI coding agents (Claude Code, Cursor, Copilot, etc.)
working on this repo. Humans should also skim this; nothing here is
agent-specific in spirit.

## What this is

A TypeScript extension for the third-party open-source CLI
[`@earendil-works/pi-coding-agent`](https://github.com/earendil-works/pi).
It exposes two read-only tools (`search_sessions`, `read_session`) and
a `/find-sessions` slash command that grep prior pi session transcripts
on disk.

Peer-deps only on `@earendil-works/pi-coding-agent` and `typebox`. No
Adobe-internal dependencies, no servers, no network calls.

## Build / test / typecheck

```bash
npm install        # if node_modules is missing
npm test           # runs unit + integration tests
npm run typecheck  # tsc --noEmit against tsconfig.check.json
```

`npm test` must stay green on every PR. Don't merge red.

## Packaging & runtime (read before touching `engines` or the loader)

- pi loads `.ts` extensions through its TypeScript loader (`jiti`), **not**
  Node's native `--experimental-strip-types`. The published package's
  `engines.node` must mirror the supported host CLI's manifest, **not** the
  Node version the test script happens to need. Check the installed host's
  loader and manifest before changing this boundary.
- pi has first-class npm support: `pi install npm:@adobe/pi-session-search`
  is the primary install path. Keep the published tarball loadable as-is
  (no build step) — ship the `.ts` sources, not compiled JS.
- The `files` whitelist in `package.json` is what ends up in the npm tarball.
  If you add a runtime file the extension needs, add it to `files` too, or it
  won't ship. Verify with `npm pack --dry-run` before publishing.
- General lesson worth keeping: don't assert a dependency's internal
  mechanism (loader, engine requirement, transport) without checking its
  actual code/manifest first. This note exists because that check was once
  skipped.

## Code style

- TypeScript, `strict: true`. No `any` without a written justification
  in a comment.
- The implementation is a single `index.ts` file by design; resist the
  urge to split it unless the file actually outgrows readability.
- No new runtime dependencies without discussion.
- Apache-2.0 header on every new `.ts` file, copyright
  `2026 Adobe`. Match the format of the existing source.

## Commit / PR hygiene

- Conventional-commits style commit messages.
- Squash PR branches to a single descriptive commit before merging.
- Don't bundle unrequested work. Surface adjacent fixes in the PR
  description and ask — don't silently include them.

## Trust model

Read the **"Trust model & security notes"** section of `README.md`
before changing anything in the directory walk, the JSONL parser, or
the regex/matching path. The threat model — including the warning
that this tool must never be exposed to a model running on untrusted
input — is documented there in full.

## Security invariants — don't weaken these

These were tightened during the open-source review. Don't relax them
without an explicit discussion on the PR:

- **`realpath` containment.** Both per-subdirectory and per-file. A
  `.jsonl` symlinked outside the configured sessions root must be
  detected and skipped. Don't substitute `lstat`-only checks.
- **Bounded streaming records.** Follow README's “Bounded record parsing”
  security contract when changing the reader. Do not restore a whole-file
  size ceiling or retain the full transcript in memory.
- **Regex `g` and `y` flags stay stripped.** They break match-position
  bookkeeping in the snippet logic and have caused real bugs.
- **`maxResults` is schema-clamped to `[1, 1000]`.** Don't relax the
  upper bound; large result sets blow up the calling LLM's context.
- **Per-message haystack cap** of 256 KB before regex matching. Keeps
  worst-case regex evaluation bounded.
- **Read-only by design.** This tool must never grow a write code path
  — no editing transcripts, no deleting sessions, no archive operations.
  If a write feature is genuinely wanted, it goes in a different
  extension.
- **No new network calls.** No telemetry, no remote indexing, no
  cloud-sync. Local filesystem only.
