# CUE contracts for skills and policies

Use this library to check a proposed assignment, plan or report against named constraints.
For example, a plan can require independent verification without imposing one worker per role:

```cue
package myplan

import policy "dotfiles.example/skillrules@v0"

review: policy.#IndependentVerification & {
    constructors: ["builder-a", "builder-b"]
    verifiers: ["qa-a", "qa-b"]
}
```

The definition requires at least one verifier and forbids any verifier from sharing a declared constructor's identity.
It permits multiple builders, multiple verifiers and verification without new construction.
Apply it only when independence is required; ordinary consumer checks do not acquire that requirement merely by using this library.

These are opt-in building blocks, not replacements for the existing prose or new mandatory workflow steps.
The library checks supplied declarations, not whether an agent tells the truth or performs its recorded plan.
A valid record means it satisfies the selected constraints, not that every governing instruction has been modeled.

## Check records and compose schemas

This directory is a local CUE module, with package name `skillrules` and import path `dotfiles.example/skillrules@v0`.
The name is a local namespace, not a published registry dependency.
There are no external module dependencies.
The module declares CUE language v0.17.0 and is tested with CUE v0.17.1.

JSON records can live outside the module.
From the dotfiles root, with CUE on PATH, validate a record against one exported definition:

```sh
dev/test-environment cue -C skills/references/cue vet -c -d '#IndependentVerification' . /absolute/path/to/packet.json
```

Here `packet.json` contains `constructors` and `verifiers`, as in the example above.
`-c` requires concrete values; omitting a required value does not turn it into false or silently select a default.
A missing value and a contradictory value both fail this CLI check, so inspect the diagnostic before revising the record.

For a CUE schema that composes several definitions, use a subpackage inside this module.
The [working example](examples/review.cue) connects a task's grants, a worker's proposed effects and conditional independence checks.
It also records partial coverage, an unresolved judgment and a deferred dependent action.
Run its native import and validation path with:

```sh
dev/test-environment cue -C skills/references/cue vet -c ./examples
```

Importing this module from a separate CUE module would require dependency/distribution configuration; this change does not publish it or migrate existing skills.

## Choose a constraint

### Membership and separation

[`#Subset` and `#Disjoint`](relations.cue) work on lists of concrete CUE values.
Supply `superset` and `subset` for membership, or `left` and `right` for separation.
Comparison uses the CUE standard library's `list.Contains`, not string prefixes or schema subsumption.
Order and duplicate entries do not affect membership; these definitions do not enforce uniqueness or count independent occurrences.
An empty list is a subset of any list, and is disjoint from every list.

Callers supply the relevant identity keys.
Different display labels do not establish different people, resources or evidence producers, and aliases need resolution before checking identities.

### Authority and independent work

[`#AuthorizedEffects`](authority.cue) takes `grants` and `proposed` effects.
Each grant contains an `effect` and a `source`; each effect contains `actor`, `action` and `target` identity keys.
Every proposed effect must match one currently applicable grant exactly.

This deliberately does not infer permission from tools, roles, readiness, wildcard targets, path ancestry, a parent's grant or an assumed relationship between read and write.
Resolve those policy-specific meanings before supplying grants.
An authorized caller can supply a revised grant set after a governing decision changes; the library does not interpret instruction precedence, revocation or natural-language scope.
A source reference is not an authenticated grant.

[`#IndependentVerification`](authority.cue) combines nonempty verifier staffing with `#Disjoint`.
It validates declared identity separation, not intellectual independence or whether a separate verifier is necessary.
Repeated verifier IDs remain allowed because this contract does not claim a number of distinct verifiers.

### Judgments and sources

[`#Judgment`](references.cue) requires a `question` and `sources`, plus one of:

- `status: "resolved"`, a concrete `value` and a `rationale`;
- `status: "unresolved"` and a description of what is `missing`.

An unresolved judgment cannot carry a fabricated resolved value.
A resolved value can itself be false, structured data or another concrete value; consumers can refine its type.
An empty source list is allowed, so representing a judgment does not demand a fresh investigation or an external citation.
The rationale's quality and the evidence's adequacy remain judgments.

