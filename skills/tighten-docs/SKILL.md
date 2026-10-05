---
name: tighten-docs
description: Make docs, specs, prompts, instructions, and skills clearer and shorter while preserving required meaning, examples, rationale, constraints, and trigger behavior. Use for explicit prose-tightening requests and before completion after creating a substantial document or substantially rewriting documentation, specifications, prompts, instructions, or skills. For short documents or localized edits without an explicit tightening request, review prose directly without loading this skill. Do not apply to code, generated files, or machine-owned data.
---

# Tighten Docs

Shorten without weakening. Treat "shorter" as subordinate to "better."
Preserve behavior-changing requirements, safety constraints, public API details,
validation steps, design posture, and examples that prevent likely mistakes.

## Delegate the prose pass

The main agent delegates this skill to a small-model subagent to reduce subscription usage. It supplies the owned files or hunks, the requested change, and requirements to preserve.
The assigned subagent runs the workflow directly, without further delegation, and returns its edits for review.
The main agent reviews the returned diff and completes the required checks. If small-model delegation is unavailable, the main agent runs the workflow directly and reports that limitation.
One completed pass meets the post-rewrite requirement for the reviewed files, including this skill. Check corrections in the same pass; prose edits made during the pass do not require another pass.

## Workflow

1. Identify the document type and authority:
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

3. Audit before editing. List candidate hunks; classify each as `duplicate`, `structural simplification`, `clearer rewrite`, `risky compression`, `word shave`, or `keep`.
   - Eligible by default: `duplicate`, `structural simplification`, `clearer rewrite`.
   - `risky compression` is eligible only when the replacement keeps the concrete reason, failure mode, or boundary.
   - Never edit `word shave` or `keep`.
   - A hunk is eligible only if its win can be named without saying "shorter": duplicate removed, ambiguity fixed, structure clarified, reference made more direct, or an overlong sentence made easier to parse.

   Do not edit a section unless most planned changes are eligible cuts. If the only available reductions are posture/rationale cuts or small line-count wins, report that the section is already tight enough — prefer no edit over a marginally shorter one.

   Reject these micro-edits:
   - removing small orientation words, merging adjacent sentences, or swapping in shorter synonyms;
   - collapsing several short sentences into one unless the result is easier to scan and keeps the emphasis;
   - deleting framing words ("intended", "detailed", "like this") unless the sentence is materially clearer without them.

   Classify repeated guidance before cutting it:
   - **Duplicate policy** states the same requirement authoritatively in several places. Keep one canonical owner and replace other copies with direct, task-specific references.
   - **Duplicate routing** exposes the same owner from different entry points or indexes. Usually keep it; readers and small models need local routes more than a perfectly normalized document graph.
   - **Duplicate context** briefly repeats a safety constraint or prerequisite where a reader acts. Keep it when removing it would make the section unsafe or misleading in isolation.

   Reduce repeated text only when one source is clearly authoritative, every affected entry point links directly to it, the link says why the reader needs it, and no safety-critical constraint disappears at the moment of action. Prefer “Before source edits, follow the red/green workflow in `testing.md`” over “See `testing.md`.” Preserve deliberate two-level routing such as task → owner and owner → focused topic; flatten or add a short local guard when reaching the operative rule would otherwise require more than three hops.

