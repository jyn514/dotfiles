---
name: holistic-writing
description: Author, substantially revise, or editorially review whole prose artifacts, including reports, essays, prompts, instructions, skills, and documentation. Use whenever creating a new standalone prose artifact, regardless of length, and for selection, explanatory development, causal relationships, diction, rhythm, voice, factual fidelity, or the complete reading experience. Specialized owners retain authority over substance and behavior. Not for documentation placement or tree restructuring, design selection, human-owned product briefs, or bounded local polishing; use the relevant owner or tighten-prose.
---

# Holistic writing

Write for readers without the originating conversation, investigation, or design session.
This skill owns what the artifact explains, how its explanation develops, and how the prose reads.
Completeness and extractable facts do not establish that the writing is worth following.
Use the same editorial criteria when writing and reviewing: prose that needs revision does not become good because a reviewer can reconstruct its meaning.

## Scope and authority

For a routed editorial pass, use the established reader, purpose, requirements, and factual evidence.
Review the artifact rather than restarting its investigation, design, or authoring workflow.
Specialized owners decide its substance; an editorial pass does not expand permission to change it.
A review request does not authorize prose edits.
For review-only work, report findings, evidence, consequences, and the smallest useful corrections.
For authoring with no named artifact, establish the intended reader, purpose, and deliverable before drafting.
Ask when missing context would materially change the result rather than inventing its audience or authority.

Use adjacent owners only for their tasks, not as compulsory stages of this pass:

- `technical-docs` owns documentation-specific authoring decisions; placement alone uses its [placement reference](../technical-docs/references/placement.md).
- `readme-writing` owns introductory README writing and review, not every file named README.
- `reorganize-docs` owns existing documentation trees, page splits, renames, consolidation, and navigation.
- `new-tool-development` owns its tool lifecycle and human-authored product briefs.
  Agents may review those briefs and add only the TODO comments it permits, not write or rewrite brief prose.
- `requirements-definition` owns requirements authoring from an approved product brief.
- `human-review-packets` owns selection and framing of human decision questions and approval handoffs.
- [Design review](../review/references/design.md) owns review-only consistency and completeness analysis of designs or specifications.
- `skill-authoring` owns skill behavior, discovery, and procedure; this skill owns written presentation without silently changing those decisions.
- `typst` owns Typst syntax; use it when the artifact needs that markup, not for every prose review.
- `tighten-prose` owns bounded sentence- and paragraph-level polishing within an established explanation.

If an owner is unavailable, preserve its boundaries, state the limitation, and do not claim that its specialized review occurred.

## 1. Read the artifact and establish its authority

Read the complete current artifact, its relevant entry points, authoritative inputs, and representative uses.
For creation, inspect the material the new artifact must explain and any established destination or form.
For an editorial pass, retain the destination unless relocation is requested.
Before adding documentation, use the placement reference; do not force essays, reports, or instructions into documentation forms.

Before interpreting craft, encounter the reading experience: what comes to matter, what you expect, and what stays with you afterward.
Distinguish pleasure or friction in following the prose from what readers come to understand and how they feel about the subject or themselves.
Be specific about whether a detail changes their mental model, their feelings, or both.
Precise understanding, quiet satisfaction, curiosity, changed appreciation, and felt danger can all matter; neither positive affect nor a tidy mechanism or plot account substitutes for the effect.
When a revision is merely smoother, or an explanation seems clear but its reading judgment feels thin, read the [contrasting readings and revisions](references/reading-examples.md) before choosing edits.

Readers skim headings, search for terms, skip familiar material, and return to earlier passages.
Read the whole artifact to assess it, then trace the paths its readers are likely to take for their tasks.
Check whether they can recognize where to go and understand what they find without having read every preceding word.
A reference can serve a reader who wants one answer; an argument may need sustained reading to develop its thought.

Establish what is observed, selected, provisional, and unresolved.
Do not turn conversation context, search snippets, generated output, or an analysis script into unexplained authority.
Preserve provenance for measurements and reconstructed decisions.
Your review limits are not facts about the author's investigation.
Do not add a first-person claim such as “I have not tested this” unless supplied evidence establishes it.
When reviewing, describe the language and its reading effects rather than inferring the author's identity or effort.
A low-effort impression concerns the presentation; it does not establish who wrote the prose or how hard they worked.

## 2. Choose and develop what matters

Identify the reader's task, assumed background, and the understanding or action the artifact must support.
Make its title and opening intelligible without session context.
Define named proposals or policies rather than relying on their labels.
Explain unfamiliar specialist terms before consequential use while preserving precise established domain terms.
Distinguish facts, decisions, proposals, examples, and unresolved questions.

Choose what deserves attention and explain the connections that matter to that reader.
Your judgment can be wrong; refusing to make it leaves the reader to decide, often with less context and her own risk of error.

When the artifact supports a choice, explain what each relevant option changes, what the reader gains or gives up, and which circumstances make that difference matter.
An inventory of mechanisms, settings, or data does not by itself establish that the prose helps the reader decide.
Trace the connection from the described behavior to its consequences for this reader; do not substitute a recommendation without reasons for that explanation.
Credit connections the prose makes through warranted inference: not every implication must be explicit, and not every artifact needs an exhaustive comparison or a table.
When reviewing, identify the consequential connection the reader must supply and why that effort matters to the stated task.
Stay within the supplied evidence; do not invent missing product facts or treat an unverified factual premise as an established defect.

For an explanatory distinction, identify what it helps these readers understand or decide.
If neither side changes their understanding or choice, it is a distinction without a difference: remove or rework it when writing, and count its wasted attention or false emphasis against the prose when reviewing.
A corrective contrast needs a plausible misconception and an explanation that gives these readers reason to reconsider; do not invent confusion to defend it.

