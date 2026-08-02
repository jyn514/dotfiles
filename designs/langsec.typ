#set page(paper: "us-letter", margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true, leading: 0.65em)
#set heading(numbering: "1.")

= Language-boundary plan for the dotfiles repository

== Purpose

This plan reduces failures caused by shell parsing, implicit process state,
platform-specific utilities, and unchecked pipelines. It does not propose a
blanket rewrite. Shell remains the correct implementation language for code
that must mutate a running shell; Python becomes the default for standalone
programs that parse data, inspect files, coordinate subprocesses, or maintain
persistent state.

The desired end state has three layers:

- Declarative configuration contains data: abbreviations, tool lists, key
  mappings, and platform policy.
- Python commands perform standalone computation and mutation using explicit
  argument arrays and structured data.
- Small shell adapters apply the few results that must affect the caller:
  environment variables, aliases, completions, options, hooks, and directory
  changes.

== Decision rule

A command should move out of shell when any of these are true:

- It parses output from Git, Make, process listings, JSON, TOML, URLs, or other
  commands.
- It passes filenames or user-controlled text through more than one parser.
- It needs NUL-delimited records, transactional files, cleanup, rollback, or
  several failure branches.
- It constructs commands through `eval`, nested command substitution, or
  quoted shell fragments.
- It has behavior worth testing independently of an interactive shell.
- It is invoked as an executable and does not need to modify its caller.

Keep an operation in native shell when its purpose is to change the current
shell's directory, variables, aliases, abbreviations, completion tables,
keymaps, prompt hooks, job table, or shell options. Even then, computation
should move behind a narrow executable interface once it becomes complicated.

== Architectural conventions

=== Repository layout

Use self-contained subsystems for implementations with their own tests:

```text
tools/
  git-hooks/
    git_hooks/
    tests/
    main.py
  prompt/
    prompt/
    tests/
    main.py
  shell-data/
    shell_data/
    tests/
    main.py
```

Keep tiny user-facing launchers in `bin/` only when a stable command name is
needed. Keep cross-cutting integration tests in `tests/<feature>/`. Do not put
new application logic in `libexec/`.

=== Installation and implementation discovery

Keep every installed command path stable while moving its implementation.
Dotbot continues to link user-facing commands and configuration; implementations
under `tools/<name>/` are not expected to be on `PATH` themselves.

- A normal command in `bin/` should be the Python entry point or a minimal
  launcher beside it. It locates sibling repository files from its resolved
  `__file__`, never from the caller's working directory.
- Git keeps executable launchers at `config/githooks/pre-commit` and
  `config/githooks/pre-push` because `install.conf.json` links that directory.
  Make these launchers Python scripts. `Path(__file__).resolve()` follows the
  installed directory symlink; walking to the repository root from that
  resolved path allows the launcher to import or execute `tools/git-hooks`
  without `DOTFILES`, `PATH`, or a machine-local embedded path.
- Each launcher must work when invoked through the installed symlink, directly
  from the checkout, from another working directory, and from a linked Git
  worktree.
- A caller switch includes the corresponding `install.conf.json` change, if
  any, and an installation test that resolves the final executable target.

=== Process interfaces

- Pass subprocess arguments as arrays. Never construct a shell command string
  when direct execution is possible.
- Use `os.fsencode`, `os.fsdecode`, and bytes-oriented subprocess output for
  filesystem paths on Unix. Filenames are not necessarily UTF-8.
- Use JSON when records have named fields and NUL-delimited bytes when records
  are paths or environment entries.
- Use ordinary stdout for requested results and stderr for diagnostics. A
  nonzero exit status must describe an operation that did not complete.
- Avoid generating general shell programs. If caller mutation requires shell
  text, expose a format-specific subcommand such as `activate --shell fish`,
  validate every value, and keep evaluation in one audited adapter.
- Write persistent state beside its destination, validate it, then replace the
  destination atomically. A failed refresh must leave the last good state.

=== Shared Python support

Create a small internal package only after two consumers need the same
behavior. Likely shared primitives are:

- `run_checked(argv, *, input=None, cwd=None)`, preserving stderr and the
  producer's exit status;
