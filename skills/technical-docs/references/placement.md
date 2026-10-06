# Documentation placement

Use this reference before adding documentation or choosing where new content
belongs, including small additions during implementation. Placement alone does
not require the `technical-docs` authoring workflow. Restructuring existing pages
or navigation belongs to `reorganize-docs`.

1. Name the reader and the decision, action, or understanding the content serves.
   Omit content with no such purpose; do not document a detail merely because it
   changed during implementation.
2. Read the nearest documentation entrypoint and existing owner before choosing
   a destination. Prefer an existing task or subsystem page to a new page.
3. Match the content to its scope:
   - Root README: repository-wide orientation, common starting instructions, and
     routes to specialized tasks—not an inventory of subsystem internals.
   - Subsystem or task documentation: usage, prerequisites, observable contracts,
     hazards, recovery, and reader-relevant limitations.
   - Code comments: local implementation rationale and non-obvious constraints
     needed when modifying that code. Keep operator instructions and guarantees
     between independently maintained components in their documentation.
4. Link to the owner from relevant entrypoints rather than copying its content.
   Keep safety constraints needed at the point of action; do not make a reader
   follow a link to discover that a command costs money or can destroy data.

For example, document compaction replay cost and failure recovery in operator
instructions. Keep a saved checkpoint offset's encoding beside the code that
reads and writes it; document the resulting replay limitation for operators. An
internal capture timeout belongs in a README only if readers need it to diagnose
or operate the system.

For a small addition to an established section, apply this check and validate the
changed text and links. A new heading alone does not require the authoring skill.
Use [technical-docs](../SKILL.md) for a new standalone document, substantive
changes to reader structure or explanation, or an explicit documentation
usability/correctness review.
