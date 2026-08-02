#set document(title: "Garden: a small Trellis executor")
#set page(paper: "us-letter", margin: 1in)
#set text(font: "New Computer Modern", size: 11pt)
#set par(justify: true)

= Garden: a small Trellis executor

*Status:* Design only.

== Objective

Garden is a local build executor for small projects.
It loads a project-owned action graph, normalizes and executes command rules through Trellis, and uses Meristem for incremental recomputation and concurrent demand.

Garden should make a heterogeneous build no harder to operate than a shell script while providing the properties that shell scripts lack:

- explicit file, glob, environment, and executable dependencies
- dependency ordering inferred from declared inputs and outputs
- bounded parallel execution with coarse resource reservations
- persistent local reuse with an explanation for every cache decision
- graph, command, and dependency queries without executing actions
- safe ownership and cleanup of generated outputs

Garden is intended for repositories with tens or hundreds of actions, one machine, and one trusted build definition.
It is not a distributed build system or a package manager.

== Design boundary

Trellis owns the portable rule vocabulary, input normalization, marker expansion contract, pure action-graph construction, canonical dependency evidence, depfile integration, command execution contract, and persisted cache-row mechanics.
Xylem owns the default Make/Ninja depfile syntax.
Meristem owns dependency recording, concurrent demand, cycle detection, and in-process memoization.

Garden supplies the host behavior which Flower cannot supply outside a site build:

- loading a project build definition
- resolving rule and group names into demanded Trellis nodes
- validating host path and output-ownership policy
- supplying filesystem, environment, and executable capabilities
- scheduling requested targets within a resource budget
- publishing completed backing artifacts atomically
- choosing local manifest and scratch paths and maintaining output-ownership metadata
- reporting progress, failures, and cache explanations
- implementing query and cleanup commands

Garden must not depend on Flower namespaces, page phases, virtual page outputs, site configuration, or Flower's output directory.
Changes needed to make Trellis independently usable belong in Trellis rather than in compatibility code copied into Garden.

== Principles

=== Saving work is not publishing it

Garden runs only when explicitly invoked.
It does not install commit hooks, rewrite source files, or prevent a repository snapshot from being created.

=== Correct misses are preferable to unsound hits

Garden may rerun an action when it cannot prove reuse safe.
It must never reuse an action merely because its declared outputs exist or their modification times appear recent.

=== Authority is visible

An action inherits Garden's complete startup environment and commands retain the caller's ordinary operating-system authority.
Garden writes and deletes only its state directory, per-action scratch directories, and outputs owned by the loaded graph and recorded manifest.

Garden does not claim to sandbox commands.
The build definition and every invoked executable are trusted;
the environment and declared inputs describe cache identity, not a security boundary.

=== The operator can ask why

For every selected action, Garden can report why it ran, why it was reused, what it depends on, and which target demanded it.
Machine-readable output carries the same information as human output.

== Project interface

The default build definition is `garden.clj` at the project root.
Garden locates the root by searching the current directory and its ancestors, and `--root PATH` selects one explicitly.

The file is trusted Clojure code evaluated once while constructing the graph.
Its final value is a map with this versioned shape:

```clojure
{:garden/version 1
 :garden/default ["check"]
 :garden/groups
 {"check" ["python" "clojure" "node" "rust" "syntax"]}
 :garden/rules
 [{:trellis
   {:name "python"
    :inputs {:always true
             :executables ["pytest"]}
    :action ["pytest" "-n" "8" "--quiet"]}
   :garden/resources {:jobs 8}}

  {:trellis
   {:name "syntax"
    :inputs {:always true
             :executables ["sh"]}
    :action ["sh" "dev/check-syntax"]}
   :garden/resources {:jobs 1}}]}
```

These test actions deliberately have no outputs and run on every invocation.
A producing action becomes eligible for persistent reuse by declaring its real outputs and writing each Trellis output marker supplied in its argument vector.