- filesystem-safe NUL record encoding and decoding;
- atomic file replacement with mode preservation and cleanup;
- platform and executable discovery;
- deterministic diagnostic formatting;
- test helpers that install mock executables and capture exact argv as NUL
  records.

Do not build a general framework. Prefer a duplicated five-line helper until a
stable common contract is visible.

=== Open protocol decisions

Do not begin the affected migration until its decision is recorded by a small
prototype and contract test:

- Case conflicts: enforce a conservative conflict-equivalence policy for
  case-insensitive Windows, macOS, and Linux filesystems. Compare path names
  after NFC normalization and Unicode full case folding, while retaining the
  original filesystem spelling and bytes for diagnostics and Git calls. This
  deliberately rejects some pairs that a particular host might permit.
- Make database parsing: verify the relevant GNU Make versions and fixtures.
  If no stable record grammar can be documented, retain the existing helper
  instead of replacing a small parser with a larger fragile one.
- Python runtime: distinguish the version needed to run installed commands from
  the version used by repository development tests. Either enforce a minimum
  runtime in `setup.sh` or choose data formats and APIs available on every
  currently supported distro; do not infer the runtime baseline from `dev/test`.

== Conversion inventory

=== Git hook subsystem

/ Current files: `config/githooks/pre-commit`, `config/githooks/pre-push`, and
  `config/githooks/pre_commit_hooks/*.py`.

/ Target: A Python hook driver owns index inspection, snapshot materialization,
  hook selection, and diagnostics. Installed hook files become tiny launchers
  that locate and execute the driver.

/ Convert:
  - Resolve Git directories with `git rev-parse` and filesystem APIs.
  - Read `git diff --name-only -z` and related output as bytes.
  - Materialize the staged snapshot in an owned temporary directory without a
    shell pipeline.
  - Invoke checks with explicit path batches and deterministic ordering.
  - Run local repository hooks before global checks and preserve their exact
    status.
  - Move pre-push ref parsing and Rust-change detection into the same package.
  - Normalize case-conflict comparisons with a documented cross-platform
    policy while retaining original bytes for diagnostics and Git calls.
  - Remove independent UTF-8 assumptions in `util.py` and the LFS checker.

/ Keep in shell: Only a portable launcher, if direct installation of the Python
  entry point is impractical. It should contain no pipelines or filename
  parsing.

/ Verification:
  - Filenames containing spaces, newlines, leading dashes, undecodable bytes,
    decomposed Unicode, and case-only differences.
  - Empty commits, deletions, renames, submodules, symlinks, linked worktrees,
    bare Git directories, and failing Git commands.
  - Local-hook failure, checker failure, interrupted snapshot creation, and
    cleanup after every exit path.

=== Prompt and status computation

/ Current files: `bin/prompt-command`, `config/claude-statusline.sh`, and prompt
  functions in `config/profile`, `config/config.fish`, and `config/zshrc`.

/ Target: A Python executable computes prompt facts and emits the complete final
  prompt for a named render target. Facts remain structured Python objects
  internally; no structured representation crosses into the shell.

/ Convert:
  - Repository discovery and Git/Jujutsu status collection.
  - Duration formatting, host/model labels, path shortening, and status icons.
  - Claude status-line JSON parsing.
  - Timeout handling and suppression of optional-tool failures.
  - ANSI styling, visible-width calculation, multiline layout, and the
    nonprinting markers required by each target shell.

/ Protocol: Interactive shells invoke
  `prompt-command <target> <status> <duration-ms>` with the working directory
  and terminal context inherited normally. Named interactive targets include
  `bash`, `zsh`, `fish-left`, and `fish-right`. Shell identity and any additional
  target-specific context use explicit arguments, not encoded records. Claude
  invokes `prompt-command claude` with its JSON object on stdin. The command
  writes only the complete prompt bytes for that target to stdout, with no
  required trailing newline. Diagnostics go to stderr. A nonzero status causes
  the adapter to display a fixed minimal native fallback; the adapter captures
  output before use so partial stdout from a failed renderer is discarded.

  Bash output includes Readline `\[` and `\]` markers. Zsh output includes
  `%{` and `%}` markers. Fish targets emit directly printable left- or
  right-prompt text. The Claude target reads Claude's input JSON from stdin and
  emits its complete plain status line. No adapter invokes `jq`, parses fields,
  adds ANSI escapes, or recomputes visible width.

