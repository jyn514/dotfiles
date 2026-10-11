# Behavioral trials

Read this reference before preparing paired behavioral or summarization trial inputs.
These protocols apply when conducting trials; skill edits and textual reviews do not require a trial by default.

For paired behavioral trials, fix the comparison question, outcome criteria, historical cut, model, and task inputs before generation;
vary only the skill under test.
Inspect the exact worker inputs and keep reference outputs and later diagnoses out of them.
Judge actual decisions and actions afterward, not just formatting or workflow compliance.

For each variant, report task outcomes alongside token use and elapsed time where available.
Include tool and review overhead when they are part of the compared workflow; separate shared experiment setup from execution cost.
Assess the added skill against the existing workflow.
If costs are unmeasured, report quality observations without claiming efficiency or net benefit;
one task does not establish general reliability.

For summarization trials, distinguish incremental replay (previous checkpoint plus subsequent history)
from blind reconstruction (preceding raw history without reference summaries or later critique).
Blind reconstruction must restore the underlying raw history, not merely delete the previous checkpoint.
These are different tasks; do not treat their outputs as a same-input comparison.
