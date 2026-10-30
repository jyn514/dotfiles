---
name: issue-reporting
description: Draft or revise upstream bug reports, support questions, and design discussions for maintainers. Use when asked to write an upstream issue or discussion, fill an issue template, or prepare a maintainer follow-up about a concrete workflow, limitation, or workaround. Not for internal design documents or implementing fixes. Does not authorize submission or software upgrades.
---

# Issue reporting

Draft only when a report or follow-up is warranted and the target project's AI policy permits it.
Use the project and problem from the conversation; ask for the target repository only when it cannot be identified.
Assume jyn is writing to another maintainer.
Transfer the evidence they need without relying on shared context.
Use the project's applicable channel and template for a bug report, support question, feature request, or design discussion.
Describe the user workflow, limitation, and existing workaround rather than forcing every request into a bug report.

## Gather the authoritative inputs

Before drafting any upstream text, check the target project's current contribution instructions and linked policies for AI, LLM, or agent rules.
Check which rules apply to issue bodies, comments, drafting, disclosure, and agent submission.
Permission to generate code does not imply permission to write posts.
If the project prohibits AI-written reports or comments, do not draft, rewrite, or provide copy-ready text for them, even with disclosure or human submission.
Explain the restriction and cite the policy; continue only permitted work, such as investigation and raw evidence collection for the user to write up.
If the policy's applicability is unclear, resolve it before drafting.
If no policy is found, state where you checked outside the report rather than claiming permission.
Apply project-specific disclosure requirements instead of this skill's default wording when they differ.

Before drafting, search the target project's open and closed issues and pull requests for existing reports or fixes.
Search by the visible failure, relevant component, and distinctive error messages or function names.
Read plausible matches, including relevant comments, and compare their reproductions and affected versions with the current evidence.
When a matching report exists, read its resolution and relevant maintainer comments before proposing further communication.
Recommend a follow-up there rather than a duplicate only when new evidence could change the diagnosis, resolution, or requested action.
Reproducing a known unsupported configuration on newer versions does not, by itself, justify another comment.
Link related reports and explain the connection when they describe a different failure.
If search is unavailable or finds no match, state that limit outside the report; do not claim the bug has never been reported.

Before attributing the problem upstream or proposing a change, trace the following chain:

1. State the observed problem and required behavior separately from any preferred mechanism.
   Identify which constraints are governing requirements and which follow from a downstream design choice, including who chose it.
   A directory layout chosen for a draft design is not an intrinsic upstream requirement.
   A heading or the surrounding explanation can establish whose choice it is; do not add a disclaimer when that is already clear.
2. Check plausible existing solutions in the supported configuration and public APIs, and state what each workaround actually solves.
   Distinguish unchanged-tool capabilities from approaches requiring consumer patches, downstream forks, or upstream adoption.
   An existing library API does not by itself establish that an unmodified CLI exposes the same capability.
   State those adoption and maintenance costs in the main explanation, not only in collapsed test details.
3. Tie any remaining insufficiency to a concrete requirement and evidence, not an assumed side effect.
   If it follows from a revisable downstream design choice, consider changing that choice rather than treating it as a constraint on upstream.
   If that evidence is missing, use a small authorized check or ask a bounded question; do not turn uncertainty into a defect claim.
4. If a change is still needed, identify the minimum upstream change that addresses the remaining problem, not the original problem already solved.
   A working but costly workaround supports a simplification request, not a claim that upstream changes are required for correctness.
   Compare its downstream cost with the proposed upstream work and maintenance.

Do not require a fix proposal to report an unresolved failure; preserve uncertainty about its cause.

If the reproduction depends on an explicitly unsupported configuration, identify who selects that configuration.
Recommend correcting it at its owner rather than reporting the known incompatibility again.
This does not authorize implementing the correction.

If existing guidance resolves the problem, explain the applicable resolution and stop.
Do not draft a report or comment merely to satisfy this skill.
The writing, tightening, and delivery requirements apply only when a report or follow-up is warranted.

1. Read the target project's `CONTRIBUTING.md` and current issue template before
   drafting. Follow its issue-reporting requirements, including instructions it
   links to; reading them alone is not sufficient. If `CONTRIBUTING.md` is absent,
   check the project's documented contribution instructions. Distinguish reporting
   requirements from PR-only requirements; drafting a report does not authorize
   fixes or running unrelated PR checks. For remote source, shallow-clone the
   repository into a temporary directory. Use the applicable issue or discussion template,
   retaining its headings, order, and required fields; omit template comments and
   metadata. If no template is available, tell the user.
   Follow the project's disclosure placement; otherwise put this skill's default disclosure before the first template heading.
   Preserve the template's heading order and required fields.
   For a bug report without a template-prescribed order, put **Expected behavior** before **Actual behavior**, then **Reproduction**.
   Put the installation or invocation in the reproduction and collapse supporting output unless it is needed to understand the visible failure.