/ Keep in shell:
  - Capturing `$?`, command duration, shell mode, and prompt lifecycle events.
  - Calling the appropriate render target and selecting the fixed fallback on
    failure.
  - The native Bash/Zsh prompt hook and Fish left/right prompt function names.

/ Verification:
  - Narrow terminals, long paths, multiline prompts, non-ASCII glyphs, detached
    repositories, conflicts, absent tools, timeouts, and commands crossing a
    minute boundary.
  - Snapshot tests compare exact output bytes for every render target and
    independently verify visible width versus terminal control bytes.
  - Failure tests prove that diagnostics and partial stdout never enter the
    installed prompt and that every adapter selects its minimal fallback.

=== Shell abbreviation validation

/ Current files: `lib/abbr.txt`, `config/profile`, and `config/config.fish`.

/ Target: Keep `lib/abbr.txt` as the single source for static cross-shell
  abbreviations. Its compact line format already represents the required data;
  the duplicate-name bug requires validation, not migration to a richer format.

/ Grammar:

```text
# comment
name=expansion text
```

- Blank lines and lines beginning with `#` are ignored.
- The first `=` separates the name from the expansion; later `=` characters
  belong to the expansion.
- Names are nonempty and contain no whitespace, `=`, newline, or NUL. The
  existing punctuation used by aliases such as `:q` remains valid.
- Expansions are nonempty single-line text. They may intentionally contain shell
  syntax such as variables, pipelines, or `&&`; loaders must pass that text as
  one alias/abbreviation value rather than evaluate it while loading.
- A name may appear exactly once.

/ Convert: Nothing. Retain the existing native Bash/Zsh and Fish loaders because
  applying aliases must mutate the current shell and the format is trivial.

/ Add: A Python validator used by `dev/test` checks the grammar and duplicate
  names without generating shell source. Startup loaders continue to propagate
  read and registration failures. Add native parser tests proving each loader
  treats the expansion as one literal value during registration.

/ Keep separate: Git aliases remain Git configuration. Cargo discovery and Fish
  command-scoped abbreviations remain a cache concern; they do not extend the
  `abbr.txt` grammar.

/ Verification:
  - Duplicate and empty names, empty expansions, comments, extra `=` characters,
    quotes, backslashes, variables, pipelines, leading dashes, Unicode, malformed
    lines, loader read failure, and registration failure.

=== Tmux administration

/ Current files: `config/set-tmux-env.sh`, `config/renumber-tmux-sessions.sh`,
  `config/attach-session.sh`, and complex `run-shell` fragments in
  `config/tmux.conf`.

/ Target: Python commands call tmux directly and treat tmux format output as an
  explicit protocol.

/ Convert:
  - Session enumeration and transactional renumbering, including collision-free
    temporary names and rollback.
  - Detached-session selection and attach policy.
  - Exact environment synchronization after a clean login shell has produced
    environment records.
  - Clipboard, drag-and-drop, editor-open, and web-search dispatch currently
    embedded in nested tmux/shell quoting.

/ Environment strategy: Bash remains the environment provider because the
  desired environment is defined by shell startup files. After sourcing them,
  Bash directly `exec`s the Python receiver. Python reads the inherited
  `os.environ` and calls `tmux set-environment`; no environment serialization is
  needed. The adapter explicitly carries the absolute tmux executable plus
  `TMUX` and `TMUX_TMPDIR`, preserving unset values as unset and empty values as
  empty.

/ Keep in shell: Tmux configuration statements and, if necessary, a minimal
  login-shell command that sources the profiles.

/ Verification:
  - Custom tmux sockets, unset versus empty variables, values containing
    whitespace, equals signs and newlines, no sessions, mixed numeric and named
    sessions, every rename failure point, signals, and rollback failures.

=== Make task inspection

/ Current functions: `tasks`, `recipes`, and `recipies` in `config/profile`.

