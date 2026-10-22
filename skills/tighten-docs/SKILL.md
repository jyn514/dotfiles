---
name: tighten-docs
description: Make docs, specs, prompts, instructions, and skills clearer and shorter. Use for explicit prose-tightening requests and before completion after creating a substantial document or substantially rewriting documentation, specifications, prompts, instructions, or skills. For short documents or localized edits without an explicit tightening request, review prose directly without loading this skill. Do not apply to code, generated files, or machine-owned data.
---

# Tighten Docs

Improve the reading experience without weakening what the document must preserve.
A clearer progression can matter more than shorter sentences.
Preserve behavior-changing requirements, safety constraints, public API details,
validation steps, design posture, and examples that prevent likely mistakes.

## Delegate the prose pass

The main agent delegates this skill to a small-model subagent to reduce subscription usage.
Use [delegation](../delegation/SKILL.md) for the assignment and integration.
Supply the reader's task, the reading problem to address, and the requirements to preserve.
For document-level problems, supply the whole artifact rather than only selected hunks.
The assigned subagent runs the workflow directly, without further delegation, and returns its reading judgment and proposed edits.
The parent checks the complete revision against the original reading problem; individually defensible edits do not establish that the whole reads well.
If small-model delegation is unavailable, the main agent runs the workflow directly and reports that limitation.
One completed pass meets the post-rewrite requirement for the reviewed files, including this skill. Check corrections in the same pass; prose edits made during the pass do not require another pass.

## Workflow

1. Read the artifact as a whole, in the form its reader encounters.
   Identify the reader's task and whether the document supports continuous reading, lookup, or a sequence of actions.
   Describe the sustained experience: does the thought develop, or do lists, qualifications, repeated restarts, or a mechanical cadence make reading laborious?
   A legitimate use for every section does not establish that the whole earns its length.
   Then identify the document type and authority:
   - Spec: preserve normative requirements and observable behavior.
   - Docs: preserve user-facing facts, commands, caveats, and task flow.
   - Skill: preserve the triggering description, non-obvious procedure, and references needed for progressive disclosure.
   - Prompt/instructions: preserve priority, constraints, and decision rules.

2. Mark text needed by the artifact's readers:
   Judge preservation against the reader's task, not merely the old text's existence. An implementation detail already owned by code need not remain in operator documentation unless it affects a reader's decision, action, or necessary understanding. Preserve the observable contract and needed rationale, not every literal detail of its implementation.
   - MUST/SHOULD/MAY style obligations, even if not capitalized.
   - Inputs, outputs, defaults, edge cases, errors, and compatibility promises.
   - Concrete examples that disambiguate syntax or behavior.
   - Links, file paths, commands, and validation criteria.
   - Design intent that constrains future choices: tradeoffs, rejected alternatives, compatibility posture, ownership boundaries, safety rationale, and "why not" explanations.
   - Rationale, examples, and analogies that change a future decision, define the reader's mental model, explain why a section exists, or prevent a repeated mistake — not rationale that only says a rule is good or recommended.

3. Choose the scale of the revision.
   For a document-level problem, rebuild the reading path before polishing sentences:
   - When an abstraction is hard to follow without a concrete distinction, introduce the example first.
   - Combine repeated introductions or instruction sets into one developing explanation or action sequence.
   - Put constraints beside the decisions they govern.
     Keep required warnings at the point of action; group other exceptional cases so they do not repeatedly interrupt the ordinary path.
   - Preserve useful independent lookup paths where the genre calls for them.

   For a local problem, retain the working structure and revise the affected passage.
   Preserve requirements and useful reasoning, not their existing arrangement.

