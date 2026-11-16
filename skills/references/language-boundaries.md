# Language boundaries

Read when parsing, scanning, encoding, serializing, emitting source, or building command arguments.

## Recognize the accepted language

### Define and recognize the accepted input

Apply [LANGSEC](https://langsec.org/) by defining the accepted input language at the parsing boundary.
Reuse the owning parser and pass its structured results to effectful code instead of recognizing the same language again.
For a deliberately limited recognizer, state its accepted fragment and test lookalikes outside it.
Recognize the complete input, including framing and namespace-bearing components, rather than accepting a prefix for another layer to reinterpret.
Reject malformed or unsupported input before starting the requested effect.
Where another component interprets the result, check that both sides assign it the same meaning.

### Check downstream interpretation and generated output

An argument vector prevents shell interpretation, not reinterpretation by the receiving command.
For example, a package identifier can become a local archive operand, and an already-resolved path can become a template for another expansion pass.
Use the owning serializer or encoder for generated output, keeping values as data rather than syntax.
If another phase parses that output, test syntax-like values through the complete writer-to-reader round trip.

## Language separation

Keep different languages in separate files rather than nesting them.
For example, a Python script must launch a separate Bash file, not embed a multiline Bash string.

## Reuse parser and writer contracts

Before implementing parsing or validation, check whether an existing consumer can produce the authoritative result.
Prefer inspecting that result over reproducing its rules.
Explain why reuse is insufficient before implementing a custom parser or validator.
A regex or hand scan can be the smallest correct recognizer for a defined fragment; it is not a substitute for the owner parser of a richer language.
Include relevant lookalikes in negative tests, such as comments, quoted strings, opaque code blocks, malformed partial input, or namespace-bearing paths.

Pass structured values to the output owner rather than assembling trusted-looking source in callers.
Name deliberate raw-source or trusted-markup inputs in the API or data shape.
For example, construct syntax-tree nodes or language-native forms and serialize them instead of concatenating delimiters around values.
Literal source remains appropriate when the bytes themselves are the subject, such as malformed-input or exact-whitespace tests.
Keep shell fixtures in separate files too; pass paths, arguments, environment values, or structured input rather than embedding script bodies.