/ Provisional target: Subject to the open Make decision above, a Python command
  runs a supported GNU Make version with `-npRr`, parses its documented database
  records, and emits either target names or complete rule records.

/ Convert: All parsing. The command must preserve numeric target names, colons in
  recipes, tabs, and multiline bodies, and must propagate Make failures.

/ Keep in shell: Optional aliases named `tasks`, `recipes`, and the misspelled
  compatibility alias. They should directly execute the Python command.

/ Verification: Pattern rules, special targets, numeric targets, generated
  targets, included makefiles, empty databases, failed includes, and recipe text
  containing colons or comment-like prefixes.

=== Graphical manual-page lookup

/ Current function: `man` in `config/profile`.

/ Target: A Python command accepts the same page and optional section, resolves
  supported sections, constructs URLs with a URL library, probes providers, and
  launches the first valid result. If none succeeds, it exits with a distinct
  fallback status.

/ Convert: URL construction, HTTP status handling, distribution metadata, and
  `man -k` parsing.

/ Keep in shell: A short function that delegates option-heavy invocations to
  the native `man`, calls the Python resolver for the simple case, and invokes
  native `man` when the resolver requests fallback.

/ Verification: Page names treated as opaque arguments, sections, absent
  network access, HTTP errors, missing distribution tools, ambiguous index
  results, launcher failure, and native fallback status.

=== Package and executable inspection

/ Current functions: `what_belongs`, `what_runs`, `what_package`,
  `pip_upgrade_all`, and `purge_removed` in `config/profile`.

/ Target: Separate Python commands for read-only package queries and explicit
  mutation commands for upgrades or purges.

/ Convert: Package-manager detection, executable resolution, output parsing, and
  argument construction. Require confirmation in the user-facing mutation
  command rather than hiding confirmation inside a parsing pipeline.

/ Keep in shell: Convenience aliases only. Do not source implementations.

/ Verification: Debian and RPM output, symlinked executables, missing package
  managers, empty query results, unusual paths, partial query failure, no
  packages to mutate, and exact propagation of `sudo`, `pip`, or manager errors.

=== File-picker action dispatch

/ Current locations: Fish `fzf_action` and `fzf_file_action`, Zsh `fzf-file`,
  and tmux copy-mode commands.

/ Target: Split picker handling at the process boundary. A Python external-action
  dispatcher reads NUL-delimited selections and owns actions such as open, copy,
  search, or launch. Fish and Zsh keep separate native adapters for inserting a
  selection into or executing the current command-line buffer.

/ Convert: Shared selection validation, multiple-selection policy, URL opening,
  editor invocation, clipboard dispatch, and cancellation/error classification
  for external actions.

/ Keep in shell: Running the picker when it is coupled to the line editor,
  reading its selection without lossy command substitution, and applying insert
  or execute actions to the current command-line buffer. Do not round-trip those
  actions through Python merely for uniformity.

/ Verification: Empty selection, cancellation, picker failure, multiple paths,
  embedded whitespace/newlines, leading dashes, relative paths, and distinct
  insert-versus-execute actions.

=== Cache producers

/ Current locations: Homebrew and Cargo cache generation in
  `config/config.fish`, plus any future generated completion or activation
  files.

/ Target: A Python cache command owns locking, sibling staging paths,
  validation, atomic replacement, and stale-cache fallback.

/ Convert: Filesystem operations and metadata comparison. The producer command
  itself may still be an external program such as Homebrew or Cargo.

/ Keep in shell: Sourcing a validated cache because it must mutate the current
  process. Source only after the Python command reports success or explicitly
  reports that a previous valid cache is available.

/ Verification: Concurrent shells, interrupted writes, invalid generated
  syntax, read-only directories, producer failure, rename failure, stale cache,
  first-run failure, and cleanup of abandoned staging files.

=== Browser configuration helpers

/ Current file: `config/glide.ts`.

/ Target: Keep browser API integration in TypeScript, but extract pure URL and
  label algorithms into testable TypeScript modules. Do not move browser-native
  behavior to Python merely for language uniformity.

