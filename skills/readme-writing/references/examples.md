# README choices in real and constructed examples

The real examples have pinned sources; the fictional projects demonstrate possible rewrites, not interfaces to invent for a real project.
Read each account before its commentary.

## A short orientation: jq

jyn proposed jq's README with the entire Installation section omitted as a short example.
Its opening describes jq as:

> a lightweight and flexible command-line JSON processor akin to `sed`,`awk`,`grep`, and friends for JSON data.

For readers familiar with those tools, the comparison establishes a role without teaching it from scratch.
The excerpt then supplies documentation and browser-playground routes, followed by support and licensing information.
The brief opening establishes the tool's role; those destinations let readers continue by reading or experimenting.

Source: `https://github.com/jqlang/jq/blob/5c001b18d7237cce1fdba63608732163f978dd23/README.md`.

## Several uses explained through comparison and example: uv

jyn judges uv a complicated tool that explains what it does well through comparison and example.
Its opening names familiar tools it can replace; later sections show how to carry out the corresponding tasks.

The Projects section compares its role with existing project managers, then follows initialization, adding a dependency, and running it:

```console
$ uv init example
$ cd example
$ uv add ruff
$ uv run ruff check
```

The source includes output between these commands and continues through locking and synchronization.
The sequence shows what project management means in use.
The Tools section separately invokes the familiar role of pipx, then distinguishes temporary execution from installation with examples.

Readers can choose a section through a familiar task, then see how uv carries it out.
The overview establishes scope; the individual examples develop understanding of particular uses.

Source: `https://github.com/astral-sh/uv/blob/419068541b7452193b72a240d345595595cca3e3/README.md`.

## A library with a large reference

Suppose JobJar is a TypeScript background-job library backed by PostgreSQL.
Its supplied API connects with `openQueue(url)`, stores jobs with `queue.add(name, payload)`, and runs handlers with `queue.work(name, handler)`.
Producers and workers share a database; pending jobs survive worker shutdown, and failed handlers are retried.
Existing setup, retry, and API pages document the details.
The source README also covers batching, polling, pooling, scheduling, tracing, twelve callbacks, and contributor commands.

For someone considering the library, choose an account that explains how submitting work relates to carrying it out.
These feature names identify relevant capabilities:

> JobJar provides durable job coordination with persistence, worker orchestration, retry semantics, configurable batching, polling policies, and lifecycle instrumentation.
>
> ## Configuration
>
> Configure the connection pool, polling interval, retry policy, concurrency, callback map, and tracing options.
>
> ## Complete API
>
> The queue supports the following operations...

Develop that relationship through a receipt job, keeping the database setup and retry warning beside the actions they affect:

> # JobJar
>
> Put work in a queue so a web request can return before a worker finishes the job.
> JobJar stores jobs in PostgreSQL; another process reads them and runs the handler you provide.
> If the worker stops, pending jobs remain in the database for it to pick up later.
>
> Install the TypeScript library:
>
> ```sh
> npm install jobjar
> ```
>
> Both processes need the same PostgreSQL connection URL in `DATABASE_URL`.
> See [database setup](docs/setup.md) if you need to create a database first.
> In the process receiving an order, add a receipt job:
>
> ```typescript
> import { openQueue } from 'jobjar';
>
> const queue = openQueue(process.env.DATABASE_URL!);
> const id = await queue.add('receipt', { orderId: 'order-123' });
> console.log(`Queued ${id}`);
> ```
>
> In a worker process, register the handler:
>
> ```typescript
> import { openQueue } from 'jobjar';
>
> const queue = openQueue(process.env.DATABASE_URL!);
> await queue.work('receipt', async (job) => {
>   console.log(`Receipt requested for ${job.payload.orderId}`);
> });
> ```
>
> This example prints the order ID; your application supplies the work to perform for that order.
> The producer stores the request, while the worker decides what receiving a `receipt` job does.
>
> A handler can run more than once after a failure.
> Before replacing the print with an action such as sending a receipt, arrange for repeated attempts not to repeat an unwanted side effect.
> [Retry behavior](docs/retries.md) explains what can be retried.
>
> For scheduling, batching, and the remaining operations, see the [API reference](docs/api.md).

The account develops why to defer work, where it waits, how to submit it, and who carries it out.
The retry warning arrives before the reader turns the harmless print into a real side effect.
Batch sizes and tracing callbacks stay in the reference.
Without those pages, use inspected source, create authorized supporting docs, or omit the route—not invent a destination.

## A collection needs a choice, not a representative tour

Suppose Fieldnotes contains three existing guides for people organizing day walks: `routes.md`, `weather.md`, and `repairs.md`.
They cover choosing a route for a group, interpreting a forecast when deciding whether to go, and repairing common equipment failures.
Each guide stands alone; the collection supplies neither current forecasts nor live route conditions.
The brief asks for an introduction that helps readers choose a guide.

The reader is choosing a guide for a situation, so develop the connection between situations and destinations.
The complete README can make that choice directly:

> # Fieldnotes
>
> Fieldnotes is a set of guides for organizing day walks.
> Each guide works on its own; start with the decision or problem you have:
>
> - [Choose a route](routes.md) when you need a walk that suits your group, rather than just a destination.
> - [Read the forecast](weather.md) when you are deciding whether the planned walk fits the expected conditions.
> - [Repair equipment](repairs.md) when something has failed and you need to work out what to do with it.
>
> The guides explain how to make those judgments.
> They do not supply current forecasts or live route conditions.

