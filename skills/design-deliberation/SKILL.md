---
name: design-deliberation
description: Orchestrate the smallest useful workflow for uncertain software-design decisions using independent alternatives, repository evidence, critique, optional fusion, and fixed-set review. Use for genuine design forks, legacy architectural pain, or implementation tasks requiring explicit design selection.
---

# design-deliberation

Coordinate the design skills for uncertain software decisions. Select the smallest workflow that resolves the decision, preserve candidate independence, and stop before implementation unless requested. Delegate procedures to their owning skills or linked phase references; this skill owns routing and orchestration.

## Inputs

- The design question or implementation task
- User constraints and non-goals
- Repository context, history, and existing candidate designs when available

## Select a workflow

- **Broad project-improvement goal:** Start with `opportunity-scan`; select an area before investigating its history or design. After selection, use `pain-axis` if history could test recurring pain, then scout only if a genuine design fork remains. Recent activity is not evidence of importance by itself.
- **Small or mostly-local change:** Use `boundary-declaration`; add `second-user` for a proposed abstraction and `ratchet` when an established invariant can be checked mechanically. Do not create multiple plans without a genuine design fork.
- **Genuine design fork:** Use the sequence below. Add `pain-axis` first when repository history can provide useful evidence.
- **Legacy or failure-prone subsystem:** Start with `pain-axis` unless history is unavailable or irrelevant.
- **Long autonomous implementation:** After design selection, follow [After selection](#after-selection).

Do not ask `pain-axis` to select a project opportunity; it investigates a selected area. Do not use `council-review` instead of available mechanical checks.

## Orchestrate a genuine design fork

The planning, critique, fusion, and review procedures below are reference files,
not registered skills. Read each linked file only when entering its phase. For a
delegated phase, give the subagent the reference's full text or absolute path
resolved from this skill directory, plus that phase's inputs. Do not pass these
names as harness skills or preload unrelated phase references.

1. **Map options:** Ask `design-space-scout` for materially distinct viable briefs. Use fewer than three when fewer real options exist.
2. **Elaborate independently:** Assign one [independent-plan](references/independent-plan.md) per viable brief. Each sees the shared task, constraints, evidence, and only its own brief. Give candidates stable opaque IDs outside the plans. If fewer than two viable plans survive, stop and report why.
3. **Critique:** Ask [cross-critic](references/cross-critic.md) to compare the fixed plans without selecting or rewriting them. Give it rejected scout forks only after its initial comparison.
4. **Consider fusion:** Ask [fusion-candidate](references/fusion-candidate.md) only if the critique identifies components that may compose cleanly. No fusion is a normal result; any synthesis remains an ordinary candidate with stated provenance and risks.
5. **Review a fixed set:** Ask [council-review](references/council-review.md) to judge the candidates and critique. Do not add or rewrite candidates after review starts; hide candidate identity/provider where practical and do not treat ordering as meaningful. Accept `SELECT`, `EQUIVALENT`, or `ABSTAIN`; abstention means identify the missing evidence and cheapest useful inquiry.

Use each phase reference for its required inputs, constraints, and output; do not duplicate its procedure here.

## After selection

A selected plan is a design hypothesis, not verification. Before implementation, use `boundary-declaration`; during implementation, use `second-user` for new reusable abstractions and `ratchet` for mechanically checkable invariants or failures. Prefer tests, type checks, static analysis, benchmarks, and repository evidence over additional model votes.

If the user already supplied serious candidates, skip `design-space-scout` unless a material region is missing. Elaborate them independently when needed, then begin critique. If the user supplied one design for evaluation, do not manufacture alternatives unless a genuine unresolved fork remains.

## Cost and stopping

Use at most three initial plans, run independent planners in parallel when practical, and construct at most one fusion candidate. Do not add revision rounds by default, recursively debate, or force agreement after `EQUIVALENT` or `ABSTAIN`.

Add heavier workflow only after observing a concrete failure that it would prevent. For example, recurring scout omissions may justify an independent challenge; repeated abstention on obtainable evidence may justify an evidence-gathering step. Do not add speculative branches or persistent tracking machinery without such evidence.

## Output

Report the selected candidate, equivalent set, or abstention; the decisive reasons; important uncertainty; whether fusion was considered; and the next useful action. Keep intermediate transcripts out unless requested.
