---
name: reorganize-docs
description: "Reorganize project documentation: information architecture, consolidation, splits, renames, archives, and navigation. Not for prose-only tightening or docs-site correctness review."
---

# Reorganize Documentation

Improve how readers find and use documentation without losing policy, rationale, examples, or historical evidence.

## Read first

Discover and follow the target repository's development lifecycle, documentation entrypoint, prose and ownership rules, source-of-truth policy, and guidance for repository-local skills. Read the nearest index for every documentation subtree in scope.

Use the format-specific owner for specifications, generated documentation, public docs, or Typst files. Use the `tighten-docs` skill before the final prose pass.

## Observe

1. Inspect the working copy and protect unrelated changes.
2. Inventory paths, titles, headings, line counts, internal links, and the entrypoint that reaches each active subtree.
3. Identify broken targets, orphaned active pages, unlinked children, likely overlap, misleading names, mixed purposes, and archive roots that no active page exposes.
4. Read entrypoints first, then implicated pages.
5. Search repository-wide for every path proposed for movement or renaming.

An unlinked page is not necessarily obsolete.
Determine whether it is active policy, reference, a decision record, a work note, or historical evidence.

## Diagnose

Classify each page by its primary reader need:

- Tutorial: learn through a guided sequence
- How-to: complete a concrete task
- Reference: look up exact facts or contracts
- Explanation: understand reasons, concepts, or tradeoffs
- Policy: follow repository-owned constraints
- Archive: retain historical evidence without presenting it as current guidance

Record the canonical owner for repeated concepts and prefer cross-links over copied rules.
Organization is suspect when:

- One index mixes ordinary work, specialized authoring, maintenance, and release operations
- Several pages claim the same workflow or checklist
- One page mixes policy, procedure, reference, and historical design
- A router lists filenames without usable links or task-oriented labels
- Active-looking notes are orphaned, speculative, completed, or superseded
- Names describe implementation accidents rather than reader tasks
- A split adds navigation hops without giving the reader enough information to choose the next page
- A reference split hides rules, decisions, safety boundaries, or stop conditions needed on every invocation

Fragmentation alone is not a defect.
Keep narrow owner pages when they have distinct triggers and a clear router.
Do not split by line count alone.

## Plan

Before editing, state:

- Pages and canonical owners to preserve
- Pages to merge, split, rename, or archive
- Navigation, reciprocal links, and archive entrypoints to add
- References that must move with renamed paths
- Any additional hops introduced and how routers will make them useful
- For each proposed extraction, whether it is operative procedure or conditionally needed reference material
- Validation commands for each changed format

Prefer the smallest change that removes a real navigation or ownership problem.
Do not normalize unrelated names or headings merely for visual uniformity.

## Edit

1. Improve the entrypoint before adding deeper structure.
2. Group navigation by reader task or lifecycle stage.
3. Keep one canonical rule and replace duplicates with links.
4. Preserve split or moved text mechanically or section by section before refining it.
   When automating section extraction, use Markdown-aware boundaries or verify that headings inside fenced examples were not treated as document sections.
5. Keep mandatory sequence, decision rules, safety constraints, and stop conditions in the task entrypoint.
   Move only material that can be read conditionally, such as catalogs, literal templates, extended examples, and variant-specific detail.
6. Make router descriptions sufficient to choose a child page without opening each one.
7. Archive completed spikes, tentative notes, and superseded designs without presenting them as current guidance.
   Record the former path, archive date, known source date and author or commit, explicit unknowns, and why the record is historical.
8. Link the archive index from an appropriate active reference page;
   archived leaves may remain outside ordinary task navigation.
9. Update repository references in the same change, including agent instructions, skills, specifications, and generated owners.
10. Remove empty directories and disposable platform debris only within scope.

Do not archive unresolved work unless another active owner or issue preserves its obligation.
Do not turn a historical decision into current policy without verifying that it still governs the repository.

## Verify

- Check Markdown link targets, active-page reachability, and whether each archive root is reachable from active reference navigation
- Search repository-wide for stale paths and old names;
  distinguish intentional former-path provenance from live stale references
- Compare moved or split pages with the prior revision;
  account for policy, rationale, commands, examples, and warnings
- Treat changed introductions, relative links, headings, and ownership statements as expected differences, then investigate every other missing block
- Read each common entrypoint alone first;
  confirm it still contains every rule needed to begin, decide, act safely, stop, and validate
- Then follow its routers and judge whether conditionally needed material is easier to choose, not merely still reachable
- Run the smallest format-specific lint or compile check for every changed surface
- Inspect the final diff for formatting-only churn and unrelated files
- Use `tighten-docs` on substantially rewritten prose
- Obtain current-change review for broad, cross-boundary, or policy-ownership changes

## Report

State the information-architecture and ownership changes, archived pages and provenance, validation results, protected or unverified surfaces, and any material now one click farther away.
