# CLI design

Read when designing or changing command structure, arguments, defaults, parsing, help, output, noninteractive execution, or wrapper argument forwarding.
Start from the caller's tasks and the command's supported behavior.
Distinguish behavior that must remain supported from interface details that may be redesigned, following the [compatibility policy](code-structure.md#compatibility).
Use [language boundaries](language-boundaries.md) for accepted input, parser authority, argument interpretation, and encoding.
Use [failures and recovery](failures-and-recovery.md#diagnosability) for failure evidence, partial progress, unknown outcomes, and safe recovery.

## Design around tasks

When creating or revising an interface, sketch representative invocations before specifying its options: the main task, a small custom input, and a relevant advanced operation.
Use the tasks to choose commands, arguments, and defaults rather than exposing each implementation parameter as a required flag.
A narrow parsing fix does not require redesigning the surrounding interface.

Separate routine choices from overrides.
Give stable project resources sensible defaults and keep their paths overridable.
Require arguments for choices the caller needs to make, not facts the program already knows.
Make the selected defaults discoverable in help.

For an inherited or replacement interface, inspect actual scripts, documented uses, and independently maintained callers to establish the required compatibility.
Do not treat every existing flag or required argument as a requirement for the new interface.
Preserve the contracts those callers need; simplify details within the authorized change rather than copying the old invocation unexamined.

Check each representative invocation from preparation through the result.
What must someone locate, prepare, type, and understand to complete the task?
Where setup is necessary, provide a repeatable setup operation using stable paths rather than documenting session-specific temporary files.
Keep network access and other setup effects explicit; a shorter command does not justify hiding them in ordinary execution.

For example, a dictionary generator might require paths for vocabulary, pronunciation data, rules, and an output directory.
If the project supplies stable vocabulary and rules and most runs use the same pronunciation source, default those inputs while retaining explicit overrides.
Then the routine invocation can be `cocoa-dictionary --output-dir target/my-dictionary`, and a small custom run adds `--words my-words.json`.
If public pronunciation data needs downloading, make preparation a repeatable explicit operation rather than requiring the caller to reconstruct a download command and temporary path.
The output directory remains an explicit choice in this example; another tool's tasks may justify a different default.

## Help before ordinary execution

Recognize supported help requests before ordinary execution and its preconditions.
For example, `deploy --help` should explain required credentials rather than fail because credentials are absent or initialize a deployment client.
Help must work without credentials, network access, optional tools, generated output, or running daemon state.
Do not perform ordinary startup mutations or command effects to print help.
Separate help dispatch from effectful initialization rather than documenting an environment-preparation workaround.

Follow the command's documented help spellings, output stream, and exit status.
For a new help contract, print usage to stdout and exit successfully.
Explain the purpose, accepted arguments and options, relevant defaults, and representative use when it is not self-evident.
For commands with persistent, remote, or destructive effects, explain the affected state and required inputs without performing those effects.
Document whether an argument-free invocation performs default work or shows help.
For invalid input, identify the offending argument, point to the relevant help, and preserve the documented failure status.

## Noninteractive execution

Do not unexpectedly prompt when stdin is not a terminal.
Use the command's explicit input or confirmation mechanism, or fail with an explanation of the missing input before dependent effects.
Do not turn absent interactive input into consent or invent a blanket force flag.
A command reading a redirected document must not consume its first line as an answer to a confirmation prompt.
Preserve intentional interactive-only and stream-input contracts.

## Wrappers and argument forwarding

Identify which arguments the wrapper owns and which belong to the wrapped command.
For wrappers with their own options and a `--` forwarding boundary, parse wrapper options only before that boundary.
Forward every subsequent argument unchanged, including argument boundaries, empty strings, and option-like values.
Do not silently forward unknown wrapper options before `--` unless that is the documented grammar.
A transparent wrapper with no options can forward the entire argument vector without adding a parser.
Document the forwarding form, significant ordering constraints, output behavior, and exit status.
Preserve the wrapped command's stdout, stderr, and exit status unless the wrapper explicitly promises a different contract.

For example, in `wrapper --profile test -- compiler --help`, `--help` belongs to the compiler.
The wrapper must not intercept it as a request for its own help or reconstruct the forwarded arguments as a shell string.
Test the supported forwarding contract through the invoked wrapper, not only its parsing helper.

## Human output and automation

Default CLI output must be human-scannable.
Show the action, material inputs, current phase, result, and next action; keep hashes and internal data in receipts or explicit machine-readable output.
Report failures once, stating what failed, why, cleanup/publication status, and recovery action.
Use stdout for results and stderr for progress or diagnostics.
Do not describe partial progress or an unknown outcome as completed work; use the failure owner's distinctions when choosing what to report.

Treat human-readable output as changeable unless it is a documented public interface.
Identify what existing automation actually consumes: exit statuses, a quiet result, a structured mode, or documented text.
Maintain that contract rather than forcing every command to add a machine format.
Where new automation support is in scope, choose and document an appropriate interface, including output shape, stream, and exit behavior.
Use distinct exit statuses only when callers need to handle those outcomes differently; otherwise a consistent failure status suffices.
Avoid color-only distinctions and keep redirected results free of progress noise.

Test representative success and failure output as a user-facing contract.
For help changes, exercise the supported help entrypoint in an unprepared disposable environment and check output, exit status, and absence of ordinary effects.
For noninteractive changes, close or redirect stdin as the supported caller does and verify that execution cannot wait for an unexpected prompt.
For an automation contract, assert the promised output and statuses through its actual consumer boundary.
