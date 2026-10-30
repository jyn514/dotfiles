# Design review

Review the requested artifact against its purpose and project constraints.
Report findings; revise the artifact only when requested, except for the TODO comments that `new-tool-development` permits agents to add to human-authored product briefs.

## Read First

- Read the project's design principles, documentation conventions, and canonical
  references relevant to the artifact. Do not import another project's rules.
- Establish maturity: an exploratory sketch, a selected design, or an
  implementation-ready specification. Use its stated scope and open questions
  to set the review threshold.
- Before endorsing a general interface, inspect representative real consumers
  and their existing ownership contracts. Do not infer their requirements solely
  from the subsystem being redesigned; flag conflicts with responsibilities they
  already own.

## Maturity-specific review for new-tool artifacts

For a new-tool workflow, distinguish these artifact maturities:

- **Product brief:** owns the problem, outcomes, scope, non-goals, and human decisions.
- **Requirements:** must trace to an approved brief, be observable and solution-neutral, and flag invented product decisions.
- **Implementation spec:** must cover the requirements, own mechanisms, boundaries, and evidence, and introduce no new product behavior.

Review upstream/downstream consistency and identify dependent artifacts or evidence invalidated by stale upstream decisions. These distinctions supplement the consistency, necessity, duplication, completeness, rationale, orthogonality, and findings rules below; they do not replace them.

## Non-narrowing check

For requirements and implementation specs, first establish what the upstream authority permits.
Only then assess what downstream eligibility rules admit or reject.
When tracing a draft constraint to approval, apply the shared [decision-authority rule](~/.agents/shared.md#before-selecting-a-substantial-approach).

1. **Establish authority and permitted cases.** First read the approved brief, incorporated policy, and explicitly approved product decisions.
   Write down a few cases that are otherwise valid and permitted, noting which source population each comes from.
   For each explanation mode that the source permits, identify the least evidence that is sufficient for that mode.
   A population is the group distinguished by origin or scope; if eligibility differs between groups, include otherwise-similar cases from both.
   Looking only at the more restricted group cannot establish what the other group is allowed to do.
   Keep uncertainty visible: neither a draft definition nor a label citing a source clause can grant itself authority.
2. **Trace eligibility restrictions.** Check definitions, examples, and acceptance criteria for eligibility rules, rejection conditions, and evidence burdens.
   For each stronger condition, identify its authoritative source and explain why it is needed to enforce that source.
   Preserve the source's population, conditions, and phase.
   For example, do not silently apply a restriction on new forms to inherited forms, or turn a condition for final adoption into a condition for pre-review.
3. **Check permitted explanation modes.** Compare draft words such as “explained,” “justified,” “supported,” and “valid” with the explanation modes and sufficient evidence recorded in step 1.
   For each mode the source permits, establish observable evidence sufficient for it.
   Do not assume that every mode needs a derivation from a rule or the same kind of justification.
4. **Compare plausible readings.** If an eligibility term in the draft has two plausible meanings, apply both meanings to the same otherwise-valid case permitted upstream.
   If one meaning admits the case and the other rejects it, that is a material ambiguity even if the draft contains no direct contradiction.
   When the source settles the case, ask for wording and acceptance evidence that preserve the source's permission.
   When it does not, name the product decision needed before approval.
   Do not choose the stricter meaning just because it seems “safer.”
5. **Trace the downstream decision.** Follow each case to the downstream condition that rejects it or leaves acceptance unresolved.
   Flag unsupported narrowing, including restrictions framed as safety or validation requirements, while preserving approved limits.
   If authority is missing, that limits what the review can conclude; it does not prove the restriction false.

For example, suppose the source permits inherited mappings that are not derived from a rule, and explicitly counts them as memorized exceptions.
Consider an otherwise-valid alternative containing an exact retained mapping, a verified identity for its source, and a recorded gap in deriving it from the selected rule.
Ask whether the authority requires independent evidence of conflict or irregularity, or whether the stated facts suffice to count the mapping as memorized.
If the authority settles the question, preserve its answer; if not, name the product decision needed before approval.
Do not impose an independent-evidence requirement without that authority.
Resolve the difference before approval; “justified exception” by itself does not say what qualifies.
A missing derivation from a rule is not the same as a missing explanation when the source permits memorized mappings as an explanation mode.

## Consistency

Flag contradictions and conceptual mismatches between sections, examples, and
normative rules. Check that names, ownership, and guarantees retain the same
meaning across boundaries. Distinguish an observed conflict from an assumption
that needs evidence.

When a revision moves ownership or simplifies an interface, audit signatures,
lifecycle rules, examples, and open questions throughout the artifact and linked
specifications for responsibilities still assigned to the old owner.

## Necessity

Ask who uses each feature and whether its implementation and maintenance costs
are justified. Identify the concrete consumer or constraint behind each mechanism;
flag machinery supported only by hypothetical needs. Consider whether the same
requirement can be met by an existing primitive or a narrower interface.

Trace each mechanism to the upstream outcome it is needed to satisfy;
flag unsupported constraints before evaluating simplifications or alternatives.

Before recommending parser or component reuse, apply the
[supported-interface rule](../../references/change-with-evidence.md#distinguish-guarantees-from-details).

## Duplication

Give normative behavior one canonical owner and use direct references elsewhere.
Flag independently maintained definitions that can drift. Preserve local context
needed to understand a rule where it is applied.

## Completeness

Judge completeness against maturity. A sketch may leave transport and algorithms
open if it states the important ownership and guarantees. A selected design must
settle decisions that change its architecture; an implementation-ready spec must
not leave incompatible observable behaviors for implementers to choose between.

Look for missing inputs, results, failure behavior, lifecycle ownership, and
acceptance evidence where they affect the design's claims. Do not demand a full
API catalog or implementation plan from a high-level sketch.

Use the [design-risk applicability scan](../../architecture-design/references/design-risks.md#applicability)
to select checks for the proposed behavior, including runtime progress for asynchronous lifecycles.
Match findings to the artifact's maturity; these checks do not authorize redesign or require new mechanisms.

## Rationale and principles

Review against the project's stated principles; distinguish violations from
deliberate, explained tradeoffs. State the current design directly. Remove obsolete
comparisons, but retain rejected alternatives and historical constraints when they
explain a decision or prevent a known failure.

## Orthogonality

Before flagging overlapping interfaces, trace whether they lower to one primitive
or maintain separate semantics. A configuration shorthand that expands to an
existing operation need not be a competing mechanism.

Independent implementations with overlapping semantics need a concrete reason.
A rule such as "X wins over Y" warrants checking whether two mechanisms could
share one owner; it is not proof of a defect. Preserve intentional language
bindings, aliases, and scoped overrides with documented precedence.

## Findings

For each finding, identify the location and evidence, the consequence for a
consumer or implementer, and the smallest useful correction. Separate defects
from open questions and optional improvements; prioritize design consequences
over typos and wording. Cite canonical sections or concrete counterexamples
rather than relying on preference.

Apply the "Principles" section of `architecture-design` when evaluating corrections; use its full procedure when proposing changes to subsystem ownership or interfaces.
When proposing a new mechanism, first show why deleting a requirement,
narrowing an existing mechanism, or moving responsibility to its existing owner
is insufficient.

If no material issue is supported, say so and name the review's limits. Do not
manufacture findings to fill categories or prescribe a rewrite when a local
correction suffices.