/ Convert structurally:
  - Move repository URL parsing and hint-label generation into pure modules.
  - Remove unconditional debug logging and logging of page titles, selections,
    or visited private URLs.
  - Wrap nullable browser selections and tabs at API boundaries.
  - Keep process execution as argument arrays.

/ Verification: GitHub and nested GitLab paths, malformed URLs, absent active
  tabs, no selection, duplicate and empty labels, Unicode labels, and disabled
  site transitions.

== What should remain native configuration

Do not rewrite these merely to increase Python coverage:

- Fish, Zsh, Bash, Readline, tmux, Kitty, Helix, Kakoune, Vim, and Neovim
  keybindings and native options.
- Neovim plugin configuration and browser API callbacks.
- Shell completion registration and line-editor widgets.
- Simple exports and path additions whose inputs are fixed literals.
- One-line aliases that contain no parsing or mutation beyond invoking a
  command.

Native configuration still needs tests for duplicate bindings, precedence,
nullable API results, reload idempotence, and syntax validation.

== Migration phases

=== Phase 0: Contracts and fixtures

+ Record the minimum Python version available to installed commands on every
  supported platform. If the migration requires a newer version, make that an
  explicit setup change with container coverage; otherwise restrict runtime
  code to the established baseline.
+ Inventory every function or script being replaced, its callers, supported
  platforms, output format, side effects, and current failure behavior.
+ Add characterization tests before moving code. Include success, empty result,
  malformed result, missing dependency, producer failure, consumer failure,
  unusual arguments, and concurrent execution where relevant.
+ Add reusable byte-safe subprocess and mock-executable test helpers.
+ Use only the established runtime baseline unless a subsystem already owns
  dependencies.

Exit criterion: Every first-wave command has a documented interface and tests
that fail if its established useful behavior is lost.

=== Phase 1: Git hooks

+ Resolve and document the case-conflict policy before changing its comparison
  algorithm.
+ Build the Python driver and migrate one check at a time.
+ Keep installed hook paths stable.
+ Compare old and new results against disposable repositories before switching
  the default launcher.
+ Delete superseded shell orchestration only after byte-path, linked-worktree,
  and failure-path tests pass.

Exit criterion: Hook orchestration contains no shell pipeline and all Git path
data remains byte-safe until display.

=== Phase 2: Standalone profile utilities

+ Prototype the GNU Make database parser. Migrate Make inspection only if its
  supported grammar and fixtures satisfy the rollback criteria.
+ Migrate graphical manual lookup and package queries.
+ Replace function bodies with direct executable calls.
+ Preserve command names and statuses so interactive habits do not change.

Exit criterion: `config/profile` contains no Awk program, URL parser, package
output parser, or multi-stage data pipeline.

=== Phase 3: Tmux and picker dispatch

+ Move session algorithms and action dispatch to Python.
+ Retain declarative tmux bindings that invoke the new commands.
+ Exercise every rollback point using saved tmux mocks before testing against a
  disposable tmux server.

Exit criterion: Tmux configuration contains no nested `bash -c`, `xargs`, or
multi-layer quote construction for user-controlled selections.

=== Phase 4: Shell data validation and caches

+ Document and validate the existing `lib/abbr.txt` grammar without changing its
  format or adding generated abbreviation files.
+ Migrate Fish Cargo aliases and generated shell caches to the shared cache
  protocol.
+ Keep old files readable for one transition commit if rollback across machines
  matters; otherwise switch atomically in one commit.

Exit criterion: Repository tests reject invalid or duplicate abbreviations,
native loaders preserve expansion text, and failed cache producers cannot
replace a working cache.

=== Phase 5: Prompt boundary

+ Characterize all visible prompt variants first.
+ Move fact collection and shared policy into Python.
+ Implement final-output render targets for Bash, Zsh, Fish left/right prompts,
  and Claude status lines.
+ Replace shell formatting with minimal invocation/fallback adapters; do not add
  a structured interchange format.
+ Measure startup latency and add timeouts before enabling by default.

Exit criterion: Shell prompt code handles lifecycle, invocation, and fallback
only. Repository inspection, duration/path policy, styling, escaping, width,
and layout have one implementation with target-specific final renderers.

=== Phase 6: Cleanup and enforcement

