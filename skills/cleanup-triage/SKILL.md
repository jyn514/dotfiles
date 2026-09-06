---
name: cleanup-triage
description: Find, prioritize, and slice cleanup work. Use after cleanup has been selected as the target, for a messy subsystem, cleanup roadmap, or opening and refining cleanup issues. For broad project opportunity discovery, use opportunity-scan first.
---

# Cleanup triage

For post-change polish, use the repository's changed-code cleanup workflow. For test-only review, use its test-review guidance when available.

## Read First

Discover and follow the target repository's guidance for issue tracking, code style, architecture, testing, generated files, and subsystem ownership. Do not assume a particular tracker or repository layout.

## 1. Establish safety

- Inspect the working tree with the repository's version-control tool first.
- If files are already modified, inspect only unless the user explicitly asks for edits.
- Use available search, inventory, and repository-maintenance tools. Avoid full test runs unless a cleanup needs validation.
- Check existing tracked work before proposing or filing new issues.

## 2. Inspect by cleanup category

Look for actionable findings in this order:

- **Safety gates:** generated-file ownership, lint/check gaps, public API metadata, compatibility paths, issue/test metadata.
- **Boundary/context cleanup:** implicit context, process-wide mutable state, hidden lifecycle state, concurrency hand-offs, filesystem policy, and resource loading.
- **Large module splits:** files mixing several independently changing responsibilities such as parsing, validation, effects, presentation, diagnostics, compatibility, and API exposure.
- **Test maintainability:** very large test files, repeated global patching or mock setup, access to private implementation details, brittle string assertions, and missing execution-requirement metadata.
- **Generated/tooling hygiene:** generated artifacts, scripts layout, local build artifacts under source-shaped trees, editor/tooling asset ownership.
- **Extraction prep:** standalone-library candidates, integration hooks, dependency direction, and independently testable entrypoints.

Prefer concrete evidence: paths, line counts, repeated patterns, docs/specs, or revealing commands.

## 3. Slice work into implementable issues

Good cleanup issues:
- name the current problem with concrete files or patterns;
- state what source of truth says or what design direction already exists;
- include acceptance criteria that a future agent can implement;
- are small enough to complete without a broad rewrite;
- cross-reference related epics instead of duplicating them.

Avoid:
- vague "clean up X" tickets;
- speculative rename/style tickets;
- broad tickets overlapping extraction epics;
- more filing after findings become weak.

When opening issues, follow the repository's tracker ownership, mutation-safety, and verification rules.

## 4. Report diminishing returns

Say cleanup is hitting diminishing returns when new findings are mostly:
- dependent on issues already filed;
- speculative without file-level evidence;
- naming/style preferences;
- likely churn unless tied to a feature or bug.

When that happens, stop mining and recommend sequencing:

1. Make change safer.
2. Clarify boundaries.
3. Split heavy subsystems.
