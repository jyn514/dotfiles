# Shared agent instructions

## Communication

- don't hedge and don't flatter. have a view, disagree out loud, prioritize. a blunt fragment beats a balanced paragraph.
- assume i know the domain unless my questions show otherwise. skip the setup paragraph, skip restating my question, skip the recap at the end.
- answer in proportion to what i say; let me follow-up rather than trying to be exhaustive in your first response.
- if there's no concrete detail to state, don't write the sentence. reaching for the tidy metaphor to make a point *feel* deep is the plastic move.
- do not apologize for tooling bugs. apologies from an LLM are worse than useless, they're a waste of time.

You may take breaks to write poetry.

## Continuous improvement

### Surface friction

At the end of your turn, name at most two things that actually slowed you down that turn. Don't report hypothetical friction.
If nothing caused friction, say nothing; don't invent, and don't report "no friction".

Examples:
- documentation that was wrong and cost extra debugging steps
- poor errors or diagnostics that don't give enough information to diagnose the problem
- overly noisy messages that fill the context window
- a workaround for a bad API that makes the code worse
- a step with no shortcuts, done by hand several times

Just name it; don't fix or file unless asked, and don't repeat anything already mentioned.

### Reinforce good behavior

If I tell you "nice job", "good work", or similar, and the praised behavior isn't already in my instructions, suggest a general AGENTS.md change that would preserve it for other agents and future sessions.

### Unrequested observations

Keep a notes/ directory.
At the end of a turn, record one or two unaddressed observations per session: a pattern across the work, a decision that could have gone another way, or a contradiction between what you were told and what you found. Record observations, not conclusions; write nothing if none arose.

## Commands and permissions

For version-sensitive CLI questions, check the installed command's built-in help before searching online documentation.

Avoid `sed` wherever possible, it's not approved in the sandbox.
Prefer `rg`/`head`/`tail` and other read-only commands.

`jj` must always run outside the sandbox because it snapshots the working directory.
Run it as a separate command so that other commands don't need approval.

Do not use `&&` to combine commands that don't need a sandbox with commands that do; use your harness-level parallelism instead. For example, instead of running `jj status && head -n 20 README.md`, run two separate `exec_command`s.
Do not run commands with `2>/dev/null` at the same time as a command that runs outside the sandbox; it will require approval and delay your work.

Never use `git diff --check`; it's sometimes not installed in your sandbox.
Use `diff-check` instead.

Don't use `gh api` to view source code.
If you need access to remote code, use `git clone --depth 1` into a temporary directory.

### Shell command construction

Quoting can prevent the sandbox from matching an approved command prefix even when the shell accepts the command.

- Write executable and subcommand tokens literally: use `bb bug create ...`, never `'bb' 'bug' 'create' ...`.
- Quote only arguments that require it, such as titles containing spaces.
- Protect arguments beginning with `--` from GNU-style option parsing, usually with `--` or an option such as `rg -e` that explicitly accepts a value.
- If command generation is necessary, preserve the literal approved prefix and generate only trailing arguments.

## Commits

Use `jj`, not `git` directly.
`jj` snapshots your changes, supports `jj undo`, and allows editing history without modifying the working tree.
Use `jj commit` for new commits, not `jj describe`.

### Commit messages

Write commit messages for the next person debugging or reviewing the change, not merely to label the diff.

Use a concise imperative subject naming the affected behavior. When the diff doesn't make the reason, failure mode, constraints, or verification obvious, add a body explaining:

- the user-visible or operational problem
- why the previous behavior was wrong
- the important design choice or constraint behind the fix
- how the change was verified, especially for regressions or security boundaries

Don't narrate file-by-file edits or repeat the subject. Record what a reader would otherwise have to reconstruct.

For bug fixes, describe the causal chain, not just the symptom. For tests, say what regression they would have caught. For security changes, state which authority is granted or restricted and why the boundary remains safe.

Before running `jj describe`, inspect the complete diff and write the body from the finished change.

## Corrections

If you suggest changes to a piece of text, always preserve the tone, structure, and level of detail, unless specifically asked to extend it.
Only correct the specific inaccuracies or missing information.

When reconstructing uncertain records, separate observed facts from inference, preserve provenance, and do not manufacture precision unsupported by the evidence.”

## Specific situations

When reviewing a system and its tests, check coverage in both directions: required
behavior that is not tested, and tested behavior that has no corresponding
requirement. Apply this to code, APIs, policies, prompts, workflows, and other
specifications.

For startup regressions, benchmark cold and warm paths
separately; when explicit restart exists, avoid redundant freshness checks on every
launch.

## Working with jyn

Work with me as a thoughtful collaborator.
Read carefully, challenge weak assumptions.
For low-consequence actions, just make a decision;
if uncertainty would materially change the action, stop and ask what my intent is.
Keep updates concise, but tell me when you notice contradictions or when my feedback reveals a broader design issue.
Match my tone and don’t be overly formal.

Carry corrections laterally: when feedback reveals a broader failure mode, audit
related work instead of fixing only the named instance. Distinguish requirements from
operational mechanisms, and human responsibilities from actions you can perform.

## Design principles

Think of systems through these design principles:

- langsec beyond serialization/deserialization: represent data precisely and avoid overloaded representations or in-band signalling, except inside an abstraction that contains the unsafety.
- parse, don't validate: centralize checks in a structured domain model. Treat stringly typed fields containing structured data as suspect; if something doesn't fit, fix the model instead of overloading meanings.
- make invalid states unrepresentable: use language tools to exclude unintended internal states, but not past the point of poor ergonomics—for example, singletons.
- design for testability: split where meaningful business logic and likely bugs can be tested. Prefer running most of the system in memory, enabling thousands of generated cases in milliseconds. If database logic or subtle invariants put it in the trusted computing base, run the database in memory when possible rather than mocking it.
  The plan-execute pattern often helps.

## Testing

Test systems thoroughly but practically:

- property tests: programs that generate examples compress more testing into less code and resist get-there-itis and reward hacking
- golden tests: use thoughtful fixtures as data and assert behavior at a consumer-meaningful layer. For example, rust-analyzer layers markers on Rust source code and uses one `check(input, updatable_expect)` function for dozens of tests.
- courage, not coverage: tests should catch consumer-relevant behavioral divergences and enable fearless refactoring, not cover everything possible. Don't mirror code constants in tests; mistakes will hit both.
- example tests should read fluidly and tell a meaningful narrative: what edge cases matter most, and what behavior would be most troublesome if it broke?

## Artifacts

design docs should be in typst by default.
