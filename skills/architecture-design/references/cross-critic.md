# cross-critic

Compare fixed, independently generated plans against the original task, constraints, and repository evidence before choosing or combining them.
Ignore ordering and verbosity.

First compare without scout rejections:

- Each candidate's unique strengths, unsupported assumptions, hidden costs, missing requirements, and likely failures.
- Decisive architectural differences rather than cosmetic ones.
- Missing design regions and components that could compose cleanly.
- Missing evidence that could change the ranking.

Then read scout rejections skeptically and name premature rejections or regions worth reopening.
Return those comparisons and per-candidate findings.
Leave selection to `council-review` and synthesis to `fusion-candidate`; do not choose, rewrite, or combine candidates here.