4. Cut, then rewrite for density. Before deleting rationale, ask:
   - Would a future implementer decide differently without it?
   - Does it explain why a tempting alternative is rejected?
   - Does it define project posture, not just current behavior?
   - Does it prevent repeating a known mistake?

   If yes, tighten instead of cutting. A rationale sentence is load-bearing when it names a tempting rejected design, a concrete failure mode, project posture ("user-space over core knobs"), an operational invariant ("the graph stays correct by default"), or a motivating example that helps readers pick the right abstraction later. When compressing it, keep the smallest sentence that says why the alternative was tempting, what failure made it wrong, and what boundary the accepted design preserves. Treat vivid vocabulary, concrete rejected alternatives, and exact role names as sticky: do not generalize them unless the replacement keeps the same force.

   Safe to cut:
   - Meta-commentary about the document's purpose when the heading already says it.
   - Competing authoritative copies of warnings, definitions, and command lists once the canonical owner and direct routes are clear.
   - Apologies, motivational language, transition paragraphs, historical narrative.
   - Examples that prove the same point; keep the clearest or most edge-case-rich one.
   - Implementation detail in user docs, unless users need it to predict behavior.

   Tighten what remains:
   - Prefer imperative bullets for procedures.
   - When restructuring dense prose into bullets, group by concept or decision instead of making every sentence a separate item; keep dependent conditions together and separate normative rules from rationale or examples.
   - Replace paragraphs of conditionals with tables only when the table is shorter.
   - Merge near-duplicate sections under one heading.
   - "in order to" → "to"; "it is important to" → the action.
   - Use one term consistently; delete synonym tours.
   - Preserve precise, established domain terms; do not coin substitutes to avoid jargon. Explain specialist terms when intended readers may not know them.
   - Apply vocabulary rules in context: avoid banned metaphors, but do not mechanically replace an established technical use of the same word.
   - Keep headings specific, but do not explain the heading below itself.
   - Delete whole duplicate sentences rather than shaving words from good ones — word-shaving makes noisy diffs and weakens intent.

5. Validate:
   - Re-read original and revised side by side, as prose. If the old version has better force, rhythm, scanability, or framing, restore it.
   - Account for removed requirements, exceptions, commands, paths, and example-only behavior. Preserve those needed by this artifact's readers or route them to their owner; preserve the reasons for unusual rules, tradeoffs, compatibility boundaries, and rejected alternatives that still govern the task.
   - For each removal, name the reason: duplicated by a named owner, implementation detail owned by code and not needed by this reader, or content serving no reader decision, action, or necessary understanding. Do not restore text solely because it existed before the edit. Do not use relocation to hide safety constraints needed at the point of action.
   - Read each revised section standalone. If it says what to do but no longer gives enough context to choose correctly next time, restore the smallest framing example or analogy.
   - For each common entry point affected by a deduplication, read only that entry point and the documents it directly names. Confirm a reader can find the first action, applicable constraints, required validation, and any condition that routes to another owner.
   - Check vocabulary against the project's guidance: preserve precise domain terms, explain unfamiliar terms for the intended reader, and apply banned-word rules by meaning rather than matching words mechanically.
   - For every changed hunk, defend it as clearer, more accurate, or easier to use. If the only defense is "shorter" or "fewer words", revert it.
   - After the first pass, name at least one reverted cut, or state explicitly that every hunk is a clear improvement — then scrutinize harder. Treat restored cuts as success, not failure.
   - Confirm references still point to existing files or sections.
   - For skills: validate linked reference paths and examples, and confirm the YAML description still contains every trigger context — body-only trigger guidance is invisible until after selection.

## Example

A cut to make. The original buries an action in throat-clearing but states a real failure mode:

> In order to ensure correctness, it is important that the validator runs before the writer, because the writer assumes well-formed input and will otherwise produce corrupt output that is hard to debug.

> Run the validator before the writer: it assumes well-formed input and silently corrupts output otherwise.

"In order to … it is important that" → the action; the failure mode ("assumes well-formed input," "corrupts output") stays because it tells a future editor *why the order matters*. Only "hard to debug" — praise that guides nothing — is dropped.

A cut to reject. The shorter version reads fine but deletes the actual instruction:

> Search for an existing helper of the same shape before adding one.

> ~~Search for an existing helper before adding one.~~

"Of the same shape" is the rule, not filler — without it the reader searches by name and misses the match. No duplicate removed, no ambiguity fixed; the only win is fewer words. Leave it.

## Skill-Specific Rules

- Keep `SKILL.md` procedural and short. Move bulky examples or variant detail to directly linked reference files, read only when needed.
- Delete generated template text completely; do not add README, changelog, quick-reference, or process notes to a skill.

## Output

When reporting the edit, mention:

- what was shortened or reorganized;
- design intent or rationale preserved despite verbosity;
- rationale removed because it was duplicate or non-actionable;
- cuts reverted during self-review because they weakened clarity or design intent;
- any ambiguity that blocked a stronger cut.
