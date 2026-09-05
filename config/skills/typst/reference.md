# Typst: detailed reference

Consult on demand when reaching for a specific function or feature. Core
markup/code syntax lives in `SKILL.md`.

## Raw text & code blocks (in depth)

Inline `` `code` `` and fenced blocks produce *raw* (verbatim, monospace) text. Fenced blocks take an optional language tag for syntax highlighting:

````typst
```rust
fn main() { println!("hi"); }
```
````

The `#raw(...)` function is the programmatic form, useful when the content is dynamic or read from a file:

```typst
#raw("let x = 1", lang: "rust")        // highlighted snippet
#raw("verbatim text")                  // no lang = plain monospace
#raw(read("example.rs"), lang: "rust", block: true)  // block: true forces a multi-line block
```

`block: false` (the default for a single line) renders inline; `block: true` renders as a standalone block. Style raw text with `#show raw: set text(...)` or configure tab width / theme via `#set raw(tab-size: 4, theme: "theme.tmTheme")`.

## Common functions

```typst
#image("photo.png", width: 80%)
#figure(image("plot.png"), caption: [A plot])
#table(columns: 2, [A], [B], [1], [2])
#grid(columns: (1fr, 1fr), [left], [right])
#align(center)[centered content]
#box / #block                         // inline / block containers
#v(1em)  #h(2cm)                       // vertical / horizontal space
#pagebreak()
#outline()                            // table of contents
#bibliography("refs.bib")
```
