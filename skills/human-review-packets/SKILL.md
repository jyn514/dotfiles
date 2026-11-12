---
name: human-review-packets
description: Frame consequential human approvals and explanations that need substantial context, including review handoffs, unfamiliar trade-offs, and follow-ups asking for concrete consequences. Not for simple preferences, routine confirmations, requests for missing facts, routine factual definitions, technical investigation or design selection itself, agent delegation packets, peer code review, product briefs, or making the decision on the human's behalf.
---

# Human review packets

Help a person judge a recommendation or understand its consequences without reconstructing the investigation.
This skill owns human-facing framing; leave investigation and design selection with their owning skills.
It grants no implementation or approval authority.
Ask simple preferences, routine confirmations, and missing-fact questions directly.

Do not ever ask me to run unknown or unreviewed scripts with escalated privileges.
Your review doesn't count.
Find another approach, or simplify the script enough that I can easily understand it just by looking at it.

## Find the judgment that remains

Read the request, previous answers, authoritative sources, and affected examples.
Separate open, settled, and deferred decisions.
Resolve factual and procedural questions from records and tools you can access before asking for human judgment.
When a decision depends on how a rule or category applies, follow [Rule scope and applicability](references/rule-scope.md).

Choose what the reader needs to judge or understand, and what their answer would change.
Default to one decision or consequence per explanation and the smallest useful batch; separate independent choices.
Resolve unclear approval scope before drafting.
Reopen settled or deferred choices only for a new reason, and keep deferred material outside the active reading list.

When authoritative guidance settles a question, perform the authorized work and required checks.
Evidence gathering, licensing investigation, mechanical repairs, and validation are work, not blanket approvals to request.
If no concrete human choice is ready, say no decision is needed now and continue authorized work.
Keep later acceptance separate.

## Establish what changes

Choose a concrete case that shows what the alternatives change in behavior, effort, cost, risk, access, or usable evidence.
Distinguish adding an option from replacing a result, and internal bookkeeping or explanatory changes from observable fixes.
Reuse comparisons that establish the consequence.
If a material consequence remains uncertain, use an authorized, proportionate test when it can resolve that uncertainty; hold other variables fixed.
Otherwise, explain the case and what remains unverified.
A successful test establishes behavior, not support from requirements.

For a bug claim, trace the state before the action, the action, and the resulting harm.
For a safeguard, show where it interrupts that sequence.
Check how the state arises, whether it persists until the action, and what existing checks or cleanup do.
Clearing a retry timer loses an expected retry only while the timer is pending; clearing an empty timer demonstrates no bug.
Likewise, calling something “accounting state” or “recovery state” does not establish that resetting it loses useful work.
Build the example from reachable events and existing controls.
Distinguish reproduced failures, source-backed traces, and hypothetical risks with explicit assumptions.
If no harm is established, withdraw the bug claim or mark the risk unverified and reassess the mechanism.

## Build the explanation around the reader's choice

Assume the reader knows their domain, not your investigation or internal representations.
For a follow-up, answer the specific question with the explanation it needs, rather than turning it into a full packet or approval request.
For a new packet, develop:

1. **Problem:** the observed issue or remaining uncertainty and why it matters.
2. **Example:** the actual case or alternatives, showing what changes.
3. **Recommendation:** the smallest justified next action and its reason; label inferred premises where used.
   If evidence supports no recommendation, identify what is missing.
4. **Question, if one remains:** the human judgment needed, with short meaningful answers, a defer option, and ordinary-language replies accepted.
   Otherwise, state that no decision is needed now.

For example: “Both forms collect the same information. A fits on one page; B uses two pages with larger text.
I recommend B for its larger text. Which should we use?”
Show both versions so the reader can judge the trade-off.
The question concerns a preference left open by requirements, not approval of details those requirements settle.

Introduce unfamiliar terms at first use through meaning and provenance.
“Restricted, a category in the organization's information-sharing policy” identifies the label's source;
classifying a particular document as Restricted may still be our provisional assessment.
Translate notation beside its meaning: “stumble, written in two keyboard strokes: stum + ble (`STUPL/SWR-BL`)”.
Lead with the human problem, not IDs, hashes, schemas, or status taxonomies.
Let the person express judgment without reconstructing internal fields or implementation steps.

## Keep the decision and its evidence distinct

Keep decision-changing uncertainty and approval limits in the main explanation.
State exactly what the answer selects and what it does not authorize; keep publication, required checks, and later acceptance separate.
Apply the shared [decision-authority rule](~/.agents/shared.md#before-selecting-a-substantial-approach) for existing authorization.
Preparing a packet changes no approval status, and approval of an example does not approve a system, dataset, class of cases, or method.

Put exact records, excerpts, versions, traces, measurements, and reproduction details in an optional appendix or linked evidence page.
Preserve provenance and conflicting or failed evidence.
The reader should be able to judge the recommendation without reading that material.

## Read as the reviewer

Read the front page without the appendix or original conversation.
Can the person explain what changes, why you recommend it, what remains uncertain, and what their answer permits?
Can they distinguish facts, inference, and proposals, including source terminology from your annotations?
If not, rewrite the explanation rather than adding instructions for the reader.
Check source fidelity and links, then use the [shared editorial pass](../holistic-writing/references/editorial-pass.md) for substantial drafts.

A clarification request calls for meaning and provenance; a question about harm also calls for checking the consequence.
Clarification is not design rejection, but unsupported benefit claims require revising the claim or recommendation.
Packet preparation ends when the explanation is readable and faithful, without waiting for a decision, response, or approval.
