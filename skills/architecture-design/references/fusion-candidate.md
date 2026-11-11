# fusion-candidate

Use the fixed candidates, `cross-critic` findings, and original task and constraints to decide whether identified components compose cleanly.
Return `NO_FUSION` with a reason when they remain tightly coupled.
Otherwise construct at most one candidate D containing:

- `sources`: which components come from each candidate.
- `rejected`: conflicting components dropped or superseded.
- `plan` and `composition_argument`: how the parts work together without contradictory assumptions.
- `assumptions` and `new_risks`, including unverified premises of the composition argument.

Explain the composition rather than claiming to “combine the best parts.”
Add no unrelated novel architecture; D is an ordinary candidate, not a preferred answer.
