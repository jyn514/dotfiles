---
name: session-title-curation
description: Review, propose, and apply descriptive titles to past Pi sessions. Use when the user asks to name, rename, organize, or curate historic sessions, including sampling session history before changing titles.
---

# Session title curation

Use `search_sessions` and `read_session` to understand past work. `read_session` reports the effective current title before the transcript window. Use `edit_session_title` only after the user explicitly authorizes title changes.

## 1. Establish the requested mode

Distinguish these operations before acting:

- **Suggest:** inspect sessions, draft and review titles, then present the revised proposals; make no metadata changes.
- **Apply:** write titles the user has approved.

A request to suggest, sample, inspect, or review titles is not permission to apply changes. Preserve this boundary even when the intended titles appear obvious.

## 2. Select sessions

- Search within the relevant working directory when known.
- Deduplicate search hits by session ID; search results are messages, not sessions.
- Prefer a varied sample over several nearly identical adjacent sessions unless the user requests recency.
- Keep the exact full session ID or returned session file with every candidate.
- Exclude the current session from historic-title mutation.

Search results are message hits, so keep searching and deduplicating until the requested number of distinct session IDs is reached. Vary broad task terms to reduce query bias. If the available search surface still cannot supply the requested count or a representative sample, state the shortfall instead of silently substituting repeated sessions.

## 3. Read enough context

Read the opening request, important course corrections, and final outcome. A middle snippet alone often names an abandoned approach.

For long sessions, inspect additional windows when:

- the task changed materially;
- implementation followed an investigation;
- the opening request was blocked or replaced;
- the session contains multiple substantial tasks;
- the proposed title depends on whether work was merely discussed or completed.

Do not expose private transcript details beyond what is needed to justify the title.

## 4. Write useful titles

Prefer concise titles that name the durable purpose or result of the session.

- Use an imperative or compact noun phrase consistently within a batch.
- Name the owned subsystem or command when it distinguishes the work.
- Prefer the final implemented direction over an abandoned intermediate approach.
- Distinguish investigation from implementation: use verbs such as `Diagnose`, `Design`, `Fix`, `Add`, or `Reduce` accurately.
- Avoid generic titles such as `Fix issue`, `Review work`, or the first user message copied verbatim.
- Do not claim completion when the session ended blocked or remained exploratory.
- When two substantial tasks share one session, name both briefly or state that the session resists a single clean title.

Present the session ID beside each proposal so approval is unambiguous.

## 5. Review every suggestion

Before presenting proposed titles, perform one explicit self-review pass and revise weak titles. Check:

- factual fit with the session outcome;
- specificity without implementation trivia;
- consistent capitalization and verb form;
- accidental duplication across sessions;
- titles that describe only an intermediate step;
- sessions that should remain untitled because evidence is inadequate.

Present only the reviewed proposals. If the user later asks for another review, return revised proposals without mutating sessions.

## 6. Apply approved titles

Require `edit_session_title` for mutation. If it is unavailable, stop and report the missing capability; do not edit session JSONL directly. The tool accepts one bulk request:

```json
{
  "edits": [
    { "session": "<exact full session ID or absolute JSONL path>", "title": "<approved title>" }
  ]
}
```

Put all approved mappings for the operation in one `edits` array. Use each exact approved title; an empty title clears it. The tool validates the complete batch before writing and rejects active, unknown, ambiguous, or duplicate sessions. It skips titles that already match, then applies the rest sequentially. A write failure stops the operation and returns the entries already applied, unchanged entries, and the failed entry; because Pi has no cross-file transaction, the batch can be partially applied.

Before applying titles, state that Pi has no cross-process session lock and that this workflow cannot prove another process does not have a target open. Do not claim exclusive access.

- Apply only the approved mapping; do not silently improve wording during mutation.
- Treat each reported edit as evidence that its title entry was appended; unchanged entries required no write.
- If validation fails, report that no entries were applied.
- If a write fails, report the applied count and failed session precisely; do not imply the whole batch succeeded or retry already-applied entries blindly.
- For independent post-write verification, call `read_session` for the affected sessions and compare its reported title with the approved mapping; do not inspect or rewrite JSONL ad hoc.

Afterward, report changed, unchanged, and failed counts and whether `read_session` verified the result. Do not replay the entire title table unless the user asks.
