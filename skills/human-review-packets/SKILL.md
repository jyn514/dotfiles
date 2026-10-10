---
name: human-review-packets
description: Prepare small, readable decision packets for a human reviewer. Use when asked to prepare review packets, explain choices needing human approval, or rewrite a review handoff that is too dense or agent-oriented. Not for agent delegation packets, peer code review, product briefs, or making the decision on the human's behalf.
---

# Human review packets

Help a person make a specific decision without reconstructing the investigation. This skill owns selection and framing of human review questions; use `technical-docs` for placement and reader-oriented authoring. It does not grant implementation or approval authority.

## 1. Find the actual human decision

- Read the current request, previous answers, authoritative sources, and affected examples. Distinguish settled decisions, deferred decisions, and genuinely unanswered questions.
- Resolve factual or procedural issues you can investigate yourself. Do not ask a human to troubleshoot a tool, inspect records, or supply evidence you can retrieve.
- Before declaring a contradiction, read the surrounding explanation, related requirements, and examples. Check directly documented behavior before inventing elaborate explanations or case-specific exceptions. An apparent omission may be explained elsewhere. Separate explicit statements from your reconstruction; a plausible explanation is not source authority.
- Audit the premises of the apparent conflict. A label or category can come from an authoritative source while its application to a particular case comes from an unreviewed agent assessment. Identify both origins; do not treat the assessment as an established source fact. If a requirement's applicability depends on it, state that uncertainty.
- Ask only for judgment or intent that remains missing. If applicable authoritative guidance settles the issue, handle it as agent work within existing authorization, with the required checks—not a new approval question.
- Establish why the choice matters: what changes in behavior, effort, cost, risk, access, or the evidence people can rely on? When alternatives can be tested, compare them with unrelated variables fixed and show the actual difference. Otherwise, use a concrete case and state what remains unverified. Distinguish adding an option from replacing an existing result. A successful test does not establish that an alternative is supported by the requirements. If a change affects only explanation or internal bookkeeping, say so; do not claim it fixes observable behavior. Choose examples that demonstrate the consequence you are asking the reader to judge.
- Separate remaining work from decisions needed now. Evidence gathering, licensing investigation, mechanical repairs, and validation are not blanket approvals to request from the human. When no concrete human choice is ready, say none is needed now and continue authorized work; that is not approval of the work or later acceptance. Bring a narrow question when the evidence exposes one; keep later acceptance reviews separate.
- Do not reopen a settled choice or requeue a deferred approval without a new reason. Keep deferred material outside the active reading list.

Default to one decision per packet and the smallest useful batch. Identify what the answer would change and what it would not authorize. If that scope is unclear, resolve it before drafting.

## 2. Write the human-facing page

Assume the reader knows their domain, but not the investigation or its internal representations. Explain unfamiliar specialized terms at first use, including their origin when that affects interpretation. For example, “Restricted, a category in the organization's information-sharing policy” identifies where the label comes from; whether a particular document belongs in that category may still be our provisional assessment. Do not make a source-defined term look like terminology invented by the agent. Lead with:

1. **Problem:** what is uncertain and why the choice matters, in ordinary language.
2. **Example:** show the actual case, behavior, or alternatives, including what changes between them. Translate internal representations into something the person can inspect.
3. **Recommendation:** state the smallest justified next action and its reason. Mark uncertain premises as inferred beside the explanation. If evidence supports no recommendation, say what is missing.
4. **One question, if a human choice remains:** ask for the decision directly. Offer short, meaningful answers, including defer, and accept ordinary-language replies. Otherwise, state that no decision is needed now.

For example, if two form designs both meet the documented requirements, a real preference question might be: “Both forms collect the same information. A fits on one page; B uses two pages with larger text. I recommend B for its larger text. Which should we use?” Show both versions so the reader can judge the trade-off. Do not request approval of details already settled by the requirements.

Do not lead with IDs, hashes, branch counts, schemas, status taxonomies, or fill-in forms. Do not make the reader reconstruct internal field values or implementation steps to express their judgment. If several independent choices remain, separate them; do not hide them inside one approval question.

## 3. Keep evidence available, not mandatory reading

Put exact record identities, source excerpts, versions, traces, measurements, and reproduction details in an optional appendix or directly linked evidence page. Preserve provenance and conflicting/failed evidence.

Keep decision-changing uncertainty in the main explanation; an appendix must not hide an inferred premise, an untested alternative, or a narrow approval scope. Do not imply a tested example approves an entire system, dataset, class of cases, or method.

A review answer alone selects only the stated decision; it does not expand implementation authority, waive checks, authorize publication, or imply approval of adjacent questions. Implementation requires existing authorization or a separate explicit instruction; do not ask again for work already authorized. Packet creation itself changes no approval status.

## 4. Check the reading experience

Read only the front page, ignoring the appendix:

- Can the reader explain the problem and answer without IDs, traces, or the original conversation?
- Does the example show a concrete consequence and make the recommendation understandable?
- Does this need human judgment, or can source inspection, implementation, or validation settle it?
- Are observed facts, inference, and proposed changes distinguishable? Does the reader know which terms come from the source and which annotations we supplied?
- If a decision remains, is there one clear question, with a real defer option and explicit scope? If none remains, does the page report the result without manufacturing a question?

When a reader asks what a term means, explain its meaning and provenance before reconsidering the design. Confusion alone is not rejection of the mechanism or evidence that it is wrong.

If the front fails these checks, rewrite it rather than adding more instructions for the reader. Check source fidelity and links, then use `tighten-docs` for substantial drafts. Stop when the packet is readable and faithful; no decision, response, or approval is required to finish preparing it.
