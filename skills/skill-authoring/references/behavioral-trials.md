# Behavioral trials

Read this reference before preparing paired behavioral or summarization trial inputs.
These protocols apply when conducting trials; skill edits and textual reviews do not require a trial by default.

Before an expensive full-history or whole-workflow replay, check whether an existing real handoff can test the changed behavior.
If so, run the receiver with that packet or artifact and the evidence it would actually have, rather than a researcher-written task.
Inspect the receiver's actual actions or outputs; investigate a failed check before expanding the replay.
A passing handoff check does not establish better parent decisions or downstream task outcomes.

Preserve normal coordinator tools and native completion delivery when assessing delegation, coordination, or latency.
Removing tools can force extra delegation; manual result bridging can introduce pauses absent from the real workflow.
If isolation changes either, record the differences and do not attribute the resulting delegation or waiting to the guidance under test.

For paired behavioral trials, fix the comparison question, outcome criteria, historical cut, model, and task inputs before generation;
vary only the skill under test.
Inspect the exact worker inputs and keep reference outputs and later diagnoses out of them.
Judge actual decisions and actions afterward, not just formatting or workflow compliance.

For a failure-driven revision, reconstruct the inputs available at the recorded failure decision point.
Include a nearby control that should retain its existing path.
For example, pair a decision about replacing custom profiling instrumentation with an obvious mechanical repair that needs no redesign.
Test whether the new guidance changes the failure decision without adding unnecessary steps to the control.

For each variant, report task outcomes alongside token use and elapsed time where available.
Include tool and review overhead when they are part of the compared workflow; separate shared experiment setup from execution cost.
Assess the added skill against the existing workflow.
If costs are unmeasured, report quality observations without claiming efficiency or net benefit;
one task does not establish general reliability.

For summarization trials, distinguish incremental replay (previous checkpoint plus subsequent history)
from blind reconstruction (preceding raw history without reference summaries or later critique).
Blind reconstruction must restore the underlying raw history, not merely delete the previous checkpoint.
These are different tasks; do not treat their outputs as a same-input comparison.
