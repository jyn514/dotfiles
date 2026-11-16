# Diagnostic design

Read when designing, implementing, writing, or reviewing user-facing diagnostics, source labels, or repair suggestions.
For structured exception data and recovery evidence, use [failures and recovery](failures-and-recovery.md).
For authoritative parsing and source interpretation, use [language boundaries](language-boundaries.md).

## State the known failure

User-facing errors should name the violated rule or broken assumption, not only the internal operation.
State what the owning subsystem knows is wrong; keep a proposed repair separate from that diagnosis.
For example, a parser can know that a value is missing after `timeout:` without knowing which duration the author intended.
Report the missing value as the failure, not “set the timeout to 30 seconds.”
Use the reader's vocabulary and include the offending name or value when it helps identify the failure.

Give each part of the diagnostic a distinct job:

- The headline names the known failure and stands alone in line-oriented output.
- The primary source label explains why the highlighted source is blamed.
- Secondary labels explain relationships, such as “first declared here” or “constraint established here.”
- An explanation supplies causal detail when the rule is not self-evident.
- A suggestion describes an available next action and the result of a non-obvious edit.

Omit parts that add nothing.
Do not make a headline carry the source context, explanation, evidence, and repair at once.
For a duplicate declaration, the headline can name the duplicate, the primary label identify the conflicting declaration, and a secondary label show the first declaration.
A label that only says “here” leaves that relationship unexplained.
When a failure compares values, show the expected constraint and actual value or smallest relevant difference rather than dumping whole structures.

## Separate repair confidence from completeness

Confidence describes how strongly the evidence supports a repair.
Completeness describes whether the replacement still needs author-supplied content.
Keep these independent in the diagnostic data and presentation when the system offers edits.
A parser may confidently suggest adding a required field while leaving its value as a placeholder.
A fully spelled nearest-name replacement can still be uncertain because several names fit the author's intent.
Being the closest string is not enough: use scope, expected role, and syntax as evidence, or omit weak suggestions.
Present plausible competing repairs as alternatives.

For tool-provided fix-its, automatic application requires all of the following:

- High confidence derived from the recognizer and transformation, not one plausible example.
- A complete replacement without placeholders.
- An exact edit span.
- Valid syntax under checked preconditions.
- No author judgment about intended meaning.

A repair that may change meaning remains a proposal, not an automatic edit.
Phrase or label suggestions so readers can distinguish a confident repair, a possible repair, and a template that needs completion.
These conditions govern a diagnostic tool's automatic fix-its, not permission for a coding agent to perform its assigned work.

## Verify what the reader receives

Trace diagnostic data through adapters and renderers to the supported user-facing entrypoint.
A structured field is not visible merely because a producer populates it.
Explanations must refer to displayed information or a concrete source the reader can inspect.
Preserve existing rendered-output regressions when an internal adapter moves and the presentation contract remains unchanged.

When changing a diagnostic's presentation contract, check the complete displayed diagnostic, including applicable headline, source frame, labels, explanation, suggestions, and context.
Use a reviewed snapshot or equivalent complete-output assertion through the owning renderer or entrypoint, alongside structured assertions for relevant data.
Checking only a message substring or structured map can miss a dropped label or a suggestion the renderer never shows.
Cover reachable changed branches; record why rendered output cannot change if structured checks alone suffice.
For suggestions, cover confidence, completeness, automatic-application preconditions, alternatives, and a case where no fix should appear.
