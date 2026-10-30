---
name: issue-reporting
description: Draft or revise upstream bug reports, support questions, and design discussions for maintainers. Use when asked to write an upstream issue or discussion, fill an issue template, or prepare a maintainer follow-up about a concrete workflow, limitation, or workaround. Not for internal design documents or implementing fixes. Does not authorize submission or software upgrades.
---

# Issue reporting

Write for a maintainer who does not know the conversation or investigation.
Use the project and problem already established; ask which repository only when it cannot be identified.
Choose the right channel—bug report, support question, feature request, or design discussion—and describe the workflow, limitation, and workaround rather than forcing every request into a bug report.
Assume jyn is writing to another maintainer.

## 1. Decide whether to report

Check the target project's current contribution instructions and linked policies for AI, LLM, or agent rules.
Determine which rules apply to drafting, issue bodies, comments, disclosure, and agent submission.
Permission to generate code does not imply permission to write posts.
If the project prohibits AI-written reports or comments, do not draft, rewrite, or provide copy-ready text—even with disclosure or human submission.
Explain the restriction and cite the policy; continue only with permitted work, such as investigation and raw evidence collection.
Resolve unclear policy applicability before drafting.
If no policy is found, state where you checked outside the report; do not claim the project permits AI-written reports.
Follow project-specific disclosure rules when they differ from this skill's default.

Search open and closed issues and pull requests for the visible failure, relevant component, and distinctive errors or function names.
Read plausible matches and relevant comments; compare their reproduction and affected versions with the current evidence.
For a match, read its resolution and maintainer comments before proposing follow-up.
Recommend a follow-up only when new evidence could change the diagnosis, resolution, or requested action.
Reproducing a known unsupported configuration on newer versions does not by itself justify another comment.
Link related reports for different failures and explain the connection.
If search is unavailable or finds no match, state that limit outside the report; do not claim the bug has never been reported.

Before attributing the problem upstream, separate the observed problem and required behavior from the preferred mechanism.
Distinguish governing requirements from constraints introduced by a downstream design choice, and identify who chose it.
A draft's directory layout is not automatically an upstream requirement; do not add a disclaimer when the context already makes the choice clear.
Check plausible solutions in the supported configuration and public APIs.
State what each workaround solves, and distinguish unchanged-tool capabilities from approaches requiring consumer patches, downstream forks, or upstream adoption.
A library API does not establish that an unmodified CLI exposes the same capability.
Tie any remaining insufficiency to a concrete requirement and evidence, not an assumed side effect.
If it follows from a revisable downstream choice, reconsider that choice instead of treating it as an upstream constraint.
If evidence is missing, make a small authorized check or ask a bounded question.

Stop without drafting when existing guidance resolves the problem.
If an explicitly unsupported configuration causes the issue, identify who selects it and recommend correcting it at its owner; do not report the known incompatibility again or implement the correction.
Do not require a fix proposal for an unresolved failure; preserve uncertainty about its cause.
If an upstream change is still needed, identify the minimum change for the remaining problem.
A working but costly workaround supports a simplification request, not a claim that upstream changes are required for correctness.
Compare the downstream cost with the proposed upstream work and maintenance.

## 2. Gather the evidence

Read the target project's `CONTRIBUTING.md` and current issue template before drafting, plus any linked instructions that apply.
If `CONTRIBUTING.md` is absent, check the project's documented contribution instructions.
Follow issue-reporting requirements, not unrelated PR-only requirements; drafting does not authorize fixes or PR checks.
Use the applicable issue or discussion template, retaining its headings, order, and required fields; omit template comments and metadata.
If no template is available, tell jyn.
For remote source, shallow-clone the repository into a temporary directory.

Incorporate jyn's latest corrections and experiments.
Track whether each result came from jyn, an agent-run check, or source inspection.
Distinguish goals and reported experience from verification.
Describe agent-run checks with their commands, reproducers, and captured results; never say jyn ran them.
Do not present proposed steps as completed checks or invent commands, logs, environment details, or successful tests.
A source defect does not prove a runtime reproduction.
Include relevant local patches, forks, nonstandard configuration, and prior attempts with their results.
Include a working control when it narrows the failure, such as one picker order failing while the reverse order works.
In the report, include facts that help the maintainer reproduce, diagnose, or fix the failure; omit investigation narration and redundant checks when a working control already establishes the relevant difference.

Record the installed version, installation source, and relevant runtime dependencies.
Name the source precisely (for example, a GitHub release asset, distribution package, or local source build); say when it is unknown rather than using “official.”
If the project requests a development-version test, check that requirement and report whether it was met.
If that test needs another build, prefer an isolated standalone directory to replacing the installed program.
Follow `dependency-review` for a requested build or update; do not silently expand drafting into installation.

Inspect source when making a source-based claim.
For GitHub, resolve the full commit hash and use a permalink with precise line anchors—never a branch name or abbreviated hash.
For other hosts, use an equivalent stable, revision-specific link when available.
Omit source links when the report makes no source-based claim.

## 3. Write for the maintainer's decision

