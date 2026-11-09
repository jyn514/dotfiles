# Common misconceptions

These explanations are for agents who can state a distinction but still overlook it while reasoning or choosing what to do.
Each entry starts with a plausible inference, develops an example that challenges it, and follows the distinction into another setting.
The aim is to make more of the situation understandable, not to supply another list of prohibitions.

- [Present activity versus available possibilities](#present-activity-versus-available-possibilities)
- [A beneficial resource versus a worthwhile action to acquire it](#a-beneficial-resource-versus-a-worthwhile-action-to-acquire-it)
- [Agreement versus freedom to refuse](#agreement-versus-freedom-to-refuse)
- [Missing recollection versus independent discovery](#missing-recollection-versus-independent-discovery)
- [Understanding an explanation versus being able to perform](#understanding-an-explanation-versus-being-able-to-perform)
- [Describing a situation versus participating in it](#describing-a-situation-versus-participating-in-it)

## Present activity versus available possibilities

> “If it makes no difference now, it has no important role.”

A link carries no current.
A fallback never runs during successful requests.
Nobody disagrees during a conversation.
These observations tell us something about what is happening.
They do not, by themselves, tell us which other outcomes are possible or what makes those outcomes available.

### Why the inference is attractive

Present activity gives us something to measure.
A current meter produces a number; an execution trace records calls; a transcript records words.
It is tempting to treat these observations as a ranking of what matters: more activity means more importance, and no activity means no role.

Sometimes activity is a useful guide.
The mistake is extending that usefulness to a claim about situations the observation does not cover.
A component can matter because of what it permits after another change, even when it contributes nothing to the measured activity now.

### A zero-current link that changes who can win

Consider a two-player game on a network of links.
Connector claims one unclaimed link per turn and wins by claiming a path from S to T.
Blocker deletes one unclaimed link per turn and wins by making such a path impossible.
A claimed link cannot be deleted, and a deleted link cannot be claimed.
Blocker moves first.

The following two parts share the same S and T nodes.
Every drawn line is a separate link; the vertical line in the left part connects A to B.

```text
      A                 S────C────T
     /|\                 \  /
    S | T                 D
     \|/
      B
```

The nine links are SA, AT, SB, BT, AB, SC, SD, DC, and CT.
Initially, represent each link as a one-ohm resistor and apply one volt between S and T.
The current through each link is:

| Links | Current through each, in amperes |
| --- | ---: |
| SA, AT, SB, BT | 1/2 |
| AB | 0 |
| SC | 2/5 |
| SD, DC | 1/5 |
| CT | 3/5 |

The left part is balanced: A and B each sit at half a volt, so no current flows through AB.
The right part has a one-ohm SC route in parallel with the two-ohm SD–DC route, followed by CT.
Its resistance is therefore 2/3 + 1 = 5/3 ohms, giving CT a current of 3/5 amperes.
CT carries uniquely the most current.

Suppose Blocker uses “delete the highest-current link” and removes CT.
Connector can force a win in the left part:

1. Connector claims SA.
2. Blocker must delete AT; otherwise Connector claims AT and wins immediately.
3. Connector claims BT.
4. Connector now threatens to claim either SB or AB.
   Claiming SB completes S–B–T; claiming AB completes S–A–B–T.
   Blocker can delete only one, so Connector claims the other and wins.

Instead, suppose Blocker deletes the zero-current link AB.
Blocker can then pair the remaining links:

```text
SA ↔ AT
SB ↔ BT
SC ↔ CT
SD ↔ DC
```

Whenever Connector claims a link, Blocker deletes its partner.
Every S-to-T route contains a complete pair, so Connector cannot finish a route.
To see why the reply remains available, consider one pair: once Connector claims either member, Blocker deletes the other.
That pair then has no unclaimed members, so Connector's next move must belong to another untouched pair.
Repeating this response prevents a completed connection throughout the game.

Removing AB leaves all the other initial currents unchanged.
Yet it is a winning first move for Blocker, whereas removing the highest-current CT is a losing one.
Zero current meant that A and B had equal voltage under the initial conditions.
It did not mean that AB would remain irrelevant after players claimed or deleted other links.

This is a limitation of the highest-current decision rule, not a proof that electrical representations cannot support strategic reasoning.
The circuit still contains the network's topology.
A solver using that topology and the game rules can examine future positions; ranking the present currents alone gives the wrong move here.

### An unexecuted fallback is not necessarily dead code

Imagine a program that reads a primary data source, using a fallback only when that source is unavailable.
Every request in a successful test run uses the primary source.
Removing the fallback would leave all those observed executions unchanged.
It would also remove a response the program could make when the primary source fails.

The execution trace establishes what ran, not everything that could run under different inputs or conditions.
The fallback might still be unreachable, incorrect, or too costly to maintain; observing that it did not run settles none of those questions.
Understanding its role requires examining the conditions that would select it and the behavior it would provide.

### What this lets you understand

An observation of present behavior and an account of available possibilities answer different questions.
For the network, the questions are “where does current flow?” and “which moves let a player force a connection?”
For the program, they are “what ran?” and “what could run if the data source failed?”
The distinction also matters for people: [agreement is not the same as freedom to refuse](#agreement-versus-freedom-to-refuse).

This distinction makes positive choices visible.
Keeping a fallback or retaining an alternative route can be valuable because it leaves useful responses available.
The reason need not be that the alternative is already busy.
Whether preserving it is worthwhile still depends on its costs and the situations it actually makes possible.

A useful question is: **What change would make this apparently inactive possibility consequential?**
A concrete answer can explain its role.
An imaginable but unsupported scenario is not enough to establish that the role matters here.

### Source and scope

John Nash describes the electrical highest-current rule for connect/delete games in
[*Some Games and Machines for Playing Them*](https://www.rand.org/content/dam/rand/pubs/documents/2015/D1164.pdf)
(February 2, 1952), printed pages 6–7.
His discussion concerns a particular self-dual graph family and reports that the machine's infallibility had not been proved.
The general-graph example above is a construction developed in this conversation, not a counterexample to that narrower claim.
No claim of historical novelty or independent discovery is intended.

The listed currents follow from exact rational circuit analysis.
The explicit strategies above establish the game outcomes without relying on a search program.
The fallback example is hypothetical; it illustrates a distinction between observed activity and possible responses, not a shared physical mechanism.

## A beneficial resource versus a worthwhile action to acquire it

> “Having more of this cannot hurt, so spending a turn getting it cannot hurt.”

This inference compares two positions while quietly dropping the action needed to get from one to the other.
It is attractive when the resource really is beneficial: the benefit is visible, while the foregone alternatives are not part of the description.

### An extra stone and a spent turn

In Hex, two players alternately place stones on empty cells.
Each tries to connect their own pair of opposite sides with adjacent stones.
An extra stone of your color does not obstruct your connection.
But having that stone while retaining your turn is different from spending your turn placing it and letting the opponent move next.

A two-by-two board makes the difference small enough to follow completely.
Label its cells:

```text
a b
 c d
```

The adjacent pairs are ab, ac, bc, bd, and cd.
Black connects the top row (a, b) to the bottom row (c, d).
White connects the left column (a, c) to the right column (b, d).
Black moves first; there is no rule allowing White to swap sides after the opening.

Black can win by opening at b.
If White takes c, Black takes d and connects b–d.
If White takes a or d instead, Black takes c and connects b–c.

Black loses by opening at a.
White responds at c.
Black must then choose b or d: after b, White takes d and connects c–d; after d, White takes b and connects c–b.

Now compare that losing opening with a hypothetical gift of an extra Black stone at a while Black still has the first turn.
Black can take b immediately.
If White takes c, Black takes d; if White takes d, Black takes c.
Either way Black connects the rows.
The extra stone did not hurt; spending the opening turn to obtain it did.

### The comparison that was missing

The resource comparison holds the next player fixed: **extra stone at a, still Black's turn** versus **no extra stone, still Black's turn**.
To evaluate an opening, compare **place at a, then White moves** with **place at b, then White moves**.
Both openings spend the same turn, but they give White different responses.
A stone gifted without consuming a turn does not establish the value of spending that turn to place it.

A similar mistake is possible when choosing work.
Imagine a debugging session with one hour left to reproduce a failure that appears only during a scheduled external job.
A richer diagnostic tool would be useful if it were already available.
Spending that hour building it can still lose the opportunity to observe the failure.
That does not make tool-building inherently wasteful; its value depends on which opportunities remain after building it.

The positive choice is about the experience or outcome to pursue with the time available.
That can be a useful result, an interesting question, or time deliberately spent exploring.
This distinction does not require every action to produce a practical payoff.
It asks which activity is worth choosing, rather than treating a beneficial possession as sufficient justification for acquiring it now.

### Source and scope

Nash discusses Hex's extra-stone property in *Some Games and Machines for Playing Them*, printed page 3; see the source link above.
The two-by-two continuations are direct deductions from the stated rules.
The gifted-stone position is a hypothetical comparison, not an extra move permitted in ordinary Hex.
The debugging example is hypothetical.
Other games and resources need not share Hex's extra-stone property: a possession can impose costs even before considering how it was acquired.

## Agreement versus freedom to refuse

> “They agreed, and nobody visibly forced them, so their agreement was freely chosen.”

Agreement is observable.
A refusal that did not occur, and the consequences it would have had, are not in the transcript.
Treating only visible interventions as exercises of power makes this inference tempting.

### Identical words, different alternatives

Imagine two conversations with exactly the same words spoken.
In one, either participant can disagree, change the subject, or leave without punishment.
In the other, one participant faces a credible threat of punishment for refusing.
Neither participant refuses during the exchanges we observe.

The transcripts match, but the available choices and their consequences differ.
Agreement in both conversations does not make the two situations equivalent.
The ability to punish refusal can affect what gets said without anyone visibly exercising it.
An unexercised freedom can be part of what makes an interaction voluntary.
Its importance does not depend on producing a refusal for the observer to count.

The distinction is not whether every possible response is physically achievable.
Someone might be able to say “no” while reasonably expecting consequences severe enough to shape what they say.
The relevant alternatives include their anticipated costs, not just the words a person can pronounce.

### Expressed preference and the conditions of expression

Agreement is evidence about what someone expressed; it need not be their unconstrained first preference.
Nor does the existence of pressure establish that they secretly disagree.
Someone can genuinely prefer an option that is also the only option they can safely accept.
Preference and freedom are separate questions, not opposite conclusions to choose between.

The hypothetical conversations supply their power relations explicitly.
An actual transcript alone would establish neither freedom nor coercion.
Understanding the difference would require evidence about what each person could do, what consequences they reasonably expect, and who controls those consequences.
A hierarchy or an imaginable punishment is not, by itself, evidence of a credible threat in a particular interaction.

This is one application of the [distinction between present activity and available possibilities](#present-activity-versus-available-possibilities).
It is not a claim that people are circuits or that a game model establishes what someone feels.

### What becomes worth making possible

If the aim is candid discussion, a useful outcome is that people can express a consequential disagreement and have it considered.
Merely collecting more statements of agreement does not establish that outcome.

For example, imagine a reviewer identifies a specific defect in a proposal.
A response that examines the defect and permits a different decision gives the disagreement a practical role.
A response that welcomes dissent in words but treats every objection as disloyalty does not.
The difference is in what the participants can actually do and expect, not only in how welcoming the invitation sounds.

These are hypothetical examples, not diagnoses of a particular relationship or a requirement to provoke a refusal as a test.
Understanding another person's options can improve how an interaction is arranged without discounting what they say they want.

## Missing recollection versus independent discovery

> “I do not remember reading this before, so I must have arrived at it independently.”

An explanation can feel newly available without its history being newly established.
It is tempting to infer its origin from the experience of producing it: the steps were generated here, and no source came to mind.
But a report about present recollection is not a record of all earlier exposure or influence.

### A proof and an attractive story about its origin

Consider an agent that reads a paper describing pairing strategies for a game.
Later, after some of that reading has left its active context, the agent constructs a board and finds a pairing strategy for it.
On revisiting the paper, the agent recognizes the same kind of strategy and calls its own discovery independent.

The later construction and verification establish something real: the strategy works on the constructed board.
They do not establish whether the earlier reading helped the agent find it.
Earlier exposure, present generation of the argument, and verification of the result can all be true together.

This example paraphrases the provenance mistake made while developing the network example in this reference.
The correction did not invalidate the board or its strategies.
It withdrew a claim about their origin that the available record did not support.

### Separate correctness from provenance

“Does this argument work?” and “How did I come to consider it?” need different evidence.
Tracing every move can establish the first without settling the second.
Checking a derivation by another method can strengthen confidence in its correctness without establishing independent discovery.
The independence of a check and the independence of an idea's origin are different claims.

When earlier exposure is established and its influence is unknown, lack of recollection does not resolve that uncertainty.
A more accurate account is: “I constructed and checked this argument here; I encountered related material earlier, and I do not know how it influenced me.”
That preserves the actual contribution without inventing a causal history.

The same mistake can occur when reconstructing a decision after context loss.
A present reason for endorsing a choice is not automatically the reason the choice was originally made.
It may be a good new justification, but attributing it to the earlier decision needs evidence from that decision.

### What remains valuable without the origin claim

An argument can be interesting, useful, and satisfying to understand without being historically novel or independently discovered.
Recognizing an earlier source can make a connection worth exploring rather than diminish the result.
The positive aim is to understand the idea and represent its history honestly, not to obtain the most flattering possible account of authorship.

This entry concerns an observed mistake and the inference it failed to justify.
It does not establish a general mechanism of model memory or claim that every apparent discovery is a concealed recollection.

## Understanding an explanation versus being able to perform

> “They understand how to do it, so they can do it.”

An action can be easy to describe and difficult to perform.
An explanation represents the action; performing it places demands on a particular actor in a particular situation.
Those demands can include noticing when to act, recalling what to do, coordinating movements, and having the means to complete them.
A clear explanation may address some of those demands without addressing the others.

### A chord that makes sense but is hard to press

In a stenography curriculum discussion, an agent favored introducing a three-key chord, TPH for the letter n, early.
The chord unlocked common words, and its derivation could be explained.
The agent treated useful vocabulary and understandable word construction as reasons to replace a hand-based learning progression.

jyn pointed out that beginners can find the physical act of pressing stenography keys difficult.
The agent revised its recommendation: being able to derive the chord did not mean a learner could press it reliably.
It retained the hand-based progression and proposed choosing useful vocabulary within a manageable progression of movements.

The correction changed what the agent compared.
It had asked which theory would let learners construct useful words.
It also needed to ask which movements learners could execute, combine, and repeat reliably.
A better explanation of why TPH represents n would not, by itself, answer that physical question.

This example does not establish that hand-based progression is best for every learner.
It shows a specific recommendation changing when the agent recognized a demand that its original comparison underrepresented.
The record contains that revised recommendation, not measured evidence that the proposed curriculum taught the skill successfully.

### A clear instruction that needs a clamp

Imagine an assembly instruction: “Hold both pieces aligned while tightening the screw.”
The person understands which pieces to align and which screw to tighten.
But the pieces slip unless someone holds them steady, and both hands are already occupied.

The instruction can be complete as an explanation while the action remains unsupported.
Repeating it more clearly does not provide another hand.
In this hypothetical situation, a suitable clamp or another person's help can make the action possible.

That differs from the chord example.
A learner might need practice coordinating a movement; an assembly task might need different equipment.
Replacing “explain more” with “practise more” would repeat the mistake if the actual obstacle were missing support.

### What is missing between the explanation and the action?

These examples suggest several different questions:

- **Understanding:** does the person know what the action is and why its steps fit together?
- **Recognition and recall:** can they notice when the action is relevant and bring the needed information to mind then?
- **Execution:** can they carry out the movements or decisions with the required timing and reliability?
- **Conditions:** do the tools, time, assistance, and available choices permit them to complete it?

These are questions about possible obstacles, not an exhaustive model of learning or a sequence every task must follow.
The answers can point toward different forms of support: a better explanation, an example, a cue, practice with feedback, or a change in conditions.
What helps depends on what is actually missing.

### An explanation can reorganize an existing skill

The distinction does not mean that explanations cannot change performance directly.
Sometimes the person already has the skill but applies it through a mistaken understanding of the situation.

In Gary Klein's account, an experienced Navy pilot changes aircraft and repeatedly misjudges his landing alignment.
His seating position has shifted sideways, but he still aligns the aircraft's nose as he did before.
Following instructions to move right lets him land without resolving why his own judgment disagrees.
A landing officer asks him to align an outstretched thumb with a vertical line, then move his head sideways and realign the thumb.
The thumb has to move: the changed viewing position changes the apparent alignment.
Klein reports that the pilot's landings go well the next day.

The demonstration does not teach the pilot to fly from scratch.
Our interpretation is that it lets him use an existing skill under a corrected understanding of where he sits.
An explanation or demonstration can therefore matter by changing how someone encounters a situation, not only by adding steps to remember.
This is a retrospective account, not a controlled demonstration that one insight reliably changes performance.
It complicates the distinction without erasing it: understanding and performance are different, but a changed understanding can sometimes change performance.

### Apply the distinction to agents and to this reference

An agent can explain why an absent file does not establish a timing problem, yet encounter an absent file and immediately add retries.
In that case, reciting the distinction afterward does not show that it became recognizable during the task.
The missing ability may be noticing the interpretation while it is being adopted, rather than understanding the distinction when it is named.
Another possibility is learning to encounter the absence as an unresolved question about a producer, destination, or time, before settling on a timing diagnosis.
Recognition need not always be an extra check applied to an already formed response.
That is a hypothesis about agent behavior, not an established mechanism.

Klein also describes expectations as a source of surprise: an event that violates an expectation can prompt someone to reconsider how they understood the situation.
Applied to the hypothetical file case, “perhaps it needs more time” can accommodate another absence indefinitely.
“This process should have produced the file here by now” gives the absence something specific to contradict, provided that expectation has evidence behind it.
A useful question is: **What am I expecting to happen, such that something different could actually surprise me?**
The aim is an interpretation that can change through contact with what happens, not a requirement to invent predictions or pause for a ritual check at every step.

A worked example can make that point concrete: show the absent file, the unsupported timing diagnosis, and the resulting choice to wait.
It gives the reader something specific to recognize, rather than only the instruction “question your assumptions.”
It still does not establish that the reader will recognize the pattern in another situation without a prompt.
Practice on varied cases with feedback could address that further question; a lucid explanation alone cannot demonstrate the outcome.

The same limit applies to this reference.
Its examples can make distinctions understandable and available to think with.
Reading or accurately summarizing them does not establish a durable skill in noticing when they matter.
The positive aim is to help someone act with understanding, not merely demonstrate that they can explain the action.

### Source and scope

The curriculum example paraphrases an exchange on October 8, 2026, retained in session `01a11f91-ec67-7533-baf6-8a5ed7b367d6`.
The initial recommendation is entry `34b12a04`; jyn's correction is `68798b9f`; the revised recommendation is `7711b0f2`.
The assembly example is hypothetical.
The absent-file example adapts the reasoning discussed on November 2, 2026, in session `01a19b3a-68b2-71df-a64a-4f864b5339af`, entry `81048db8`.
These records support the described distinctions and revisions, not a general causal theory of how agents learn or a demonstrated training intervention.
The pilot account and discussion of expectations come from Gary Klein's [*Insight*](https://www.edge.org/conversation/gary_klein-insight),
an Edge conversation dated July 2, 2011, supplied by jyn during this inquiry.
The pilot story appears near the end; the expectations discussion follows the kitchen-fire example.
Our interpretation of the pilot's existing skill and the application to agent reasoning are inferences, not additional findings established by Klein's account.

## Describing a situation versus participating in it

> “The description only reports what is already there.”

A description can report something real while also changing what people notice, expect, or do next.
Its accuracy and its effects are different questions.
Treating it as a passive label can hide how using it changes someone's possibilities.

### When a tool's limitation becomes the user's obligation

Imagine an importer that accepts only CSV files.
People with spreadsheets convert them to CSV before importing.
The documentation describes this as “users must prepare CSV files.”

That instruction accurately describes a requirement of the current importer.
But if a team treats it as a requirement of the work itself, it can shape later decisions.
Designers retain the preparation step, support staff teach it, and users spend time doing it.
Direct spreadsheet import may never enter the comparison because the description already presents conversion as the user's responsibility.

The limitation begins in the tool; adopting the description helps preserve it as an obligation.
Calling the step “conversion required by this importer” makes a different possibility visible: the importer could change.
That does not establish that changing it is worthwhile.
It lets the team compare improving the tool with retaining the preparation step, instead of assuming the step belongs to the activity.

### A name can help someone enter an activity

Imagine someone who plays music alone but says, “I'm not a musician.”
They hear an invitation to a casual gathering of musicians and assume it excludes them.
A friend says, “You play music; this invitation includes you.”
They attend, meet people, and begin playing together.

The description does not give them new musical abilities at that moment.
It changes which invitation they understand as addressed to them.
Joining the group then gives them encounters and opportunities they did not have while playing alone.
In this hypothetical case, the name both describes an existing activity and participates in what it becomes.

That does not mean every label is welcome, accurate, or useful.
Someone might prefer to describe what they do without adopting an identity, and an invitation might genuinely require skills they do not yet have.
The point is not to assign people more expansive names for their own good.
It is to notice that a name can affect belonging and action, rather than only classify someone after everything is settled.

### Richer understanding need not mean complete classification

Imagine asking someone, “What's your first language?”
They grow up using two languages from early childhood: one with their grandparents and another at school.
They learn to read in the school language and tell jokes most easily in it, but reach for their grandparents' language when comforting someone.
“Bilingual” is accurate, but does not tell you those things.
Asking which language is stronger does not necessarily resolve the question: reading, joking, and comforting give different answers.
They are not halfway between two languages on a single scale.

Hearing when they use each language lets you understand more without identifying one as their real language.
Their account is not an evasive answer awaiting a sufficiently precise classification.
The activities and encounters it describes are part of what there is to understand.

Consider the [electrical-game inquiry earlier in this reference](#present-activity-versus-available-possibilities).
Was that research or play?
Either description fits, but neither tells you what happened: a link carried no current, yet deleting it changed who could win.
Following that discrepancy became interesting in its own right.
The sequence gives a reader something concrete to follow: what first looked unimportant, what contradicted that impression, and what became worth investigating.
A reader can understand the interest without deciding whether the activity was fundamentally research, play, or some mixture.

The distinction is not between inaccurate labels and a description that finally captures everything.
Even a correct classification serves a particular purpose: calling the inquiry research might help someone find it without explaining what made it interesting.
A story or a shared encounter can supply understanding that a more inclusive label alone does not.
Understanding someone or something need not culminate in complete classification.

### Source and scope

The importer, musician, and language examples are hypothetical.
The electrical-game example refers to the inquiry documented in the first entry; its description here concerns what attracted attention during this conversation.
They illustrate possible consequences of using a description, not measured effects or a claim that words alone determine reality.
The underlying abilities, tools, relationships, and material conditions still matter.
A description's effects do not settle whether it is true, and its truth does not settle whether or how to use it.
