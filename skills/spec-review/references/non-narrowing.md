# Non-narrowing check

Use this focused check when a concrete question concerns whether a contract narrows governing requirements, supported cases, or permitted explanation modes.
It is owned by `spec-review`; consulting it does not start a full specification-contract audit.

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
