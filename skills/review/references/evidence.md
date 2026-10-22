# Evidence standards

These standards define what checks prove during implementation and at completion; consulting them early does not start the full audit.
[Testing](../../references/testing.md) owns test construction.
[Autonomous-work](../../autonomous-work/SKILL.md) applies these standards to implementation milestone readiness during explicitly authorized autonomous work.

A worker report, aggregate test count, correct helper, or atomic commit is not evidence that the assembled path works. Distinguish:

- **Component-tested / local-only:** checks pass only for an isolated component or mocked path.
- **Integrated:** the required consumer-path check passes through intended interfaces for the declared scope.
- **Verified with required real inputs:** checks also pass with the credentials, data, or environment explicitly required by the governing acceptance condition.

Fixture inputs through intended interfaces can establish integration, but cannot satisfy a condition requiring real inputs. A feasibility or component milestone can complete at its declared scope without completing downstream integration. Record a failed check or unresolved contract that prevents integration as **blocked**; do not certify blocked outputs or claim broader completion.

Label each check by the process or boundary it reaches. A unit/helper or mocked-launcher test does not prove that the receiver loaded an extension, ran a hook, or received a transformed payload. For receiver-visible claims, trace the production path from entrypoint through configuration, launch, handler order, and receiver, then use an integration test that reaches the receiver or direct runtime observation. If unavailable, mark that behavior unverified; component results support but do not substitute.
