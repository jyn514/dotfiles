---
name: typst
effort: low
model: claude-haiku-4-5-20251001
description: Write Typst (.typ) markup files. Use when creating or editing Typst documents — covers core syntax for markup, scripting, and common functions. Does not cover compilation or preview.
---

# Writing Typst files

Typst is a markup-based typesetting language. A `.typ` file mixes **markup mode** (the default, like Markdown) with **code mode** (entered via `#`).

## Markup mode

```typst
= Heading level 1
== Heading level 2

Normal paragraph text. Blank lines separate paragraphs.

*bold*  _italic_  `raw/code`  
Line break with trailing backslash \
Or two newlines for a new paragraph.

- bullet item
- another
  - nested (indent)

+ numbered item
+ next

/ Term: definition list entry

#link("https://example.com")[link text]
#footnote[a footnote]

A label <intro> and a reference @intro.

$x^2 + y^2$ inline math, and block math:
$ sum_(i=1)^n i = (n(n+1))/2 $
```

Escape special chars (`#`, `*`, `_`, `$`, `@`, `<`, `\`) with a backslash.

### Headings

Do not manually number heading sections.
If you need to refer back to an earlier heading, use labels `<label-name>` and references `@label-name`.

## Code mode

Start an expression with `#`; use `[ ]` for content blocks and `{ }` for code blocks.

```typst
#let name = "World"
Hello, #name!

#let add(a, b) = a + b
The sum is #add(2, 3).

#set text(size: 12pt, font: "New Computer Modern")
#set page(paper: "a4", margin: 2cm)
#set par(justify: true)

#show heading: set text(navy)        // styling rule
#show "TODO": strong                  // replace/transform

#if name == "World" [Hi everyone] else [Hi #name]

#for x in (1, 2, 3) [Item #x ]

#let data = (a: 1, b: 2)              // dictionary
#let items = (1, 2, 3)               // array
```

`#set` configures defaults for following content; `#show` transforms elements. Place them near the top of the file or scope them in a block.

## Raw text & code blocks

Inline `` `code` `` and fenced ``` ```lang ... ``` ``` blocks produce verbatim monospace text; the optional language tag enables syntax highlighting. `#raw(content, lang: "...", block: true)` is the programmatic form (useful with `read(...)`).

For `#raw(...)` options, styling, and `#image` / `#figure` / `#table` / `#grid` / `#align` / `#outline` / `#bibliography` / spacing helpers, see `reference.md`.

## API lookup with Tinymist

For unfamiliar or version-sensitive functions, prefer the installed `tinymist` language server over guessing signatures or relying only on `reference.md`. Start `tinymist lsp`, initialize the workspace over JSON-RPC, open the target file (or a minimal scratch `.typ` file), then use:

- `textDocument/hover` for documentation and resolved types
- `textDocument/signatureHelp` for parameters at a call site
- `textDocument/completion` for available functions and named arguments

Query the exact source position where the API is used. Keep one server process for related lookups, and shut it down cleanly; if Tinymist is unavailable, compile a minimal probe with the repository's Typst version.

## Units & values

- Lengths: `pt`, `mm`, `cm`, `in`, `em`, `%`, `fr` (fractional/flex).
- Colors: named (`red`, `navy`) or `rgb("#1a1a1a")`, `luma(200)`.
- Strings use `"double quotes"`; content uses `[brackets]`.

## Tips

- Comments: `// line` and `/* block */`.
- One statement per `#…`; wrap multi-line logic in `#{ … }`.
- Function args are positional then named: `func(pos, name: val)`.
- Trailing content block syntax `func(args)[body]` is sugar for passing the block as the last argument.