Develop a hypothesis as a hypothesis, explaining its proposed mechanism and uncertainty without claiming confirmation.
For a nontrivial mechanism, explain the problem, show a concrete example or trace, then explain the solution and its invariant.
Introduce one conceptual layer at a time, with plain-language meaning before notation and a worked example before an algorithm when useful.
Preserve deliberate concrete-to-general development.
A reader may understand a particular case before learning the broader concept or its name.
Before recommending an earlier definition, identify what the reader cannot understand at that point without it; needing the concept later does not establish that it belongs earlier.
Explain why a schema or invariant exists before listing its fields.
Do not force every artifact into a design-document progression or require a worked example of every application.

Give a thought room to develop.
Joining sentences or packing definitions together can preserve facts while making their connections harder to follow.
Concision makes good use of attention; it need not mean compressing the prose.
Use the space that helps the reader follow, without rewarding either length or brevity on its own.

For important measurements, identify the population or denominator, what was counted, input revision or time range, method, and limitations.
Explain what the number demonstrates and whether it is provisional or an acceptance constant.
Comparisons need comparable results for the alternatives, not merely a winning conclusion.
Use labeled tables or definition lists rather than an uninterrupted wall of figures.
Avoid wide Markdown tables; use bullets or short subsections for prose, commands, or more than three columns.

## 3. Revise connected passages without losing meaning

Identify the reading problem before choosing edits: a buried relationship needs different work from an awkward sentence.
Revise connected passages when selection or arrangement causes the difficulty; retain what already works.
Judge diction, rhythm, emphasis, selection, and development, not words removed or paragraphs joined.
Preserve effective voice, deliberate casing, fragments, idiom, and precise terms rather than normalizing them for consistency.
Voice also lives in particular attention, selection, connections, and implications, not only verbal personality.
Apply vocabulary bans by meaning rather than word matching.

Read headings on their own: what subject or task would a reader expect under each one?
Compare that promise with what the section actually does; regroup or rename when they differ.
For example, a section about reporting a decision should describe the expected response, not introduce criteria for making the decision.
Preserve needed lookup paths, not necessarily existing headings or section boundaries.

Shape each paragraph around a developing thought, contrast, or reading effect; sharing a broad topic is not enough to bind sentences together.

Preserve governing requirements, authority, priority, conditions, exceptions, commands, paths, defaults, and validation.
Moving an unconditional rule under “When tests fail” makes it appear conditional even if its words do not change.
Keep dependent conditions together; separate independent rules, exceptions, and validation steps when they obscure one another.
Distinguish rationale and examples from normative behavior.
Keep required warnings beside the actions they govern.
When removing duplicated instructions, apply the [consolidation check](references/consolidation.md).
For skills, preserve discovery triggers and check linked references and examples.

Keep rationale, rejected alternatives, and examples that guide a future choice or prevent a likely mistake.
Explanations that merely praise a rule can go; code-owned detail need not remain unless readers need it to act or understand.
Do not turn example-only behavior into a default or guarantee.
Do not remove necessary detail merely to shorten a document; move it later, label it, or derive it from a clearer authority.

## 4. Read the complete result against the original

Read the complete artifact in the form its reader encounters, including dull stretches.
Read the complete result before defending individual edits, then compare it with the original as prose.
Restore anything that reads better in the original.
Also skim the result and read revised sections independently, following the routes readers need for their actions and constraints.
A requirement being present somewhere is not enough if a section label sends its reader elsewhere.
Useful sections, preserved facts, and individually defensible edits do not establish that the whole reads well.
A revision can improve without fully solving the original reading problem; identify what remains difficult.

Check that additions serve this reader and do not repeat another owner.
Check that terms, numbers, examples, single-item cases, and composed or multistage cases remain understandable and consistent.
For instructions or contracts, check that readers can act without inventing policy.
Use representative original/revised passages and sustained patterns to support the reading judgment, not an edit tally.
Explain consequential preservation decisions, actual reversions, uncertainty, and unread or excluded scope.
Before claiming guidance is missing, read the complete relevant sections in both versions and follow replacement routes; cite exact locations.

Leave the artifact unchanged when no considered revision earns its cost.
Compare the original with the strongest concrete alternative considered and identify unresolved reading problems.
“Every section has a purpose” or “the evidence is findable” does not settle how the writing reads.
This verdict concerns the alternatives considered, not whether a better version is possible.
If support is insufficient, arrange a bounded independent whole-artifact reading when available, or report that limitation.
If it finds a missed improvement, reconsider the affected scope rather than defending the earlier verdict.
Make corrections within this pass; do not recursively invoke the workflow because its output changed.
Completing a pass does not certify writing quality.

## 5. Validate and finish

For creation or edits, validate the final consumer-visible representation, not only source syntax.
Compile or render when relevant tooling exists, check changed links and examples, and run applicable repository documentation checks.
Do not edit generated output directly.
Report failures, unavailable checks, skipped surfaces, and residual uncertainty.
Use `tighten-prose` only for a remaining local problem, not as a mandatory second pass or a substitute for whole-artifact judgment.
Distinguish the reading judgment from technical or operational checks actually performed.

Creation or revision is complete when the whole-artifact judgment is supported and unresolved reading problems are identified.
The intended reader must be able to understand and use the result without the originating conversation.
Give consequential claims an authority or state their uncertainty.
Applicable validation must pass or have a reported limitation; required repository checks must pass.
For review-only work, finish with prioritized findings, evidence, consequences, smallest corrections, and explicit review limits.
Do not imply a rendered artifact was inspected unless rendering was relevant and actually performed.
