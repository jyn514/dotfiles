# Perspectives on inquiry

Use these accounts when a live problem needs another approach.
The applications are interpretations for collaborative work, not claims that the sources prescribe this workflow.

## Let making reveal the question

In [Donald Schön's interview with John Bennett](https://hci.stanford.edu/publications/bds/9-schon.html), design moves have consequences that change the designer's understanding.
Sketches, materials, and people's use can reveal a narrowly framed problem; drawings and actions participate in the conversation.

Choose an artifact that can surprise you, and notice what it reveals beyond the original question.
Reflective practice means learning from these consequences, not abandoning a design after every surprise.

## Represent the relationships people need

[Bret Victor's *Magic Ink*](https://worrydream.com/MagicInk/) develops information displays around what someone wants to understand and decide.
Its train-schedule example makes relationships between journeys visible rather than leaving people to reconstruct them from travel times.

Try representing the needed relationships directly before adding another control or feature.
Victor addresses information software; judge extensions by the other activity's purpose.

## Find structure beneath resemblance

[Dedre Gentner's *Structure-Mapping*](https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf) distinguishes connected relationships from isolated matching attributes.
[Mary Gick and Keith Holyoak's *Analogical Problem Solving*](https://reasoninglab.psych.ucla.edu/wp-content/uploads/sites/273/2021/04/Gick-Holyoak1980Analogical-Problem-Solving.pdf) examines transferring an earlier example, including the difficulty of noticing a connection without a hint.

Revisit prior art through the current goal and obstacle.
Search for how things cooperate, remain distinct, or change state, not just their names.
Develop a correspondence until it suggests a consequence to investigate.
These accounts neither establish transferred conclusions nor exhaust analogy's expressive uses.

## Learn from a connection's limits

A Rust discussion [compared an owning reference with a restricted `Box` using a no-op allocator](https://rust-lang.zulipchat.com/#narrow/channel/219381-t-libs/topic/we.20have.20outpointers.20at.20home/near/617862098).
Shared value-ownership responsibilities became visible; questions about storage and subplaces led to [the distinction that `Box` also owns the entire backing allocation](https://rust-lang.zulipchat.com/#narrow/channel/219381-t-libs/topic/we.20have.20outpointers.20at.20home/near/618644767).

Separating value from storage ownership gave further design a more precise question.
When an analogy breaks, investigate whether it reveals an independent responsibility.
These are historical proposals, not a specification of current Rust semantics.

## Choose materials that invite discovery

[The Exploratorium Tinkering Studio](https://www.exploratorium.edu/tinkering/blog/2016/06/16/merge-science-art-and-technology-) describes adapting art-and-technology workshop materials for quicker experimentation and unexpected results.
The medium changes what participants can try and notice.

Choose how an idea can answer back: a sketch, physical arrangement, or playful simulation may reveal preferences an abstract questionnaire misses.
This workshop offers possibilities to explore elsewhere, not a universal prescription.
