---
name: use-a-library
description: Check for an existing standard-library function, dependency, local helper, or structured result before implementing nontrivial solved-problem logic such as parsing, file walking, date handling, diffing, graph traversal, retry/backoff, or serialization. Not for simple edits that add no such logic or routine calls to an established helper. Use dependency-review when the choice adds or changes a dependency.
---

# Use a library

Find an existing solution that meets the required behavior, or establish why a new implementation is necessary.
This check does not authorize adding features or dependencies outside the task.

## Start with the behavior

Name the operation and required input, output, failure, runtime, and compatibility contracts.
Inspect the caller and data already available before assuming raw input needs another parser or adapter.
For parsing and generated output, apply [language boundaries](../references/language-boundaries.md).

Search by behavior and data shape, not only the proposed function name:

1. Check the standard library and runtime facilities.
2. Inspect current dependencies and local helpers, including their existing callers.
3. Check whether structured source data or an authoritative result eliminates the operation.
4. Consider a small maintained dependency when existing options cannot meet the contract.

Prefer an existing supported solution that fits.
The order guides search effort, not an absolute ranking that overrides compatibility, authority, or dependency cost.
A direct `map` or `filter` does not need a library investigation.
A heavy dependency for a tiny operation can cost more than a small correct local implementation.

## Verify the fit

Check the actual pinned version's supported interface and runtime requirements against the intended consumer.
A public API in an underlying library does not expose a tool's private modules.
For example, reuse structured parser error locations rather than extracting them from a rendered message; verify that the parser version actually returns those locations.
If integration needs private-source access, a downstream patch, or a fork, name its maintenance cost before recommending it.

For an added or changed dependency, use [dependency review](../dependency-review/SKILL.md) and the owning package manager.
Exercise the behavior through the real caller using the repository's testing procedure, not only a standalone library example.

## Finish the choice

Use the selected existing owner rather than leaving parallel implementations.
If custom logic remains necessary, state the concrete contract existing options cannot meet and keep the implementation limited to that gap.
Do not create a separate comparison document for an ordinary local choice.