2. Incorporate the user's latest corrections and reported experiments.
   Track whether each result came from the user, an agent-run check, or source inspection.
   Distinguish jyn's goals and reported experience from verification evidence.
   Describe agent-run checks through their commands, reproducers, and captured results; do not turn them into claims that jyn personally ran them.
   Do not present proposed or unverified steps as completed checks.
   A matching source defect does not prove a runtime reproduction.
   Do not invent commands, full logs, environment details, or a successful test.
   Capture relevant local patches, forks, nonstandard configuration, and previous attempts with their results.
   Include a working control when it narrows the failure: for example, one picker order fails while the reverse order works.
3. Record the installed version, installation source, and relevant runtime dependencies.
   Name the source precisely, such as a project's GitHub release asset, a distribution package, or a local source build.
   Do not use "official" as a substitute for provenance; state when the source is unknown.
   If the project requests testing the development version, check that requirement and report
   whether it was met. If testing needs a different build, prefer an isolated
   standalone directory over replacing the installed program. Follow
   `dependency-review` for a requested build or update; do not silently expand
   drafting into installation.
4. Inspect relevant source when the report makes a source-based claim. For GitHub,
   resolve the inspected revision's full commit hash and use a permalink with
   precise line anchors; never use branch names or abbreviated hashes in code
   links. For other hosts, use an equivalent stable, revision-specific link when
   available. Omit source links when the report makes no source-based claim.

## Write the report