4. Audit passages within the chosen structure.
   Assess individual sentences and claims, not whole sections as indivisible `keep`.
   A section containing requirements or important rationale may still contain redundant sentences.
   For substantial revisions, list candidate hunks and classify each as `duplicate`, `structural simplification`, `clearer rewrite`, `risky compression`, `word shave`, or `keep`.
   For a local edit, use these distinctions without requiring a formal inventory.
   - Eligible by default: `duplicate`, `structural simplification`, `clearer rewrite`.
   - `risky compression` is eligible only when the replacement keeps the concrete reason, failure mode, or boundary.
   - Never edit `word shave` or `keep`.
   - A hunk is eligible only if its win can be named without saying "shorter": duplicate removed, ambiguity fixed, structure clarified, reference made more direct, or an overlong sentence made easier to parse.

   Consider linked changes together: moving a definition can make an earlier explanation redundant or require a different transition.
   Preserve necessary meaning, not every occurrence of it.

   Reject these micro-edits:
   - removing small orientation words, merging adjacent sentences, or swapping in shorter synonyms;
   - collapsing several short sentences into one unless the result is easier to scan and keeps the emphasis;
   - deleting framing words ("intended", "detailed", "like this") unless the sentence is materially clearer without them.

   Classify repeated guidance before cutting it:
   - **Duplicate policy** states the same requirement authoritatively in several places. Keep one canonical owner and replace other copies with direct, task-specific references.
   - **Duplicate routing** exposes the same owner from different entry points or indexes. Usually keep it; readers and small models need local routes more than a perfectly normalized document graph.
   - **Duplicate context** briefly repeats a safety constraint or prerequisite where a reader acts.
     Name the concrete misunderstanding or unsafe action it prevents; otherwise test deletion or a direct reference.

   Before marking policies as duplicates, compare required behavior and conditions,
   not just shared words. A priority ranking does not replace a direct instruction:
   “Prioritize clarity → precision → concision” ranks goals; “Use concise, clear
   language” directs writing style. Keep both.

   Reduce repeated text only when one source is clearly authoritative, every affected entry point links directly to it, the link says why the reader needs it, and no safety-critical constraint disappears at the moment of action. Prefer “Before source edits, follow the red/green workflow in `testing.md`” over “See `testing.md`.” Preserve deliberate two-level routing such as task → owner and owner → focused topic; flatten or add a short local guard when reaching the operative rule would otherwise require more than three hops.

5. Revise passages for the reading path you chose. Before deleting rationale, ask:
   - Would a future implementer decide differently without it?
   - Does it explain why a tempting alternative is rejected?
   - Does it define project posture, not just current behavior?
   - Does it prevent repeating a known mistake?

   If yes, retain or rewrite the rationale rather than deleting it.
   Keep the concrete reason: why an alternative was tempting, what made it fail, or what invariant or design choice the reader must preserve.
   Treat vivid vocabulary, concrete rejected alternatives, and exact role names as meaningful choices; keep their force when rewriting.

   Safe to cut:
   - Meta-commentary about the document's purpose when the heading already says it.
   - Competing authoritative copies of warnings, definitions, and command lists once the canonical owner and direct routes are clear.
   - Framing, transitions, or history that do not help the reader follow the subject, choose an action, or understand a governing decision.
   - Examples that prove the same point; keep the clearest or most edge-case-rich one.
   - Implementation detail in user docs, unless users need it to predict behavior.

   Tighten what remains:
   - Prefer imperative bullets for procedures.
   - When restructuring dense prose into bullets, group by concept or decision instead of making every sentence a separate item; keep dependent conditions together and separate normative rules from rationale or examples.
   - Use tables for comparisons or repeated fields when they make the relationships easier to see than paragraphs.
   - Merge near-duplicate sections under one heading.
   - "in order to" → "to"; "it is important to" → the action.
   - Use one term consistently; delete synonym tours.
   - Preserve precise, established domain terms; do not coin substitutes to avoid jargon. Explain specialist terms when intended readers may not know them.
   - Apply vocabulary rules in context: avoid banned metaphors, but do not mechanically replace an established technical use of the same word.
   - Keep headings specific, but do not explain the heading below itself.
   - Delete whole duplicate sentences rather than shaving words from good ones — word-shaving makes noisy diffs and weakens intent.

