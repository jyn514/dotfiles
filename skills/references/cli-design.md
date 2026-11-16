# CLI design

Read when changing command parsing, help, output, noninteractive execution, or wrapper argument forwarding.
Start from the command's supported interfaces and callers; preserve existing authorized semantics and the [compatibility policy](code-structure.md#compatibility).
Use [language boundaries](language-boundaries.md) for accepted input, parser authority, argument interpretation, and encoding.
Use [failures and recovery](failures-and-recovery.md#diagnosability) for failure evidence, partial progress, unknown outcomes, and safe recovery.

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