Organize the report around the maintainer's decision, not the investigation's chronology.
Read the title and body together; preserve the specific request rather than replacing it with a broader problem description.
For a change proposal, name the proposed change before the workaround, unless the required template specifies otherwise.
Before opening any collapsed details, the maintainer should understand the failure, why it matters, the requested outcome,
and why obvious workarounds fall short.
Use supporting details to verify those points, not to introduce them.
When an existing supported approach might meet the need, ask about it without replacing a specific proposal with a general request for advice.
Do not imply that such an approach exists or ask the maintainer to design one unless that is the intended request.
A maintainer can recommend keeping the solution downstream without also supplying an alternative.
Follow required template fields rather than adding duplicate requests.
The [discussion contrast](../holistic-writing/references/reading-examples.md#state-the-request-before-the-workaround) shows how these choices affect reading.

- Use complete sentences and ordinary issue prose, even when conversation uses IRC style.
  State jyn's goals and known experience accurately, without imitating her conversational voice or inventing familiarity, use, or personal verification.
  When jyn supplies first-person experience, preserve direct wording such as "In my case" instead of recasting it as a formal observation.
  Use the established platform or product term, such as "WebView", instead of replacing it with a longer circumlocution.
  Distinguish intended use from current use: "I want to use ..." does not establish "I use ...".
  For a bug report, choose a title that names the general failure rather than one tool that exposes it:
  "user-local Python" rather than "mise Python"; name mise in the body.
  Treat exact UI labels and [improper nouns](https://siderea.dreamwidth.org/1773806.html) as terms of art.
  An improper noun is a domain-specific term that looks like an ordinary description.
  Quote them in titles when Markdown formatting is unavailable, format them distinctly in the body, and define unfamiliar terms on first use.
  For example, write `shows “Offline” instead of “Request access”`, not `pair mode hides request access behind offline state`.
  Include facts that help the maintainer reproduce, diagnose, or fix the failure;
  omit investigation narration and redundant checks when a working control
  already establishes the relevant difference.
- Explain the practical need with a concrete user workflow, not just a desired mechanism.
  When the motivation or upstream responsibility is not obvious, add a motivation section or use the corresponding template field.
  Introduce downstream tools and their roles before relying on them for context.
  Explain the property that makes a technical term relevant to the argument, not just the term itself.
  For example, say that all linked worktrees share Git's common directory, rather than only naming `common_dir()`.
  When execution boundaries matter, identify where processes and data live; "guest" alone does not distinguish a VM from a container.
  Develop a connected explanation: what the user wants to do, what the failure prevents, and what a fix must preserve.
  Use examples to explain those relationships, not as detached facts followed by API details and workarounds.
  When adding an example or constraint, retain the workflow it explains rather than replacing that motivation.
  Then explain where the limitation arises and why existing workarounds fall short, distinguishing each workaround's effects.
  Separate evidence that implicates the target project from assumptions that it must change.
  Do not claim downstream fixes are impossible when they are merely awkward or incomplete.
- Use familiar words: "The command returned ...", not "The execution yielded ...".
  State relevant facts directly; omit defensive commentary about claims the
  report does not make. For related reports, describe the connection and link
  the evidence; do not add "I am linking that history rather than claiming that
  nobody has reported this behavior before".
  For GitHub issues and PRs in the target repository, use `#123` without repeating the full URL.
- Use active voice and concrete subjects: "the reproducer writes the key" or "the launcher calls Python".
  Let inspectable evidence support the request rather than adding personal assurances or attributing agent-run work to jyn.
  Preserve required template text, the disclosure, and quoted output verbatim.
- Unless the project's policy requires different disclosure, start the issue body with this disclosure, before the template's first heading:
  `🤖 this issue description was generated by an LLM 🤖`.
  Keep the template's headings, order, and required fields after the disclosure.
  Leave any disclosure of later human edits to jyn.
- State the visible failure and its practical consequence, then explain the cause
  if established. A report need not diagnose the bug; label hypotheses explicitly
  and keep the observed behavior useful even if the diagnosis is wrong. Put each
  bare GitHub permalink on its own line immediately after the claim it supports.
- Consolidate exact versions, installation provenance, runtime dependencies, and source analysis in a `<details>` block at the end, unless the template requires those fields to remain visible.
  Repeat a version elsewhere only when needed to distinguish results from different versions.
  Include full development commit hashes and the tested invocation; do not repeat hashes in prose when source permalinks already identify them.
  Say "using commit ..." rather than narrating source comparisons.
  For standalone builds, include the build and resource paths and any
  environment variables needed to load them; without these, a reproduction may
  silently use the installed catalogs.
- Give a concrete command and the point where the failure appears; use numbered
  steps when reproduction needs several actions or the template requires them.
  Include relevant inputs, configuration, cursor position,
  or keystrokes. Label proposed steps as unverified when necessary, and distinguish
  runnable reproducers from illustrative code with omitted setup or placeholders.
  If the reproduction requires inaccessible infrastructure, state that limit and
  provide the available evidence instead of implying anyone can run it.
- Include a failing input or artifact when it helps investigation, even if not yet minimized.
  State the minimization limit and use screenshots for visual failures.
  Keep decisive evidence visible; put most reproduction setup, source, and supporting output inside `<details>` unless needed to understand the issue.
  Keep required template headings and fields visible.
  Avoid repeating the visible excerpt inside the collapsed output.
  Quote attached reproducer code inline only when the reader needs it to understand the failure.
- Describe expected behavior separately. Include a small fix suggestion only
  when the evidence supports it; do not turn the report into an implementation plan.
- Preserve observed output verbatim in a fenced block. State when it is only an
  excerpt or came from an older version. Never relabel old output as a new test.

After writing or revising the report, use `holistic-writing` for the whole-artifact editorial review.
Make clear which response from the maintainer would help, and distinguish existing capabilities from proposed changes.

## Check and deliver

Check the final body against the template, applicable contribution requirements,
and latest user evidence. Verify that each code link identifies the inspected
revision and lines, reproduction commands match the reported test, and required
fields are filled or explicitly unknown.
Check template attestations individually; do not mark research, clean-environment,
or latest-version checks as completed without evidence.
Inspect the actual attachments, including archive members, before marking the report ready to submit.
Compare their paths, hostnames, environment values, and private content with the privacy choices and redactions in the report body.
A redacted body does not sanitize attached logs or reproducer scripts.
Preserve raw evidence; when preparing redacted attachments, use labeled copies and inspect the final archive again.
State any remaining identifying metadata or body/attachment mismatch outside the report, even when no credentials appear.
Review each authored sentence for passive voice and hidden actors before
delivery. Rewrite it with the known actor or a direct statement of behavior;
do not invent an actor to satisfy the style rule.
Save the issue body to a Markdown file so copying its contents preserves Markdown syntax.
Use the user's requested path, or choose a descriptive filename in the working directory when no path is specified.
Keep the file current when revising the report.
Return a copy-ready title and a link to the file.
Keep process commentary, remaining checks,
and the issue-creation URL outside the report body. For each check that remains,
give the exact check to run and which sentence or field to replace for each
possible result. Keep unverified claims out of the report; do not turn agent
limitations into first-person claims or claim checks that neither jyn nor an
agent performed. Incorporate her results when she supplies them. If no material
checks remain, say so briefly. After the first draft of each report, provide the
upstream issue-creation URL outside the report body so jyn can submit it.
Drafting does not authorize submission; submit only when explicitly requested and the project's policy permits agent submission.