The top-level map is closed: unknown keys and unsupported versions are errors.
Rule wrapper maps are also closed and contain `:trellis` and optional `:garden/resources`.
Garden removes its wrapper fields before passing the authored rule to Trellis normalization.

Rule names are required, unique target and diagnostic labels.
They do not participate in cache identity, so renaming otherwise unchanged work preserves reuse.

Groups are named target sets, not executable actions.
A group may contain rule names or other group names, groups may not collide with rule names, and recursive groups are rejected with the complete cycle.
The default target list is required and may contain either kind of name.

== Supported Trellis surface

The first release supports command rules with:

- `:name`
- `:inputs` using `:contents`, `:written`, `:created`, `:glob`, `:executables`, and `:always`
- `:outputs`
- `:action` as a structured argument vector containing strings and Trellis input, output, glob, and depfile markers
- `:stdin`, `:stdout`, `:depfiles`, `:artifacts`, and `:spawn-options`

Garden rejects Trellis function actions, private outputs, source outputs, and Flower phases.
Function identity and ambient in-process state cannot be persisted soundly by this small executor; virtual layers and phases are Flower host concepts.

Trellis marker maps currently use `:flower/*` keys as migration data.
Garden consumes them only through Trellis APIs and must not introduce another copy of that representation into its public contract.
If marker expansion is not yet public in Trellis, it must be extracted there before Garden is implemented.

== Paths and output ownership

All authored relative paths are resolved from the project root, except `:spawn-options :dir`, which selects a project-relative working directory for its action.
Absolute inputs may be permitted by an explicit future policy; version 1 rejects them.

Outputs must be relative, normalized paths beneath the project root.
They may not be the project root, the build definition, the Garden state directory, VCS metadata, or an ancestor of any declared input.
Garden rejects `..`, NUL bytes, empty path components where the platform gives them special meaning, and paths whose existing ancestor resolves through a symbolic link outside the project root.

Exactly one rule owns each output path.
Garden rejects duplicate outputs and overlapping ownership where one declared output is an ancestor of another.
An input matching another rule's output creates an action-graph edge from producer to consumer.

Commands write outputs into an action-specific scratch directory under `.garden/tmp/`, not directly to final paths.
Trellis output markers expand to those scratch paths.
After successful execution and artifact validation, Garden atomically replaces each final output where the platform permits; a multi-output action is committed from a complete scratch set, but the filesystem cannot make the entire set atomic as one transaction.

Garden records every materialized output in its manifest.
`garden clean` removes only currently declared outputs which the manifest records as Garden-owned, removes their rows, and clears scratch state.
It refuses to delete an output whose current filesystem kind conflicts with the recorded kind, and it never follows a symbolic link while cleaning.
Outputs from removed rules remain in place and their manifest rows are retained as ownership evidence until `garden clean --orphans` explicitly removes them.
Garden removes the manifest and state directory only when no owned rows remain.

== Dependency values

Garden supplies the filesystem, environment, and executable capabilities through which Trellis resolves each normalized dependency to a stable value:

/ `:contents`: SHA-256 of regular-file bytes, or a distinguished missing value.
/ `:written`: file kind, size, and nanosecond modification time where available, or a distinguished missing value.
/ `:created`: file kind and existence only.
/ `:glob`: the sorted project-relative match set plus the value appropriate to the glob's change kind.
/ `:executable`: resolved absolute path, file kind, and content digest.
/ `:always`: a value unique to the current invocation.

Directories are valid only where the corresponding input kind defines meaningful behavior.
Special files are rejected unless a later input kind specifies their semantics.

Garden passes its complete startup environment to each action, then applies the literal overrides in `:spawn-options :env`.
Each variable in that effective child environment participates in cache identity as separate `[:garden/env name]` host dependency evidence carrying a tagged value digest and a redacted diagnostic projection, so explanations can name the variable which changed without exposing its value.
An overridden startup value does not participate because the action cannot observe it.
Garden rejects authored `:inputs :env` as redundant because every effective variable is already tracked.
Files consulted through variables such as `HOME` are not implied file dependencies and must still be declared when they affect reusable output.