Each entry lets a reader recognize a situation and select a destination.
The introduction does its work by helping readers choose where to continue.

## A conceptual method with private vocabulary

Suppose Second Look's `guide.md` explains how to write first-person orientations for a model's later task.
It calls the chosen habit an “attention rule” and the resulting passage a “cue”; `notes.md` explains those terms.
It neither installs the text nor guarantees later behavior.

The reader needs to understand what choosing a habit and producing a passage involves.
This draft introduces the project's terms:

> Second Look develops attention rules into self-continuing cues.
> Suppose a team wants a better attention rule.
> The model develops the rule into a cue, which the team selects for continuation.

Choose a particular habit and show the resulting passage so readers can follow the operation before learning its names:

> # Second Look
>
> Second Look is a guide for writing a short orientation to give a model before another task.
> Instead of asking it to describe a desirable habit, you ask it to write from that habit, then select a passage for the later context.
>
> Suppose you want a model reviewing a proposal to look for a counterexample before endorsing the conclusion.
> Following `guide.md`, you could ask it to write a first-person orientation toward that habit.
> An illustrative passage might be:
>
> ```text
> I look for a case that would make the proposal fail.
> Before endorsing the conclusion, I ask which assumption that case tests.
> ```
>
> The passage names what to notice and what to do next.
> “I am a rigorous reviewer” would describe a quality without giving the next review that direction.
> The guide calls the chosen habit an attention rule and the resulting passage a cue.
>
> Read the generated passage before carrying it forward.
> If you select it, put it in the context the later task actually receives; text left in a separate drafting conversation cannot guide that task.
> Then inspect the later review for the action you wanted, rather than treating fluent first-person language as evidence that the habit took hold.
>
> This is a writing method, not an installer or a promise about model behavior.
> Start with [the guide](guide.md) to prepare one orientation; [the notes](notes.md) explain the terminology.

The habit and passage now have content before they receive private names.
The illustration explains the intended operation; assessing its reliability requires evidence from use.

## Creating supporting owners when they help

Suppose Folderlist's supplied material establishes recursive, read-only listing, exact-basename exclusions, and a version 2 command rename with no other migration steps.
The old introduction mixes all three tasks.
With permission to create supporting docs, use `reorganize-docs` for the extraction.
These three complete files belong to the fictional project, not this skill:

**`README.md`**

> # Folderlist
>
> Folderlist prints the files in a directory so you can inspect what is there without opening each subdirectory.
> Run it on the directory you want to inspect:
>
> ```sh
> folderlist list ./photos
> ```
>
> Each line is a file path relative to `./photos`, including files in its subdirectories.
> Folderlist only reads the directory; it does not move or delete files.
>
> For a list without subdirectory contents, use `folderlist list ./photos --top-only`.
> See [listing options](docs/listing-options.md) to leave out particular filenames.
> If you used version 1, [updating commands for version 2](docs/migration-v2.md) explains the renamed command.

**`docs/listing-options.md`**

> # Listing options
>
> `folderlist list PATH` prints one relative file path per line.
> It scans subdirectories unless you add `--top-only`.
>
> To omit a filename at every depth, use `--exclude NAME`.
> The name must match the complete basename, not a path or a pattern.
> Repeat the option to omit more than one name:
>
> ```sh
> folderlist list ./photos --exclude .DS_Store --exclude index.txt
> ```
>
> This lists files under `./photos` except those named `.DS_Store` or `index.txt`.
> It does not delete the omitted files.
>
> Return to [Folderlist](../README.md) for the basic listing command.

**`docs/migration-v2.md`**

> # Update commands for version 2
>
> Version 2 renames the `scan` command to `list`.
> Before updating a script that uses Folderlist, find its `folderlist scan` calls and change the command name:
>
> ```sh
> # Version 1
> folderlist scan ./photos
> # Version 2
> folderlist list ./photos
> ```
>
> Keep the directory argument unchanged.
> There are no other migration steps.
>
> See [listing options](listing-options.md) for the version 2 options, or return to [Folderlist](../README.md).

The README keeps recursion and read-only behavior beside its command.
The option page supports lookup; the migration page keeps old and new commands together.
Each serves a reader task.
Review each complete page for how well it helps its reader perform that task.

## Published examples and their limits

The historical re-frame README assigns the programmer and framework their parts:

> To build an app, you hang pure functions on certain parts of this loop, and re-frame looks after the **conveyance of data**

Its later account follows that division through events, effects, queries, and views.

Source: `https://github.com/day8/re-frame/blob/a743ab66ff8b7aae85b08f175906d1f7d80ce378/README.md#it-is-a-loop`.

Ripgrep makes file-type filtering concrete with two actions on the same search:

> For example, `rg -tpy foo` limits your search to Python files and `rg -Tjs foo` excludes Javascript files from your search.

Its wider adoption argument connects defaults to work a grep user otherwise does manually and includes reasons not to choose it.
Source: `https://github.com/BurntSushi/ripgrep/blob/3de31f752729525d85a3d1575ac1978733b3f7e7/README.md#why-should-i-use-ripgrep`.
