---
name: ui-design
description: "Design or review frontend screens, interactions, mockups, and cross-screen consistency. Ground changes in the existing product, compare real components with matched fixtures, and verify behavior, accessibility, themes, and viewports. Use for UI/UX design, redesigns, mockups, and usability reviews. Not for backend architecture, prose-only editing, or a trivial styling correction with settled behavior. A review or mockup request does not authorize production changes."
license: MIT
---

# UI design

Start with the task someone needs to complete, then inspect the interface they actually use.
A convincing mockup must show the proposed behavior without quietly changing the surrounding product.

## Establish the task and permitted changes

Identify the audience, user task, surface, relevant states, and requested result: findings, alternatives, a mockup, or implementation.
Reuse the brief and settled decisions; ask only about unresolved choices that could materially change the design.
A review authorizes findings, not repairs; a mockup does not authorize shipping it.

For an existing surface, open the running UI when available and read its authoritative components and styles.
Inspect the existing design system, tokens, interaction patterns, and applicable accessibility requirements.
Distinguish a visual refresh from changes to navigation, terminology, information structure, or workflow.
Do not treat “make it modern” as permission to discard existing behavior or migrate the stack.
For a new surface, inspect adjacent screens or the selected design system before inventing another visual language.

Identify what the task must preserve: routes, shortcuts, fields, legal text, analytics semantics, accessibility, and other external contracts.
Check test selectors and callers when component structure changes; preserve behavior rather than freezing incidental markup.
Apply the [shared change guidelines](../references/change-with-evidence.md) to implementation and dependency choices.

## State the basis for material choices

Explain the concrete problem, the proposed change, and why it should help this task.
Distinguish the basis:

- **Public guidance:** cite the applicable design-system or accessibility rule and explain why it applies here.
- **Human decision:** name the explicit choice and preserve its scope; approval of one example is not approval of every related change.
- **Observed behavior:** identify what people actually did, with the context and limits of the observation.
- **Product convention:** point to the existing pattern and explain whether consistency serves this task.
- **Unvalidated proposal:** state the rationale and what review or observation could support or reject it.

A proposal is a candidate, not evidence of improved usability or permission to expand scope.
Do not invent a public rule, treat a taste preference as an accessibility requirement, or use a heuristic to override a governing requirement.
Resolve factual questions from available sources before asking for human judgment.
Use [human review packets](../human-review-packets/SKILL.md) when a consequential choice needs substantial context, not for every spacing decision.

For example, a reviewer sees a toolbar action but cannot tell which selected row it affects.
Moving the action beside the row is a proposal grounded in a specific ambiguity; it is not yet a demonstrated improvement.
Compare it with retaining the toolbar and naming the target, then show selection changes and the narrow-screen state.
If existing user observations already establish the failure, retain that evidence instead of presenting the diagnosis as a guess.

## Build the smallest faithful comparison

Use the project's existing preview, story, test harness, or development setup before adding infrastructure.
For an existing component-based UI, render the real components rather than copying their markup into a parallel mock.
A static sketch can answer a geometry question or explore a surface with no buildable components; label its fidelity and do not claim it verifies interactions.
Do not add a mock-site framework, design-contract file, scoring service, or dependency unless the task actually needs it.

When showing alternatives:

- Render Current from the actual baseline components and props, not a redraw.
- Give Current and Proposed the same surroundings, viewport, state, and fixture data except where the proposal intentionally differs.
- Identify each intended difference so accidental changes do not look like approved design.
- Use fixtures with realistic record shapes, lengths, and state combinations; keep secrets and private records out of review artifacts.
- Give each variant a stable label or reference so the human can identify what she accepts or rejects.

Use owned disposable state and separate outputs from anything a live application serves.
Verify which checkout and resources the preview actually loads.
A worktree or private HOME alone does not establish isolation; follow the [shared testing guidance](../references/testing.md#isolate-and-register-tests).

For a destructive action, a static side-by-side image cannot establish the confirmation or cancellation behavior.
Exercise those transitions through the real component with a disposable fixture.
For a typography-only change, a matched rendered comparison may suffice without a new interaction harness.

## Verify the rendered result

Choose cases from the task and affected contracts, not an arbitrary number of screenshots or a universal score.
Inspect the result in a real browser when making claims about rendering or interaction.
If that check is unavailable, identify what remains unverified rather than treating a source inspection as a rendered pass.

Check the affected user path, including relevant loading, empty, error, success, and cancellation states.
Exercise clicks, typing, focus changes, and keyboard controls when those interactions matter.
Check responsive behavior at the widths the product supports, including where the proposed layout changes or overflows.
Verify each affected shipped theme or mode; use existing tokens rather than hardcoded replacements.

Evaluate applicable accessibility requirements: semantics, accessible names, reading and focus order, visible focus, keyboard access, contrast, zoom, and reduced motion.
Use the project's automated checks where available, then inspect what they do not establish through manual checks or appropriate assistive technology.
Do not claim full accessibility from screenshots or an automated scanner alone.

Classify findings by concrete user impact and governing requirements.
Keep taste suggestions distinct from defects; a model's visual score is not an acceptance condition.
Fix the highest-impact in-scope issue first when repairs are authorized, then recheck the affected path and protected behavior.
Stop when the requested outcome and required checks are met, not when every imaginable preference has been satisfied.

## Present and preserve the result

Show a runnable preview when the human needs to judge interaction and one is available; use images for visual comparison when sufficient.
Name each alternative, its important trade-off, the basis for the recommendation, and checks or decisions still missing.
Record human decisions against the exact alternative reviewed before implementing dependent changes.
Do not interpret silence or your own review as human acceptance.

For substantial UI copy or explanatory prose, use [holistic writing](../holistic-writing/SKILL.md); preserve established product terminology.
For authored design explanations, use its [editorial pass](../holistic-writing/references/editorial-pass.md).
Keep reusable product decisions in their existing canonical owner rather than creating a second design system or a session recap.

Adapted from BlackBeltTechnology/pi-agent-dashboard's `frontend-mockup-loop` skill in `packages/mockup-loop/.pi/skills/`.
The adaptation keeps real-component comparisons and rendered verification without requiring the upstream tools or every-decision citation policy.
See [LICENSE](LICENSE).
