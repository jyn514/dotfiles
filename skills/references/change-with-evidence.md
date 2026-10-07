# Change with evidence

These rules apply when designing, implementing, or reviewing code, configuration,
or tests. Read them before that work; they supplement the always-loaded shared
instructions.

## Language separation

Apply LANGSEC (language-theoretic security): keep different languages in separate files rather than nesting them. For example, a Python script must launch a separate Bash file, not embed a multiline Bash string.

## Compatibility

Do not preserve compatibility for internal interfaces whose producers and consumers change and deploy together. Preserve compatibility at external, persisted-data, protocol, and independently deployed boundaries, or when justified by a historical constraint.

## Single authority

When the same value appears across multiple consumers, choose one authoritative representation and derive the others from it. Consumers should refer to stable roles or interfaces rather than repeat filenames, paths, commands, identifiers, defaults, or other change-prone constants.

Add a regression test showing that changing the authority updates consumers without corresponding edits.

## Logging

Default CLI output must be human-scannable. Show the action, material inputs,
current phase, result, and next action; keep hashes and internal data in
receipts or explicit machine-readable output. Report failures once, stating
what failed, why, cleanup/publication status, and recovery action. Use stdout
for results and stderr for progress or diagnostics. Test representative
success and failure output as a user-facing contract.

## Distinguish guarantees from details

API guarantees between architecture boundaries must be explicitly documented.
Do not depend on internal details, exact source code, or coincidentally convenient properties.
This applies WHENEVER there is an architecture boundary, even when writing tests for code you wrote yourself.
Consult the "Principles" section of `architecture-design` for what constitutes a boundary.
