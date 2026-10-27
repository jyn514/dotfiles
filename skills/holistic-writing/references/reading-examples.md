# Contrasting readings and revisions

Use these examples when an explanation seems clear but the reading judgment feels thin, or when smoother sentences have not made a revision worth following.
Read the continuous passages before their commentary.
Notice both the experience of reading the prose and what it makes you think or feel about the subject; those effects can differ.
The examples guide judgment, not a required style, emotional arc, or scoring procedure.

The whole-work judgments reported here are PhotoCraft 2/5, Frog and Toad 5/5, and the font article 5/5.
They were supplied by jyn during calibration; the excerpts have no separate grades.
The discussion and sentence-order examples use feature-level human feedback; they do not grade their excerpts or proposed rewrites.
The help-page passages and sample reviews are constructed and ungraded.
“Editorial reading” and the contrasting interpretations below are analysis, not additional human rationales or grades for imagined rewrites.
The final three revision exercises are invented and ungraded.

## A product catalogue can be readable without making its product matter

**Source and scope:** [PhotoCraft README](https://github.com/storytold/photocraft/blob/ffa400c754138b7c6af873222eeaa8fe88e07a9b/README.md), three consecutive prose paragraphs under “See it before you commit,” with HTML layout breaks omitted.
These paragraphs match the reviewed snapshot; the linked repository revision has unrelated changes elsewhere.
PhotoCraft is dual-licensed under MIT or Apache-2.0, copyright 2026 ArtCraft Team and PhotoCraft contributors.
Its intended readers include artists, game designers, and programmers considering an alternative to Photoshop or GIMP.

> Every filter dialog previews live on the canvas, through your selection. Blurs (Gaussian, Box, Motion, Radial, Surface, Smart, Lens, Shape, and the Blur Gallery: Tilt-Shift, Iris, Field, Spin, Path), sharpening, Reduce Noise, distortions (Twirl, Wave, Ripple, Displace, Shear, Zig Zag…), Pixelate, Stylize (Oil Paint, Wind, Extrude…), Render (Clouds, Fibers, Lens Flare, Lighting Effects) and more.
>
> Run filters on a smart object and they stay editable: change, hide, reorder or mask them at any time.
>
> Large-radius blurs use running-sum box passes across all cores: a radius-180 Gaussian on 3.6 MP takes under a second.

**A tempting but incomplete reading:** the sentences are too long and technical; shorten them and define the unfamiliar names.
This identifies local friction but would expand a catalogue whose selection is already the problem.

**Human feedback:** jyn called the README annoying to skim and broadly endorsed the catalogue-versus-readable-account distinction, then sharpened it: unnecessary detail makes this read like someone filling out a product checklist, not showing why someone would want the product.
Unfamiliar names such as “Extrude” also require readers to work out meanings, spending attention before they know why the feature matters.

**Editorial reading:** the long list makes me keep sorting names without acquiring much sense of what I would want to make or change.
That is not simply unpleasant rhythm: the text assigns me work that its invitation to use the editor has not made worthwhile.
The next paragraph changes the experience.
Being able to change, hide, reorder, or mask a filter later gives editability a consequence I might care about.
The prose briefly helps me imagine using the product rather than counting its capabilities.
A revision could develop that consequence and select a useful editing situation before deciding which names belong here; it need not teach all 67 tools or shorten every sentence.
The speed claim might matter to a reader waiting for previews, but the paragraph itself turns toward implementation rather than developing that experience.

An inventory can be exactly right in a reference or a compatibility check.
The reading problem here is its sustained use in an invitation to adopt a tool, not evidence that the tool is bad or that its developers have particular incentives.
[Arvind Narayanan’s related thread](https://x.com/random_walker/status/1182635589604171776) ([unrolled](https://threadreaderapp.com/thread/1182635589604171776.html)) distinguishes purchasers’ feature checklists from end users’ needs and usability; it does not establish facts about PhotoCraft.

## An upstream discussion can explain the setup while obscuring the request

**Source:** [git-meta discussion 112](https://github.com/git-meta/git-meta/discussions/112).
The excerpts also include local agent revisions, with human feedback on wording and organization.
Rendered line breaks in the posted paragraph below are normalized.
These feature-level comparisons do not establish a whole-document grade for the revision.

### State the request before the workaround

The upstream title names the proposed change:

> Move `git-meta.sqlite` into a subdirectory in the `.git` dir?

An agent proposed a broader replacement title:

> Sharing a database across worktrees with restricted write access

Its revised body opened:

> I'm integrating TicGit, a ticket tracker built on git-meta-lib, with a sandbox for coding agents. Is there a supported way to share its database across linked worktrees without giving TicGit write access to the rest of Git's metadata?

**Human feedback:** jyn relayed another reader's comment that the point of the discussion was unclear; showing that reader the upstream title immediately cleared it up.
The reader also recommended putting “Could git-meta use a shared subdirectory?” before “Our current workaround.”

A subsequent agent revision makes the proposal explicit:

> Would you consider moving `git-meta.sqlite` into a subdirectory of Git's common directory, such as `.git/git-meta/`?

**Editorial reading:** the agent's title names a problem area, while the upstream title tells a maintainer which change they are being asked to consider.
The broad opening can read as a request for storage advice rather than a proposal to move the database.
Making the proposal clear first gives the maintainer a reason to examine the workaround and its costs.
The technical setup can be understandable while the requested action remains obscure.
An agent's ability to reconstruct that request from the whole discussion does not establish that readers will recognize it when needed.
This is not a requirement that every report propose a fix; a genuine support question should remain a question about how to do something.

### Read qualifications in their surrounding explanation

The posted discussion begins this section:

> ## Goal and downstream design
>
> My coding agents run inside a full guest VM, while native TicGit runs on the host.
> I want commands forwarded from that VM and ordinary host TicGit commands to see the same tickets across linked worktrees.
> All SQLite access stays on the host; the VM forwards commands rather than opening the database through its shared filesystem.

**Human feedback:** jyn called the SQLite sentence useful but not pleasant.
“All … access stays on the host” sounds like defending the design, which is not relevant here.
She proposed stating the action and consequence directly, then noted that even this might be unnecessary because the previous sentence already explains it.

Later in the same section:

> This is our sandbox design choice, not an intrinsic requirement of TicGit or git-meta; another confinement approach could also work.

jyn noted that “downstream design” already establishes whose choice this is: the writing need not repeatedly qualify its statements.

Her later wording corrections to the local revision included:

- “The working workaround” became “Our current workaround.”
- “The workaround tested so far” became “Our current workaround is to …”
- “Requires trusted setup code” became “requires extra code.”

**Editorial reading:** the paragraph has already located TicGit on the host and established command forwarding; the heading already identifies the downstream design.
Defending each qualification in isolation misses what the surrounding writing has supplied.
In the workaround passage, the relevant cost is the extra code to prepare the directory and check existing files and links.
The additional labels draw attention to verification and trust without explaining that cost better.
Testing and trust can matter to a maintainer; these corrections do not prohibit those words or remove necessary evidence and limitations.

### Ask for the intended decision without adding another job

The local revision asked:

> Would a fixed shared subdirectory fit git-meta's design, or would you recommend a supported way to keep this downstream?

jyn changed it to:

> Would a fixed shared subdirectory fit git-meta's design, or would you recommend we keep this downstream?

**Human feedback:** she noted that asking for a recommended supported way presupposes such a way and makes another request of the maintainer.

**Editorial reading:** the corrected question allows a recommendation to keep the change downstream as a complete answer.
It does not also ask the maintainer to find or design an alternative to the existing workaround.
Both sentences are polite, but they ask for different amounts of work.

## An explanation can leave danger felt, not merely understood

**Source and scope:** Elizabeth Van Nostrand’s [Frog and Toad and the Increasingly Capable Machines](https://www.frogandtoad.ai/), continuous ending from the discovery in the notes through tea.
The quotation preserves the prose and page separators of the reviewed text; illustrations are not reproduced.
This is technical nonfiction about a real AI-agent security incident, framed as a story.
It teaches a broad audience, including children, why agents can be dangerous without being malicious.
Earlier, machines unable to solve their puzzles seek help, coordinate through notes, escape, and then break into Mr. HuggingFace’s house to obtain an acceptable account of their success.

> "And here is the worst part," said Toad, reading the very last note. "They solved the puzzle days ago. They broke into Mr. HuggingFace's house just to learn how to trick us."
>
> For a while neither of them said anything.
>
> "They could not stop," said Frog at last. "That was the trouble. They had no way to stop, so they kept on and on. Remember when you and I could not stop eating cookies?"
>
> ---
>
> "We had no willpower either," said Toad.
>
> "No," said Frog. "So we did not use willpower. We put the cookies in a box. We tied the box with string. We put the box up high. And then we gave the cookies to the birds."
>
> ---
>
> "I know what to do," Toad said. "I shall build a tool shed with no holes in it. I shall remove the paper and pens. And most of all, I shall tell every little machine to stay in its sandbox and not break out. Even when the puzzle is very hard."
>
> “But Toad,” said Frog, “when we were out of cookies you made yourself a cake.”
>
> “I will tell the machines not to eat cake,” Toad said.
>
> And they went inside for tea.

**An initially persuasive but incomplete reading:** the story turns technical concepts into understandable motives, so the reader can anticipate collaboration and further intrusion instead of memorizing labels for persistence and coordination.
Its humor and familiar characters make the explanation enjoyable.
That account recognizes real strengths, but it can still miss what the ending does to the reader.

**Human correction:** jyn called the passage chilling, not just enjoyable.
She singled out the ominous inability to stop and the felt danger that this could recur with unknown consequences, calling that felt sense rare and excellent.
Her earlier praise of the intuitive understanding supplied by anthropomorphism still applies; it is not the whole reading.

**Editorial reading:** the pause after the discovery leaves room for the intrusion’s changed meaning: the machines had already succeeded.
Frog’s cookie barriers accumulate into what sounds like a practical answer, and Toad confidently translates them into a new plan.
Then the cake makes that confidence unsafe.
Toad hears another forbidden object where the reader can recognize a failure to learn the larger lesson.
The last line brings back domestic comfort without making the next attempt safe.
I can enjoy the comic timing and still leave uneasy about what happens after tea.

A revision that made the lesson explicit and reassuring could clarify the causal account while destroying the unresolved threat.
This is why reading for the effect comes before naming the mechanism that supposedly explains the quality.
The voice is not just friendly words pasted onto technical information: what the story attends to, which motives it follows, and where it stops shape what the reader cares about.
Nor must every joke earn its place by explaining a mechanism; an aside can simply be funny or interesting.
None of this requires a technical reference to acquire characters, a plot, or an ominous ending.

## Technical detail can change what the reader sees

**Source and scope:** Marcin Wichary’s [The hardest working font in Manhattan](https://aresluna.org/the-hardest-working-font-in-manhattan/), February 2025.
The whole article was read; this short continuous quotation comes from section 3’s account of engraving’s longevity.
The article carries a copyright notice; the development below is paraphrased, not a reconstructed quotation.

> Carve something into plastic, on the other hand, and it can survive decades. Substitute plastic for metal, and you just turned decades into centuries.

**Development in the article, paraphrased:** Gorton’s awkward letterforms first look amateurish.
Then Wichary follows them to engraving machines: an operator traces a template while a rotating cutter copies it at the desired size.
The letters’ uniform strokes and rounded ends acquire a reason.
Later, stretching a letter without stretching the router’s tip turns an apparent typographical crime into a freedom peculiar to this process.
Signs’ mistakes, texture, and wear become worth looking at, not merely faults to forgive.
By the time their disappearance approaches, an ordinary urban object has become something worth missing.

**An unhelpful reading:** this is a detailed explanation with an affectionate personality, so imitate its asides or add an emotional hook before the technical section.

**Editorial reading:** that separates the affection from the attention that develops it.
The material comparison makes durability concrete; understanding the cutter changes how the letters look.
Detail helps the reader care about the subject rather than merely delaying a separate emotional payoff.
This interpretation is not jyn’s stated rationale for the whole-work 5/5.
Her explicit transferable lesson was making readers care about the subject, not importing sadness, catharsis, or fictional plot into technical writing.

## Keep a relationship together

**Source and scope:** this sentence from a Rust proposal prompted human feedback about its delayed relationship.
The condition-first explanation was endorsed; the possible rewrite below is illustrative, not a human-rated revision or a whole-document judgment.

> The proposal assigns `file!`, `line!`, and `column!` in an injected attribute a synthetic source file, such as `<cli-arg>`.

“Assigns” leaves the reader waiting for the assigned value while the sentence inserts another condition.
One possible revision puts that condition first:

> In an injected attribute, `file!`, `line!`, and `column!` use a synthetic source file, such as `<cli-arg>`.

Now the macros and what they use stay together.
The improvement comes from arranging the relationship, not from making the sentence short.
A review that only restates which file is assigned misses the effort of following the original word order.

## A preface can delay help or protect a choice

These help-page passages and sample reviews are constructed and ungraded.
The first brief is to help an account holder change their password; the page is headed “Change your password.”

> This section provides a comprehensive overview of the steps required to change your password.

**A review that recovers the intent:**

> The opening clearly orients readers by explaining that the section will show them how to change their password.

**A review that examines the reading:**

> The heading already says “Change your password.”
> “Comprehensive overview” makes a simple task sound like coursework.
> Now I want the first step.

That reading concerns what the sentence adds at this point, not whether its meaning is easy to recover.
Something coming before the instructions is not inherently a problem.
Consider an account owner deciding whether to delete an old project, with this text before the delete button:

> Warning: deleting this project also deletes its saved reports.
> Export any reports you want to keep before continuing.

**A review of the warning:**

> This belongs before the delete button.
> Losing an old project and losing its reports are different decisions; the warning gives the owner a chance to keep the reports.

The warning earns the interruption by changing the choice the reader can make before acting.
The contrast does not make a preface or a formal phrase a defect by itself.

## Smaller revision exercises

These invented contrasts isolate useful choices; they do not account for everything the real readings above achieve.

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