Organize the report around the maintainer's decision, not the investigation's chronology.
Read the title and body together; keep the specific request rather than broadening it.
For a change proposal, name the change before the workaround unless the template requires another order.
Before opening collapsed details, the maintainer should understand the failure, why it matters, the requested outcome, and why obvious workarounds fall short.
When an existing supported approach might meet the need, ask about it without replacing a specific proposal with general advice-seeking.
Do not imply an approach exists or ask the maintainer to design one unless that is the request.
A maintainer can recommend keeping a solution downstream without supplying an alternative.
Do not duplicate requests already covered by template fields.
See the [discussion contrast](../holistic-writing/references/reading-examples.md#state-the-request-before-the-workaround) for examples.

### Explain the workflow and limitation

Use complete sentences and ordinary issue prose, even if the conversation uses IRC style.
State jyn's goals and experience accurately; do not invent familiarity, use, or personal verification.
If jyn supplies first-person experience, preserve wording such as “In my case.”
“I want to use ...” does not establish “I use ...”.

For a bug report, name the general failure in the title, not just the tool that exposes it; for example, title a failure “user-local Python” and name mise in the body.
Treat exact UI labels and [improper nouns](https://siderea.dreamwidth.org/1773806.html) as terms of art: quote them in titles when Markdown is unavailable, format them distinctly in the body, and define unfamiliar terms on first use.
Use familiar words and active voice with concrete subjects.
For example: “The command returned ...” rather than “The execution yielded ...”; “the launcher calls Python” rather than “Python is called.”
For GitHub issues and pull requests in the target repository, use `#123` without repeating the full URL.

Explain the practical need through a concrete workflow, not just a desired mechanism.
When motivation or upstream responsibility is not obvious, add a motivation section or use the template field.
Introduce downstream tools before relying on them for context, and explain why a technical term matters.
Connect what the user wants to do, what the failure prevents, and what a fix must preserve.
Explain where the limitation arises and why workarounds fall short, distinguishing what each one solves.
When execution boundaries matter, say where processes and data live; “guest” alone does not distinguish a VM from a container.
Use examples to explain the workflow, not as detached facts followed by API details.
Separate evidence implicating the target project from assumptions that it must change.
Do not claim downstream fixes are impossible when they are merely awkward or incomplete.

State the visible failure and practical consequence, then explain the cause if established.
Label hypotheses and keep the observed behavior useful even if the diagnosis is wrong.
Describe expected behavior separately.
For a bug report without a template-prescribed order, use **Expected behavior**, **Actual behavior**, then **Reproduction**.
Add a small fix suggestion only when evidence supports it; do not turn the report into an implementation plan.

### Present reproduction and technical details

Keep required template headings and fields visible.
Put the installation or invocation in the reproduction.
Give a concrete command and the point where failure appears; use numbered steps when several actions or the template requires them.
Include relevant inputs, configuration, cursor position, or keystrokes.
Mark proposed steps unverified when needed, and distinguish runnable reproducers from illustrative code with omitted setup or placeholders.
If inaccessible infrastructure prevents reproduction, state that limit and provide available evidence.
Include a failing input or artifact when useful, even if not minimized; state any minimization limit.
Use screenshots for visual failures.

Keep decisive evidence visible, and put most reproduction setup, source, and supporting output inside `<details>` unless needed to understand the failure.
Collapse supporting output unless it explains the visible failure.
Do not repeat the visible excerpt inside collapsed output.
Preserve observed output verbatim in a fenced block; say if it is an excerpt or from an older version, and never present old output as a new test.
Put each bare GitHub permalink on its own line immediately after the claim it supports.

Unless the template requires otherwise, put exact versions, installation provenance, runtime dependencies, and source analysis in a `<details>` block at the end.
Repeat a version elsewhere only to distinguish results across versions.
Include full development commit hashes and the tested invocation; do not repeat hashes in prose when source permalinks identify them.
Say “using commit ...” rather than narrating source comparisons.
For standalone builds, include build and resource paths and any environment variables needed to load them, so the reproduction does not silently use installed catalogs.

Follow the project's disclosure placement.
Otherwise, put this disclosure before the template's first heading:

`🤖 this issue description was generated by an LLM 🤖`

Keep the template headings, order, and required fields after the disclosure.
Preserve required template text, the disclosure, and quoted output verbatim.
Leave disclosure of later human edits to jyn.

## 4. Validate and deliver

Check the final body against the template, contribution requirements, and jyn's latest evidence.
Verify code links identify the inspected revision and lines, reproduction commands match the reported test, and required fields are filled or explicitly unknown.
Check template attestations individually; do not mark research, clean-environment, or latest-version checks complete without evidence.

If the report has attachments, inspect the actual files and archive members.
Compare paths, hostnames, environment values, and private content with the report's privacy choices and redactions.
A redacted body does not sanitize attachments.
Preserve raw evidence; use labeled copies for redacted attachments and inspect the final archive again.
State remaining identifying metadata or body/attachment mismatches outside the report, even when no credentials appear.

Review each authored sentence for passive voice and hidden actors.
Use the known actor or state the behavior directly; do not invent an actor to satisfy this check.

Save the issue body as Markdown at jyn's requested path, or use a descriptive filename in the working directory.
Keep it current when revising.
Return a copy-ready title and a link to the file.
Keep process commentary, remaining checks, and the issue-creation URL outside the report body.
For each material check that remains, give the exact check to run and say which sentence or field to replace for each possible result.
Keep unverified claims out of the report; do not turn agent limitations into first-person claims or claim checks neither jyn nor an agent performed.
Incorporate jyn's results when supplied.
If no material checks remain, say so briefly.
After the first draft, provide the upstream issue-creation URL outside the report body.
Drafting does not authorize submission; submit only when explicitly requested and the project's policy permits agent submission.

After writing or revising a report, use `holistic-writing` for a whole-artifact editorial review.
Make clear which response from the maintainer would help, and distinguish existing capabilities from proposed changes.
