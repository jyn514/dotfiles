# Evidence standards

Use these standards when supporting specification-review findings, conformance findings, or completion claims, and when interpreting checks during implementation.
Consulting them does not start an audit.

## Scope and findings

Establish the artifact, governing requirements, and inspected scope before assessing it.
Separate observed defects, assumptions, unresolved questions, and optional improvements.
For each finding, identify its location, evidence, consequence, and smallest useful correction.
Report exclusions, deferrals, and unavailable validation; silence does not establish completeness.
Loading this reference grants no permission to repair artifacts or write issues.
Apply task-specific permissions and stopping conditions from the applicable skill.

## What checks establish

[Testing](testing.md) owns test construction.
[Autonomous-work](../autonomous-work/SKILL.md) applies these standards to implementation milestone readiness during explicitly authorized autonomous work.

A worker report, aggregate test count, correct helper, or atomic commit is not evidence that the assembled path works. Distinguish:

- **Component-tested / local-only:** checks pass only for an isolated component or mocked path.
- **Integrated:** the required consumer-path check passes through intended interfaces for the declared scope.
- **Verified with required real inputs:** checks also pass with the credentials, data, or environment explicitly required by the governing acceptance condition.

Fixture inputs through intended interfaces can establish integration, but cannot satisfy a condition requiring real inputs. A feasibility or component milestone can complete at its declared scope without completing downstream integration. Record a failed check or unresolved contract that prevents integration as **blocked**; do not certify blocked outputs or claim broader completion.

Label each check by the process or boundary it reaches.
A unit/helper or mocked-launcher test does not prove that the receiver loaded an extension, ran a hook, or received a transformed payload.
For receiver-visible claims, trace the production path from entrypoint through configuration, launch, handler order, and receiver, then use an integration test that reaches the receiver or direct runtime observation.
If unavailable, mark that behavior unverified; component results support but do not substitute.

## Reuse evidence without duplicating verification

Independent verification requires inspecting underlying evidence, not automatically repeating its production.
Check the actual diff and relevant results against the governing requirement, tested artifacts, scope, inputs and intended consumer interfaces.
Retain the tested identities and establish whether intervening changes invalidate the result; rerun missing or invalidated checks.
A worker summary or aggregate count is not enough, but independence does not require reconstructing every count, join or receipt in a second verification system.
Use raw traces where they resolve a correctness question, not as a mandatory duplicate reconstruction of every passing check.
When repeated mechanical checks are necessary, extend existing maintained tests or validation rather than adding successive coordinator scripts.
Keep one authoritative result and reference its evidence and demonstrated limits from acceptance and recovery records.

Keep historical evidence bound to the artifact and property actually checked.
A reference-only rewrite can preserve execution behavior while invalidating an attestation to the exact body.
Changing identifiers or recomputing hashes does not establish that the transformed artifact passed the original check.
Establish which checked properties survive an authorized transformation before reusing the evidence; verify only claims whose evidence is missing or invalidated.
Do not present preserved historical evidence as a newly executed check.