`#SourceRef` distinguishes file, message, ticket, URL and inline material.
File references can include a revision and selector.
Paths and URLs are only nonempty strings: the library does not parse their syntax, resolve them, check existence, fetch content or establish authority.
Inline material permits honest recording when no stable source identifier is available.
`#Text`, the shared string constraint, rejects an empty string but does not reject whitespace-only text.

### Coverage without an invented success claim

[`#Coverage`](coverage.cue) takes an independently supplied `inventory` of identity keys and a `dispositions` map.
Every inventory key must have a concrete row, and rows outside the inventory are rejected.
Each row has a status, reason and evidence list.

The statuses are `covered`, `excluded`, `unresolved` and `unexamined`.
A covered row requires at least one source reference; other rows may have an empty evidence list.
An inventory key has one row, rather than potentially conflicting membership in several status lists.
Inventory order and repeated keys have set membership semantics, not occurrence-count semantics.

A complete accounting can still contain unresolved or unexamined work.
This contract does not certify completion, authorize exclusions, prove that the inventory is complete or establish that evidence reaches the claimed boundary.
A caller claiming a stronger result must add that result's requirements.

### Prerequisites without stopping independent work

[`#Prerequisite`](authority.cue) takes `required`, a `state`, and the proposed `dependentAction`.
If required, an unsatisfied or unresolved prerequisite permits only `dependentAction: "defer"`.
A satisfied or unnecessary prerequisite permits either `proceed` or `defer`; it does not compel action or establish authorization.

The state remains explicit, so unresolved does not become failed.
Only the named dependent action is constrained; this is not a whole-goal blocked state or a rule to stop unrelated work.

## Where the patterns come from

The survey sampled skills, shared instructions, role procedures and selected executable policy declarations.
It is not a claim that every repository policy was translated.
The sources motivate the relations; the CUE files do not replace their scope, exceptions or judgment criteria.

| Pattern | Source contexts |
| --- | --- |
| Effects stay within explicit authority | [Shared objectives and scope](../../../config/agents/shared-agents.md#objectives-and-scope); [builder responsibility](../../../config/pi-agent/pi-codex-subagents/agents/builder.md); [sandbox permissions](../../../config/agents/sandbox-AGENTS.md#permissions) |
| Separation without a fixed team | [Executive assignments](../../delegation/references/executive.md#assign-bounded-outcomes); [declared identity and cardinality](../testing.md#validate-consumer-behavior-and-resource-selection) |
| Explicit unresolved judgments and provenance | [Non-narrowing review](../../spec-review/references/non-narrowing.md); [requirement decisions](../../requirements-definition/SKILL.md); [records and provenance](../../../config/agents/shared-agents.md#records-and-provenance) |
| Coverage against a declared inventory | [Completion audit](../../completion-audit/SKILL.md); [population accounting](../testing-examples.md#coverage-and-required-populations); [review evidence](../review-evidence.md#scope-and-findings) |
| Prerequisites affect only dependent work | [Generation before consumption](../../../AGENTS.md); [retained assignment boundaries](../../delegation/references/executive.md#assign-bounded-outcomes); [producer/consumer contracts](../../delegation/references/shared-contracts.md) |

## Test and extend

With CUE installed, run the native-validator tests through the repository runner:

```sh
dev/pytest -q tests/skills-cue/cue_library_test.py
```

If the executable is not on PATH, select it explicitly:

```sh
env DOTFILES_TEST_CUE_REAL=/absolute/path/to/cue dev/pytest -q tests/skills-cue/cue_library_test.py
```

The suite is included in normal pytest discovery.
Without CUE it reports a skip; an explicitly configured but unusable executable is an error.
Tests use disposable copies, exercise real module imports and JSON validation, compare membership relations against bounded set oracles, and check valid counterexamples to stronger rules.
They do not run agent trials or establish that agents obey this library.

When adding a definition, identify its source contexts, accepted counterexamples and intentionally unverified judgments.
Retain both allowed and rejected examples: a stronger but unjustified constraint can be valid CUE while incorrectly rejecting a legitimate case.