6. Validate:
   - Read the complete revision in order before inspecting the diff.
     Assess whether its progression, rhythm, and cumulative attention cost resolve the original reading problem.
     Useful content, fewer words, and individually improved passages are not sufficient evidence.
     If the same problem remains, reconsider the reading path rather than repeating a local trimming pass.
   - Then compare original and revised as prose. Restore wording, transitions, examples, or framing where the original reads better.
   - Before reporting missing or removed guidance, read the complete relevant section in both versions and check any route that replaced it.
     Cite the exact source location supporting the finding.
     A truncated output or incomplete excerpt does not establish absence; reread the bounded section before making that claim.
   - Account for removed requirements, exceptions, commands, paths, and example-only behavior. Preserve those needed by this artifact's readers or route them to their owner; preserve the reasons for unusual rules, tradeoffs, compatibility boundaries, and rejected alternatives that still govern the task.
   - For each removal, name the reason: duplicated guidance, unnecessary implementation detail, irrelevant content, or optional material whose benefit does not warrant its attention cost.
     Required coverage still applies; identify the canonical owner when removing a duplicate.
     Do not restore text solely because it existed before the edit or use relocation to hide safety constraints needed at the point of action.
   - Read each revised section standalone. If it says what to do but no longer gives enough context to choose correctly next time, restore the smallest framing example or analogy.
   - For each common entry point affected by a deduplication, read only that entry point and the documents it directly names. Confirm a reader can find the first action, applicable constraints, required validation, and any condition that routes to another owner.
   - Check vocabulary against the project's guidance: preserve precise domain terms, explain unfamiliar terms for the intended reader, and apply banned-word rules by meaning rather than matching words mechanically.
   - For every changed hunk, defend it as clearer, more accurate, or easier to use. If the only defense is "shorter" or "fewer words", revert it.
   - For substantial rewrites, look specifically for cuts that weakened reasoning, orientation, or voice; restore them even if the result is longer.
     Report actual reversions rather than meeting a quota.
   - For large reviews, report actual inspected scope and any excluded or unread material.
     Support a no-cut verdict with a whole-document reading judgment as well as exact quotes of the strongest rejected candidates.
     Explain why the cumulative experience works, not just why each passage has a purpose.
     Say "No further eligible cuts identified," not "already tight enough" or a claim that no possible cuts remain.
     When that verdict lacks concrete support, the main agent arranges a bounded independent whole-document reading through the delegation skill, or reports that independent review is unavailable.
     If the challenge finds missed eligible cuts, withdraw the verdict and re-audit the affected scope before renewing it.
   - Confirm references still point to existing files or sections.
   - For skills: validate linked reference paths and examples, and confirm the YAML description still contains every trigger context — body-only trigger guidance is invisible until after selection.

## Examples

A structural rewrite: a tutorial repeats account setup in its quickstart, configuration guide, and troubleshooting section.

- Before: overview → setup and first task → setup and configuration → setup and troubleshooting.
- After: overview → setup → first task → configuration → troubleshooting.

Keep one setup explanation and link to it from sections that support independent lookup.
Keep warnings beside the actions that need them.
Each stage now continues from the last instead of repeating the preparation; polishing the repeated setup paragraphs separately would miss this improvement.

A local cut: consolidate the same contract under different headings.

> Shape: Declaration maps are keyed by name. A user value wholly replaces the bundled value at the same key.
>
> Merge rule: User declarations add new keys and wholly replace bundled values at matching keys; missing user keys retain bundled values.

Change Shape to:

> Declaration maps are keyed by name; see Merge rule for adding and overriding declarations.

Keep Merge rule unchanged.
Calling one copy "requirements" and the other "mechanics" does not make the replacement policy distinct.
Shape retains the local editing task and routes its semantics to one canonical owner.

A cut to reject. The shorter version reads fine but deletes the actual instruction:

> Search for an existing helper of the same shape before adding one.

> ~~Search for an existing helper before adding one.~~

"Of the same shape" is the rule, not filler — without it the reader searches by name and misses the match. No duplicate removed, no ambiguity fixed; the only win is fewer words. Leave it.

## Skill-Specific Rules

- Keep `SKILL.md` procedural and short. Move bulky examples or variant detail to directly linked reference files, read only when needed.
- Delete generated template text completely; do not add README, changelog, quick-reference, or process notes to a skill.

## Output

When reporting the edit, mention:

- what changed in the overall reading experience and what evidence supports that judgment;
- what was shortened or reorganized;
- design intent or rationale preserved despite verbosity;
- rationale removed because it was duplicate or non-actionable;
- cuts reverted during self-review because they weakened clarity or design intent;
- any ambiguity that blocked a stronger cut.