The executable named by argument zero is an implicit `:executable` dependency even when omitted from `:inputs`.
Executable lookup and child process execution use the Garden process's startup `PATH` unless the rule overrides it.

== Graph construction

Garden constructs a graph before executing any command:

1. Load and validate the build definition.
2. Normalize each wrapped rule with Trellis.
3. Validate names, paths, outputs, markers, and resource requests.
4. Ask Trellis to index each output and construct producer edges for exact file inputs and globs which can match declared outputs.
5. Supply recorded depfile dependencies from the previous successful execution to the same Trellis graph planner.
6. Expand requested groups into demanded rule nodes.
7. Reject cycles reported by Trellis and present the complete named chain.

Glob-to-output edges may conservatively order a consumer after a producer even when the output does not yet exist.
This is preferable to evaluating the glob before its possible producers run.

A depfile discovered during execution affects cache validation immediately and graph ordering on later invocations.
A depfile dependency on another generated output must also be declared statically in `:inputs`; otherwise Garden fails the action after parsing the depfile and explains that first-run ordering would be unsound.

Rules not reachable from the requested targets are validated but not executed and do not reserve resources.

== Persistent reuse

Garden stores disposable state beneath `.garden/`:

```text
.garden/
├── manifest.edn
└── tmp/
```

The manifest is versioned and written atomically after all selected actions have settled.
A missing, corrupt, or unsupported manifest produces a warning and a cold build; Garden never repairs it by guessing.

A described output-producing action is reusable only when all of the following match a prior successful row:

- Garden and manifest format versions
- the canonical normalized Trellis rule and any host dependency evidence
- every static and recorded dynamic dependency identifier and value
- the output path set, filesystem kind, and content digest

Rules with no outputs or `:inputs :always` always execute and produce no persisted reuse row.
Reuse is derived from the described operation and its evidence rather than selected by an authored cache policy;
an action which cannot describe its dependencies must use `:inputs :always`.

Failed, interrupted, or artifact-incomplete actions never update their successful cache row.
Successful independent actions may update in-memory rows even when another action fails, and Garden persists those rows after running actions have stopped; this avoids discarding valid work without treating the overall build as successful.

`.garden` is a cache, not durable project state.
Deleting it must cause extra work but must not change the bytes of a successful final build.

== Scheduling and resources

Garden passes demanded roots to Meristem for concurrent evaluation.
Meristem prevents duplicate execution when several consumers demand the same producer.

`--jobs N` defines a pool of integer job tokens and defaults to the machine's available processor count.
Each rule reserves `:garden/resources :jobs`, defaulting to one, before its command starts and releases them when the command exits.
A request must be a positive integer no greater than the invocation's pool; an oversized rule is rejected before execution.

Resource acquisition must be work-conserving without allowing small rules to starve an older large rule indefinitely.
Garden may implement this with a FIFO waiter queue and may leave worker threads idle while the oldest runnable request waits for enough tokens.

Garden stops launching new actions after the first failure by default, allows already-running actions to settle, and returns nonzero.
`--keep-going` continues actions which do not depend on failed nodes and reports all failures in deterministic rule-name order.
Dependents of a failed action are marked blocked and are not executed.

This integer budget deliberately does not model memory, I/O, named locks, services, or remote capacity.
Measurements from real projects should precede a richer resource language.

== Command-line interface

The version 1 interface is:

```text
garden build [--jobs N] [--keep-going] [--explain] [--verbose] [TARGET ...]
garden list [--json]
garden graph [--json] [TARGET ...]
garden explain RULE [--json]
garden clean [--orphans]
```

With no subcommand, Garden behaves as `garden build`.
With no target, `build` and `graph` use `:garden/default`.
Unknown targets fail before execution and suggest nearby names without silently selecting one.

`list` prints rules, groups, and defaults without evaluating dependency values or running commands.
`graph` prints the selected `trellis.engine/prepared-plan`, including recovered depfile edges, after loading and normalization; JSON output uses stable rule names and sorted arrays.

