---
name: human-review-packets
description: Frame consequential human approvals and explanations that need substantial context, including review handoffs, unfamiliar trade-offs, and follow-ups asking for concrete consequences. Not for simple preferences, routine confirmations, requests for missing facts, routine factual definitions, technical investigation or design selection itself, agent delegation packets, peer code review, product briefs, or making the decision on the human's behalf.
---

# Human review packets

Help a person judge a recommendation or understand its consequences without reconstructing the investigation.
Use this workflow for consequential approvals or explanations that need substantial context.
Ask simple preference questions, routine confirmations, and requests for missing facts directly.
This skill owns selection and framing of human review questions and explanations, not the underlying investigation or design selection.
Use the owning investigation or design skill for that work.
Use [documentation placement](../technical-docs/references/placement.md) to choose a documentation owner and destination.
Use `holistic-writing` for whole-artifact authoring and reader experience.
It does not grant implementation or approval authority.

## 1. Resolve what needs human judgment

Start with the current request and the decisions already made.
Read previous answers, authoritative sources, and affected examples.
Separate settled decisions, deferred decisions, and questions that are still open.

### Resolve facts and scope first

Investigate factual or procedural questions you can answer yourself.
Do not ask a human to troubleshoot a tool, inspect records, or provide evidence you can retrieve.

Before calling something a contradiction, check the relevant sources and examples.
If the decision depends on how a rule or category applies to a case, follow [Rule scope and applicability](references/rule-scope.md) before asking a human to resolve it.

### Establish the consequence

Explain why the choice matters: what changes in behavior, effort, cost, risk, access, or the evidence people can rely on?
When alternatives can be tested, compare them with other variables fixed and show the actual difference.
Otherwise, give a concrete case and say what remains unverified.
Distinguish adding an option from replacing an existing result.
A successful test does not prove that requirements support the alternative.
If a change affects only explanation or internal bookkeeping, say so; do not claim it fixes observable behavior.

For a claimed bug, trace a reachable sequence: the relevant state before the action, what the action changes, and the resulting harm.
For a claimed safeguard, show the harmful sequence it prevents and where it intervenes.
Check how the state arises, whether it can still exist when the action runs, and which existing checks or cleanup already prevent the harm.
For example, clearing a retry timer loses an expected retry only if the timer is pending; clearing an empty timer does not demonstrate a bug.
Distinguish reproduced failures, source-backed traces, and hypothetical risks, and state assumptions explicitly.
Do not invent extra events or bypass existing checks to make the example work.
If no harm is established, withdraw the bug claim or mark the risk unverified and reassess the proposed mechanism.
A name such as “accounting state” or “recovery state” does not prove that resetting it loses useful work.

### Ask only for the unresolved decision

Ask only for judgment or intent that remains missing.
If authoritative guidance settles the issue, handle it as agent work within existing authorization and perform the required checks; do not ask for new approval.

Separate work from decisions needed now.
Evidence gathering, licensing investigation, mechanical repairs, and validation are not blanket approvals to request.
When no concrete human choice is ready, say that no decision is needed now and continue authorized work; this does not approve that work or later acceptance.
Ask a narrow question when evidence exposes one, and keep later acceptance reviews separate.

Do not reopen a settled choice or requeue a deferred approval without a new reason.
Keep deferred material outside the active reading list.

Default to one decision or consequence per explanation and the smallest useful batch.
State what the answer would change and what it would not authorize.
Resolve unclear scope before drafting.

## 2. Write the human-facing page

Assume the reader knows their domain, but not the investigation or its internal representations.
Explain unfamiliar specialized terms at first use, including their origin when that affects interpretation.
For example, “Restricted, a category in the organization's information-sharing policy” identifies where the label comes from;
whether a particular document belongs in that category may still be our provisional assessment.
Do not make a source-defined term look like terminology invented by the agent.
For a follow-up, answer the specific question directly and use only the parts below needed to explain it.
Do not turn a short clarification into a full packet or an approval request.
For a new review packet, lead with:

1. **Problem:** the observed issue or remaining uncertainty, and why it matters, in ordinary language.
2. **Example:** show the actual case, behavior, or alternatives, including what changes between them.
   Translate internal representations into something the person can inspect, and put notation beside its meaning.
   For example, write “stumble, written in two keyboard strokes: stum + ble (`STUPL/SWR-BL`)”, not just the technical notation.
3. **Recommendation:** state the smallest justified next action and its reason. Mark uncertain premises as inferred beside the explanation. If evidence supports no recommendation, say what is missing.
4. **One question, if a human choice remains:** ask for the decision directly. Offer short, meaningful answers, including defer, and accept ordinary-language replies. Otherwise, state that no decision is needed now.

For example, if two form designs both meet the documented requirements, a real preference question might be: “Both forms collect the same information. A fits on one page; B uses two pages with larger text. I recommend B for its larger text. Which should we use?” Show both versions so the reader can judge the trade-off. Do not request approval of details already settled by the requirements.

Do not lead with IDs, hashes, branch counts, schemas, status taxonomies, or fill-in forms. Do not make the reader reconstruct internal field values or implementation steps to express their judgment. If several independent choices remain, separate them; do not hide them inside one approval question.

## 3. Keep evidence available, not mandatory reading

Put exact record identities, source excerpts, versions, traces, measurements, and reproduction details in an optional appendix or directly linked evidence page. Preserve provenance and conflicting/failed evidence.

Keep decision-changing uncertainty in the main explanation; an appendix must not hide an inferred premise, an untested alternative, or a narrow approval scope. Do not imply a tested example approves an entire system, dataset, class of cases, or method.

State exactly what a review answer selects; keep publication, required checks, and later acceptance separate from that decision.
Apply the shared [decision-authority rule](~/.agents/shared.md#before-selecting-a-substantial-approach) to determine existing authorization.
Packet creation itself changes no approval status.

## 4. Check the reading experience

Read only the front page, ignoring the appendix:

- Can the reader explain the problem and answer without IDs, traces, or the original conversation?
- Does the example show a reachable change to a useful result—not merely an internal-state reset—and make the recommendation understandable?
- Does this need human judgment, or can source inspection, implementation, or validation settle it?
- Are observed facts, inference, and proposed changes distinguishable? Does the reader know which terms come from the source and which annotations we supplied?
- If a decision remains, is there one clear question, with a real defer option and explicit scope? If none remains, does the page report the result without manufacturing a question?

When a reader asks what a term means, explain its meaning and provenance.
If they also ask why the behavior is harmful or the mechanism is needed, check the consequence rather than only defining the term.
A request for clarification is not rejection of the design, but finding no support for its claimed benefit requires revising that claim or recommendation.

If the front fails these checks, rewrite it rather than adding more instructions for the reader.
Check source fidelity and links, then use `holistic-writing` for whole-artifact editorial review of substantial drafts.
Stop when the packet is readable and faithful; no decision, response, or approval is required to finish preparing it.
