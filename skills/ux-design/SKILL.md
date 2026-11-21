---
name: ux-design
description: "Work out how someone should understand and perform an activity across interfaces, commands, workflows, terminology, examples, and explanations. Use for design or review when choices about steps, information priority, grouping, discovery, feedback, or learning remain unsettled. Covers removing user burdens and comparing concrete interaction models. Not for implementing a settled design, isolated styling or rendering fixes, prose polishing, backend architecture, or choosing overall work priority. A separate designer agent is not required."
---

# UX design

Design how someone accomplishes an activity and understands what happens.
Produce a concrete workflow, interaction, or explanation that its implementation and verification owners can use.
A direct task owner can use this method; assigning a designer is a separate choice about sustained responsibility.

## Establish the activity and scope

Read the original request, relevant corrections, explicit requirements, and available examples of the activity.
Establish whether the requested result is findings, alternatives, a worked example, or implementation.
A review authorizes findings, not repairs; a proposed design grants no additional effects.
Reuse settled decisions and ask only for missing context that could change the design.

Follow an actual operation from what someone starts with to the result they need.
Inspect available observations, conversations, support history, and current behavior before inventing an account of their needs.
Distinguish what people do, what they want to change, your interpretation, and your proposal.
Current practice neither requires preserving it nor overrides the requested outcome.
An imagined persona can suggest a question, not establish a user need.
When evidence is missing, state the assumptions that matter rather than claim user research or require a research project by default.

## Work out what the person must do and understand

Walk through the activity with the information available at each step:

- What must someone notice, choose, supply, or remember to proceed?
- What knowledge does the system assume without explaining it?
- How can they recognize what will happen, what did happen, and whether they got the intended result?
- Who else benefits, does work, or bears consequences when that could change the choice?

Use the answers to construct the interaction, not merely list usability concerns.
Decide which information belongs immediately in view, on request, or in reference material, according to what it enables the person to do.
Consider steps, grouping, names, defaults, examples, and feedback together where they affect the same activity.
Preserve required information and behavior without assuming the implementation's representation must determine their presentation.
Compare removing a burden with explaining how to manage it.
Preserve explicit requirements; distinguish them from agent-selected mechanisms and restrictions.

## Compare concrete alternatives

Sketch materially different ways to support the activity before developing one.
Show what someone knows, does, and can recognize in a worked example, including consequential differences between alternatives.
Use existing useful behavior and the requested outcome as the comparison, not just the nearest defect or a newly chosen specification.
Keep the comparison proportional to the unsettled choice; a local decision does not require a separate design document.

For example, a message transport may deliver a batch while someone reading updates needs to identify individual senders and bodies.
Compare showing the batch structure with showing individual messages and making correlation details available on expansion.
Use short, long, and multiple messages to see whether the grouping still serves that reading task.
Keep the complete information accessible; in a debugging view, identifying a specific message may make its ID important enough to show beside the body.

The same method applies without a visual interface.
For a recovery command, work through selecting a backup, understanding what it replaces, and recognizing the recovered result.
If someone cannot identify the right backup, compare improving the selection information with explaining the existing identifiers.
An accurate command reference can still leave that decision unresolved; a clearer selection step can remove the need to memorize identifiers.
Changes to operating behavior remain within the requested scope and its lifecycle owner's responsibility.

## Check the result and make it usable

Choose evidence for the claim and reuse the product's existing comparison or verification facilities.
A coherent proposal, agent agreement, or passing configuration check does not establish that people can use the result.
Keep observed outcomes, human choices, and unvalidated expectations distinct.
Use [human review packets](../human-review-packets/SKILL.md) for consequential choices needing substantial context, not routine preferences.

Use the applicable artifact procedure rather than create a second workflow:

- [UI design](../ui-design/SKILL.md) owns concrete rendered interfaces, controls, previews, and interaction verification.
- [Holistic writing](../holistic-writing/SKILL.md), or a dedicated writing skill, develops and reviews the explanation using the established facts and design choices.
- [Operational lifecycle](../operational-lifecycle/SKILL.md) owns unsettled installation, operation, update, recovery, and removal behavior.

Share the chosen workflow, usable examples, terminology, evidence, and unresolved assumptions with the people or agents implementing and checking it.
Revise affected choices when implementation or practice evidence contradicts their assumptions, and tell the affected consumers what changed.
Keep settled guidance with its canonical artifact; do not add a parallel specification or reporting step unless the task needs one.
Finish when the requested design result is usable by its consumers, or identify the specific dependency preventing that result.
