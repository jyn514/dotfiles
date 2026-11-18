# Non-narrowing check

Check whether a downstream contract rejects cases, implementations, or results upstream permits, including permitted explanation modes.
This focused check does not start a full specification review.
Use the shared [decision-authority rule](~/.agents/shared.md#before-selecting-a-substantial-approach) when tracing approval.

## 1. Establish permitted cases

Read the approved brief, incorporated policy, and explicitly approved product decisions—not just downstream documents that may repeat the same restriction.
Draft definitions and source labels cannot authorize themselves.
Record otherwise-valid permitted cases, implementations or results, their origins, and the minimum evidence that observably suffices for each permitted explanation mode.

For example, suppose a spelling system inherits a mapping from `night` to `nite`.
Its approved brief permits inherited mappings that cannot be derived from a rule and explicitly counts them as memorized exceptions.
The proposed alternative retains that exact mapping, verifies its source identity, and records that the selected rule cannot derive it.
The alternative is otherwise valid, but a downstream requirement says every exception must be “justified.”
One reading accepts the recorded facts for this memorized exception.
Another rejects it without independent evidence of conflict or irregularity.
Both readings fit the word; they do not admit the same alternatives.

Include otherwise-similar cases from differently governed populations—groups distinguished by origin or scope, such as inherited versus new mappings.
Checking only the more restricted group cannot establish the other's permission.

## 2. Trace rejection conditions

Inspect definitions, examples, and acceptance criteria for eligibility rules, evidence burdens, and stronger promises that exclude otherwise-conforming implementations or results.
For each stronger condition, identify the governing obligation or actual consumer need and why it requires that condition; the draft's own promise cannot authorize itself.
Preserve the source's population, conditions, and phase:

- Does a restriction on new forms now reject inherited forms too?
- Has a condition for final adoption become a condition for entering review?
- Does one explanation mode now have to meet another mode's evidence standard?

In the spelling example, inability to derive `nite` does not by itself mean lack of an explanation: the brief permits memorization.
Check what evidence that mode needs rather than treating derivation as the only possible justification.

For example, a requirement permits optional transforms A and B but does not require exhaustive alternatives.
An implementation that offers A and B individually without composing them can satisfy that requirement.
A downstream promise to enumerate every repeated combination of A and B would exclude it even if all required inputs remain accepted.
Check whether an upstream scope or actual consumer contract requires that closure before treating it as mandatory.

## 3. Compare plausible readings

Compare “explained,” “justified,” “supported,” and “valid” with the evidence established in step 1.
Apply competing meanings to the same otherwise-valid upstream case, implementation, or result.
If the readings admit different cases or implementations, report a material ambiguity even without a literal contradiction.
Identify the condition rejecting the case or implementation, or leaving acceptance unresolved.

## 4. Follow authority, not stricter defaults

If the source settles the case, request wording and acceptance evidence preserving its answer.
Otherwise, name the product decision needed before approval.
Missing authority does not prove a restriction false.
Flag unsupported safety or validation restrictions while preserving approved limits.
Do not default to stricter readings as “safer.”
Resolve what “justified exception” requires before approval rather than leaving the eligibility decision to downstream readers.