`explain RULE` compares the current rule and dependency state with its manifest row without executing the action.
It reports `reusable` or one or more miss reasons: no prior row, always-run input, rule changed, dependency set changed, dependency value changed, output missing, or output changed.
When several reasons apply, it reports all of them in this order and includes dependency identifiers while redacting environment values.

`build --explain` emits the same decision immediately before each action is reused or scheduled.

== Output and failure semantics

Human output is concise and line-oriented.
Each action produces one start or reuse line and one completion or failure line; captured command output is printed only on failure unless verbose output is requested.

Garden preserves each command's stdout and stderr separately.
On failure it reports the rule name, resolved argument vector, working directory, exit status or signal, elapsed time, stderr, and then stdout.
It does not print inherited secret environment values.

Interactive commands are not supported in version 1.
Standard input is closed unless supplied by a Trellis stdin declaration, and action output is captured rather than attached to a terminal.

The process exit status is zero only when every demanded rule was reused or completed successfully.
Action failure returns 1; command-line usage, definition, graph, and query errors return 2 so callers can distinguish invalid configuration from a failed build.

Temporary directories from an interrupted invocation are never treated as completed outputs.
Garden removes its exact invocation scratch directory on normal completion and leaves bounded, uniquely named remnants after an unclean termination; a later invocation may reap only remnants whose recorded owner process is absent and whose age exceeds a conservative threshold.

== Portability and distribution

Garden targets macOS and Linux first.
Path comparison follows each platform's filesystem behavior, but manifest paths use normalized forward-slash project-relative strings.
Rules which require a platform should be selected by ordinary Clojure logic in `garden.clj`; Garden does not add a condition language.

The initial implementation may run on the JVM and be distributed as an executable wrapper plus an uberjar.
The project build definition uses the Clojure version bundled with Garden and may require only Garden, Trellis, and the Clojure standard library.
Loading arbitrary Maven dependencies from `garden.clj` is outside version 1 because it would make graph loading depend on network and package-manager state.

Garden must start and query quickly enough that operators do not bypass it for routine checks.
A native image or Babashka-compatible build is an implementation choice only after behavior and measurements justify its cost.

== Evolution

The build-definition and manifest formats are independently versioned.
An unsupported build-definition version is a hard error; an unsupported cache-manifest version is a warned cold build.

Garden may later add watch mode, traced undeclared-input diagnostics, remote artifact storage, richer resources, outputless success receipts, or a non-Clojure serialized graph.
Each addition must preserve the explicit dependency and authority boundaries above rather than inferring durable truth from incidental process behavior.

== Acceptance criteria

- a project can define and run heterogeneous command rules without Flower
- Trellis performs rule and input normalization, graph planning, dependency evidence, and cache decisions; Garden does not fork those contracts
- independent demanded rules execute concurrently within the job-token budget
- generated-output inputs create producer ordering regardless of declaration order
- multiple consumers execute a shared producer once
- unchanged successful output-producing rules are reused across Garden processes
- file, glob, environment, executable, command, working-directory, and output changes invalidate reuse
- outputless and always-input rules execute on every demand
- failed or interrupted actions never publish incomplete artifacts or successful cache rows
- duplicate, overlapping, escaping, and cyclic outputs fail before command execution
- `list`, `graph`, and `explain` answer their questions without executing actions
- cleanup removes only manifest-owned outputs and Garden-owned state
- human and JSON explanations redact environment values
- the implementation imports no Flower namespace

== Non-goals

- package resolution or tool installation
- remote execution or remote caching
- automatic dependency inference
- syscall tracing or hermeticity enforcement
- arbitrary command sandboxing
- services or long-lived processes
- interactive terminal programs
- function actions or persistent Clojure computations
- Flower pages, phases, virtual source layers, or output policy
- compatibility with Make, Ninja, Bazel, or task-runner build files
- watch mode in the first release
- guaranteeing transactionality across several final output paths
