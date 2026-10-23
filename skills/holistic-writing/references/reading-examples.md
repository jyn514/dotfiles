# Contrasting revisions

Read these examples when judging whether a revision develops an explanation rather than merely smoothing sentences.
They illustrate the whole-artifact judgment in `holistic-writing`, not a required style.

### Reach the distinction without an abstract detour

> SQLite’s in-process architecture, for example, represents a different paradigm from a daemon-based database design.

Compare:

> SQLite runs in-process instead of as a daemon.

The first sentence makes a plain engineering contrast sound grand.
The second names the difference directly.

### Explain a hypothesis without claiming confirmation

This invented bug report leaves the proposed connection unstated.

**Facts left for the reader to connect**

> Some requests execute twice.
> The client retries after a timeout.
> The server can still be processing the original request after the client times out.

**An explanation that overclaims**

> The client's retries cause the duplicate executions.

**An explanation that develops the hypothesis**

> My hypothesis is that the client retries while the server is still processing the original request.
> The retry would then start a second execution before the first has finished, explaining the duplicates.

The last version develops the proposed cause without treating it as a confirmed finding.
It adds reasoning, not evidence.

### Develop an explanation, not just smoother sentences

This invented library newsletter explains why a worn book is being repaired rather than replaced.

**Original**

> The library has a 1932 history of the town.
> Its spine is broken.
> The book has handwritten notes in its margins.
> New copies are still for sale.
> They do not include those notes.
> The library will repair its copy rather than replace it so visitors can keep reading the notes.
>
> One photograph’s caption names the wrong person.
> A reader crossed out the name and supplied another.
> Several shops mentioned in the book have closed.
> Readers added their closing dates.
> The repaired book will return to the local-history shelf.

**A superficially polished revision**

> The library’s 1932 history of the town, which has a broken spine and handwritten notes in its margins, will be repaired rather than replaced so visitors can continue reading the notes, although new copies that do not include them are still for sale.
>
> The notes include a correction to a photograph’s caption, where a reader crossed out the wrong name and supplied another, and the closing dates of several shops mentioned in the book that have since closed.
> After repair, the book will return to the local-history shelf.

**A revision that develops the explanation**

> New copies of the town’s 1932 history are still for sale, but they do not include the handwritten notes in the margins of the library’s copy.
> In one photograph’s caption, a reader crossed out the wrong name and supplied another.
> Readers also recorded when several shops mentioned in the book closed.
>
> To keep those notes available to visitors, the library will repair its copy’s broken spine rather than replace the book.
> It will then return to the local-history shelf.

The middle version preserves the facts but delays what makes them interesting: what the handwritten notes actually say.
Joining sentences has not developed the explanation.
The last version first shows the reader what a replacement would omit, then explains why the library will repair the book.

Use these contrasts to guide judgment, not to impose their style on every document.
Formality, fragments, repetition, and a restrained voice can all serve the reader.
Develop what repays attention without inventing facts; development need not include a worked example of every application.

