# Choose and develop a use

The examples below are complete introductory accounts, not opening paragraphs to paste above an unchanged manual.
Their facts belong to invented projects.
They demonstrate selection and explanation, not interfaces you may invent for a real project.

## A library with a large reference

Suppose JobJar's supplied material establishes these facts:

- JobJar is a TypeScript background-job library backed by PostgreSQL.
- `openQueue(url)` connects to an existing PostgreSQL database and creates its job tables if needed.
- `queue.add(name, payload)` stores a job and returns its ID.
- `queue.work(name, handler)` waits for jobs of that name and calls the handler with `{ id, payload }`.
- Producers and workers can run in separate processes connected to the same database.
- Pending jobs remain in PostgreSQL when a worker stops.
- A failed handler is retried, so the same job can run more than once.
- The package is installed with `npm install jobjar`.
- Existing `docs/setup.md`, `docs/retries.md`, and `docs/api.md` explain database setup, retry behavior, and all operations.
- The source README also documents batch sizes, polling, connection pooling, scheduling, tracing, twelve callbacks, and contributor test commands.

An inventory can be accurate and still fail to introduce the library:

> JobJar provides durable job coordination with persistence, worker orchestration, retry semantics, configurable batching, polling policies, and lifecycle instrumentation.
>
> ## Configuration
>
> Configure the connection pool, polling interval, retry policy, concurrency, callback map, and tracing options.
>
> ## Complete API
>
> The queue supports the following operations...

Adding a good paragraph above that inventory leaves the reading problem in place.
Compare this complete replacement:

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

The revision keeps the behavior and warning needed for this use without reproducing every operation's contract.
It does not describe a batch size or tracing callback inaccurately; it leaves those subjects to the supplied reference.
The two examples develop one division of responsibility instead of showing every possible callback before the reader understands a job.
If those reference files did not exist, the writer could create useful supporting pages when authorized, link to inspected source definitions, keep selected additional explanation here, or omit a route rather than invent a page.
The absence of another manual does not by itself require reproducing the entire old README.

## Creating supporting owners when they help

Suppose Folderlist prints the paths of files in a directory.
Its supplied material establishes that `folderlist list PATH` scans recursively unless given `--top-only`.
It reads files without changing them and prints one relative path per line.
Version 2 renamed `folderlist scan PATH` to `folderlist list PATH`; there are no other migration steps.
An optional `--exclude NAME` omits files with that exact basename at any depth, and the option can be repeated.
The old README mixes those options and the version transition into its introduction.
The user authorizes rewriting the README and creating supporting documentation.

Use `reorganize-docs` for the extraction and navigation changes.
A small documentation set could contain the following three complete files.
The paths below belong to this fictional example, not to this skill's package.

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

The writer creates both linked files rather than leaving the README dependent on nonexistent pages.
The option reference serves lookup, while the migration page serves existing users updating scripts.
Neither page needs to repeat the introduction.
The README still explains what its command includes and that it does not change files.
Moving those facts out would make its selected action harder to judge.
If there were no specialized options or migration task, a single README could be enough.

Review the README's prose first without borrowing explanations from these supporting pages.
Then inspect the pages and routes separately when reviewing the documentation set.
Finding every old sentence somewhere in the set would not establish that any of the three pages reads well.

## A conceptual method with private vocabulary

Suppose Second Look supplies a Markdown guide, `guide.md`, for writing short first-person orientations to give a language model before a later task.
The user chooses a habit to encourage, asks the model to write from that habit, reviews the text, and places a selected passage in the later context.
The guide calls the habit an “attention rule” and the passage a “cue.”
It does not install the text, run the later task, or guarantee the later model follows it.
`notes.md` explains the method's terminology.

This source draft and its supposed example remain abstract:

> Second Look develops attention rules into self-continuing cues.
> Suppose a team wants a better attention rule.
> The model develops the rule into a cue, which the team selects for continuation.

“Suppose” does not make a situation concrete.
The rule and cue still have no particular content.
Compare this complete introduction:

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

The example does not report a successful experiment.
Its chosen habit and quoted passage make the method's intended operation understandable without claiming it works reliably.
It also does not provide a new interface: the supplied project is a writing guide, so an ordinary-language illustration is appropriate.
The private names arrive after their meanings, not as prerequisites for understanding the example.

## A small tool needs less

Suppose Certwatch scans certificate files and reports those expiring within 30 days.
It only reads files, and its existing `docs/scan-options.md` explains JSON output and other warning windows.
A complete introductory account can be this short:

> Certwatch shows you which certificate files need replacing soon.
> Point it at a directory to list certificates that expire within the next 30 days:
>
> ```sh
> certwatch scan ./certs
> ```
>
> Each result gives the file's path and expiry date, so you can find the certificate and plan its replacement.
> Certwatch does not replace certificates for you.
> For machine-readable output or a different warning window, see [scan options](docs/scan-options.md).

The command, result, and limit develop the same action.
The brevity follows from the use, not a word-count target.

## Published examples and their limits

The historical re-frame README assigns the programmer and framework their parts:

> To build an app, you hang pure functions on certain parts of this loop, and re-frame looks after the **conveyance of data**

Its later account develops that division through events, effects, queries, and views.
The programmer supplies transformations; the framework coordinates the data passing through them.
The long essay and analogies are not a required style for every README.

Source: `https://github.com/day8/re-frame/blob/a743ab66ff8b7aae85b08f175906d1f7d80ce378/README.md#it-is-a-loop`.
The Awesome README collection praises its writing: `https://github.com/matiassingers/awesome-readme/blob/67494300e0a6e3df6c6b50913b93207db90798b4/readme.md`.
Reader praise and dissent: `https://news.ycombinator.com/item?id=44482375` and `https://news.ycombinator.com/item?id=23956668`.
The comments do not establish the precise revision read, and the current root README is not the historical essay.

Ripgrep makes file-type filtering concrete with two actions on the same search:

> For example, `rg -tpy foo` limits your search to Python files and `rg -Tjs foo` excludes Javascript files from your search.

Its wider adoption argument connects defaults to work a grep user otherwise does manually and includes reasons not to choose it.
Source: `https://github.com/BurntSushi/ripgrep/blob/3de31f752729525d85a3d1575ac1978733b3f7e7/README.md#why-should-i-use-ripgrep`.
Reader response: `https://news.ycombinator.com/item?id=22098602`.
That experienced command-line user praises the README and says relevant defaults persuaded them to try the tool; the comment's separate praise of an article is not praise of the README.
Neither case establishes universal reader preference.