+ Remove dead compatibility code and obsolete tests after all callers migrate.
+ Add a repository check that flags new complex shell patterns: nested command
  substitutions, unchecked producer pipelines, direct parsing of newline-based
  filename output, and persistent writes without atomic replacement.
+ Document approved exceptions beside the code with the reason shell mutation
  is required.

Exit criterion: New standalone parsing or orchestration code defaults to Python,
while shell-native configuration stays small and auditable.

== Per-migration decision record

Before implementation, add a short record for each conversion containing:

- Current command names, callers, platforms, dependencies, side effects, and
  baseline tests.
- The exact new protocol, executable path, installation mapping, and fallback.
- Shell lines and parsing stages expected to be removed; reduction is a goal,
  not a hard quota.
- Added runtime processes and measured cold and warm latency. Interactive
  migrations must set a latency budget before the caller switch.
- Required native programs and the behavior when each is unavailable.
- A rollback trigger, such as slower prompt rendering, lost platform support,
  a protocol that cannot represent current inputs, or a larger/more fragile
  parser than the implementation it replaces.
- Verification evidence required before removing the old implementation.

The caller-switch commit must update this record with measurements and test
results. If the new boundary does not reduce parsing ambiguity, failure-state
complexity, or duplicated policy, keep the existing implementation.

== Commit strategy

Each migration should use narrow commits in this order:

+ Characterization tests and fixtures.
+ New implementation behind an explicit command interface.
+ Caller switch with integration tests.
+ Removal of the old implementation and obsolete compatibility code.

Do not combine unrelated shell rewrites. Preserve existing command names where
they are user-facing. A commit body should explain any changed failure behavior,
protocol choice, or platform assumption.

== Validation matrix

Every converted subsystem should select applicable checks from this matrix:

- Exact argv, environment, cwd, stdin bytes, stdout bytes, stderr, and status.
- Empty, single, and multiple records.
- Spaces, tabs, newlines, leading dashes, glob characters, invalid UTF-8 bytes,
  and canonically equivalent Unicode.
- Missing executables and unsupported platforms.
- Producer failure before output, after partial output, and consumer failure.
- Concurrent writers, interrupted writers, and stale valid caches.
- Native parser validation for every shell/config adapter.
- End-to-end execution on an owned disposable repository, tmux server, cache
  directory, or other resource when mocks cannot prove the full contract.

`dev/test` remains the broad gate. Focused unit tests should run without Fish,
Zsh, Neovim, tmux, or a graphical session unless the test specifically covers
that native integration.

== Risks and mitigations

/ Python startup cost: Keep prompt calls bounded and measured; use one process
  per rendered component rather than subprocesses for individual facts, avoid
  parsers in shell adapters, and cache only when measurement justifies it.

/ Bootstrap availability: Confirm Python before installing Python-backed
  commands. Retain minimal degraded shell behavior where a machine can
  legitimately lack Python.

/ Shell activation still requires evaluation: Narrow generated activation and
  cache files to a versioned contract per shell, validate before output, and
  never mix diagnostics with stdout. Static `abbr.txt` loading does not require
  generated shell source.

/ Behavior drift during rewrites: Characterization tests precede implementation,
  and caller switches remain separate from cleanup.

/ Over-centralization: Keep browser and editor APIs in their native languages.
  Share only stable primitives, not a universal dotfiles runtime.

/ Arbitrary filenames: Keep paths as bytes internally on Unix and decode only
  for escaped diagnostics. Tests must include undecodable names.

== Recommended first milestone

The first deliverable should be the Git-hook subsystem. It already uses Python,
has clear executable boundaries, handles adversarial filenames, and contains
enough shell orchestration to demonstrate the architecture without affecting
interactive startup.

That milestone consists of:

+ A byte-safe Git command layer.
+ Unicode-aware case-conflict policy.
+ A Python staged-snapshot driver.
+ Migration of pre-commit orchestration and pre-push ref parsing.
+ Unit tests plus disposable-repository integration tests.
+ Tiny stable launchers at the existing hook paths.

After that milestone, reassess complexity, startup cost, and test ergonomics
before migrating prompts or shell-generated caches.
