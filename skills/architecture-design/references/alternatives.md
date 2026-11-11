# Map design alternatives

Use when tracing leaves a genuine architectural choice and supplied candidates do not cover it.
Choose the few decisions that define the space, such as ownership, persistence, synchronization, representation, or compatibility.
Produce up to three viable briefs with materially different decisions, not stylistic variants or complete implementation plans.

Use the task, explicit constraints, repository context, and relevant historical evidence to judge viability.
Reject a fork when it violates a requirement, contradicts itself, adds no distinct option, or is strictly dominated on the stated criteria.
Name the requirement or evidence; missing evidence is not demonstrated failure.
Compare candidates on equal terms: one proposal's optional guarantee cannot disqualify another, and a repaired candidate cannot fairly beat an unrepaired competitor.

Each brief contains:

- `id`: A, B, or C.
- `key_decisions` and `rationale`: what it chooses and why that arrangement is viable.
- `assumptions` and `invalid_if`: what it relies on and what evidence would rule it out.
- `why_distinct`: the concrete decisions separating it from the others.

Return rejected forks and reasons separately.
Keep unconventional viable options; leave slots empty rather than inventing weak alternatives.
