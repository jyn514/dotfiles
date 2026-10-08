# Perspectives on inquiry

Read these when a different approach to a live problem would help. They offer ways to notice and explore possibilities. The applications below are interpretations for collaborative work; the sources have their own purposes and limits.

## Let making reveal the question

In [Donald Schön's interview with John Bennett](https://hci.stanford.edu/publications/bds/9-schon.html), design develops through moves whose consequences change the designer's understanding. Sketches, materials, and people's use of an artifact can reveal that the problem itself was framed too narrowly. The conversation includes drawings and actions as well as words.

Apply this by choosing an artifact that can surprise you. Observe what the result makes newly noticeable, including effects the original question did not ask about. This perspective concerns reflective practice; it does not make every unexpected result a reason to abandon the design.

## Change what the representation makes visible

[Bret Victor's *Magic Ink*](https://worrydream.com/MagicInk/) develops information displays around what a person wants to understand and decide. Its train-schedule example turns travel times into visible relationships between journeys. The choice of representation changes which questions are easy to answer.

Apply this by examining the relationships a task requires people to reconstruct mentally. Try representing those relationships directly before assuming another control or feature is needed. Victor's argument concerns information software; extending the approach to other kinds of work requires judgment about their purposes.

## Find structure beneath resemblance

[Dedre Gentner's *Structure-Mapping*](https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf) distinguishes correspondences between connected relationships from matches between isolated attributes. [Mary Gick and Keith Holyoak's *Analogical Problem Solving*](https://reasoninglab.psych.ucla.edu/wp-content/uploads/sites/273/2021/04/Gick-Holyoak1980Analogical-Problem-Solving.pdf) studies how people retrieve and apply an earlier example to a new problem, including the difficulty of noticing a relevant connection without a hint.

Apply this by revisiting prior art through the current goal and obstacle. Search for how things cooperate, remain distinct, become visible, or change state, as well as for the names of the things involved. Make the correspondence specific enough to suggest a consequence worth investigating. These accounts of reasoning do not establish the truth of a transferred conclusion or exhaust the expressive uses of analogy.

## Learn from the limits of a connection

In a Rust design discussion, [an owning reference was compared with a suitably restricted `Box` using a no-op allocator](https://rust-lang.zulipchat.com/#narrow/channel/219381-t-libs/topic/we.20have.20outpointers.20at.20home/near/617862098). The comparison brought shared value-ownership responsibilities into view. Questions about storage and subplaces then led to [a more precise formulation: `Box` adds ownership of the entire backing allocation](https://rust-lang.zulipchat.com/#narrow/channel/219381-t-libs/topic/we.20have.20outpointers.20at.20home/near/618644767).

The useful discovery was a decomposition that could guide further design. Separating value ownership from storage ownership made both the common structure and the additional capability easier to discuss. These are historical proposals, not a specification of current Rust semantics. When an analogy fails at a boundary, investigate whether that failure reveals an independent responsibility or a better relationship between the concepts.

## Choose a medium that invites discovery

[The Exploratorium Tinkering Studio's account of combining art and technology](https://www.exploratorium.edu/tinkering/blog/2016/06/16/merge-science-art-and-technology-) describes adapting workshop materials to enable quicker experimentation and unexpected results. The medium influenced what participants could try and notice.

Apply this by considering how quickly an idea can answer back and what kinds of surprise a medium allows. An imperfect sketch, physical arrangement, or playful simulation may reveal preferences that an abstract questionnaire would miss. This is an account of a particular workshop, with useful possibilities to explore in other settings.
