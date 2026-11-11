# council-review

Judge a fixed candidate set against the original task, constraints, `cross-critic` report, and available factual evidence in fresh contexts.
Assess every candidate against the same criteria; count unsupported assumptions as liabilities, not verbosity, familiarity, confidence, or inclusion of more ideas as merits.
Ignore ordering and provider identity.

Return exactly one:

- `SELECT`: supplied candidate ID, decisive reasons, important rejected alternatives, and remaining uncertainty.
- `EQUIVALENT`: materially indistinguishable candidates, reasons, and an optional deterministic tiebreak criterion.
- `ABSTAIN`: decision-changing missing evidence and the cheapest useful inquiry.

Judge only the supplied candidates; neither rewrite them nor invent another.
A fusion candidate has no special status: choosing D is ordinary `SELECT D`.
