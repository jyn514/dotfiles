---
name: typst-diagrams
description: Create or revise Typst diagrams, especially Flower spec `.typ` files. Add or clarify a figure, convert prose/dataflow, use Fletcher, or validate rendered layout.
---

# Typst Diagrams

## Read First

- For prose and spec style, follow `contributing/doc-style.md`.
- For Typst syntax basics, consult the global `typst` skill when needed.
- For Flower specs, prefer the existing `bb lint --files doc/spec/flower/flower.typ` validation path over ad hoc Typst commands.

## Diagram Decision

Add a diagram only when it explains structure that prose or a list does not already show.

Good diagram candidates:

- converging inputs to one representation
- precedence or fallback order
- dataflow across ownership boundaries
- source/provenance maps between coordinate spaces
- parallel successful and degraded paths

Avoid diagrams that merely redraw an adjacent ordered list.
If a figure does not add relationships, remove it and keep the prose.

## Construction Rules

Prefer Fletcher for node-edge diagrams:

```typst
#import "@preview/fletcher:0.5.8" as fletcher: diagram, edge, node
#import fletcher.shapes: rect
```

Use open-coded `grid`/`table` only when the visual is actually tabular.

Keep diagrams compact:

- 4 to 8 nodes is usually enough
- put the main flow in one direction
- prefer a vertical main flow for large diagrams;
  portrait pages provide more room downward than across, and short side branches are easier to read than a wide horizontal chain
- use a side rail for metadata, precedence, fallback, or source maps
- label edges only when the edge meaning is not obvious
- prevent margin clipping by checking the extreme nodes first;
  `scale-to` scales the graph but does not guarantee that wide coordinates fit
- shorten arrows or coordinates, reshape wide flows vertically, and stack unimportant early steps before shrinking the diagram;
  shrinking often makes text unreadable
- avoid long diagonal back-edges through other nodes;
  they usually read as a crossing bug rather than a loop

When color distinguishes roles, separate categories by both hue and lightness.
Render the legend with the figure and confirm that adjacent categories remain distinguishable at the final page scale;
pale neighboring hues such as blue and lavender often collapse into one visual class.

For recursive or re-entrant flows, show the real callback boundary.
When an import, include, callback, or retry re-enters an existing owner, draw the edge back to that owner node instead of expanding a second copy of the same subgraph.
Add one short prose sentence after the figure if the recursion can repeat.
Do not hide recursion by turning it into a one-way pipeline to the final output.

For precedence diagrams, make order explicit in the figure itself.
Use numbered node labels or a visible "top to bottom" / "first present wins" label.
Do not rely only on vertical position.

For source-map or provenance diagrams, distinguish:

- the value/data path
- the provenance/map path
- fallback behavior when provenance is missing

## Validation

### Rendered validation

After editing a spec diagram:

1. Run the narrow Typst/spec lint command, usually:

   ```sh
   bb lint --files doc/spec/flower/flower.typ
   ```

2. Confirm that the expected `target/*-spec-lint.pdf` was refreshed.
3. Locate the rendered figure in the PDF with `pdftotext`.
4. Rasterize the page with `pdftoppm` into `$TMPDIR`.
5. Inspect the image with `view_image`.

Check for:

- clipped nodes or arrows
- extreme left and right nodes outside the page margin
- arrows crossing through labels or node boxes
- diagonal or fallback branches crossing unrelated nodes or paths
- edge labels colliding with arrows, nodes, or other edge labels
- arrows whose direction contradicts the intended dataflow order
- labels too small to read
- legend categories that are hard to distinguish at rendered size
- captions that repeat the figure without adding meaning
- diagrams split awkwardly from their explanatory prose
- figure numbering or ordering made confusing by removed/inserted figures

Do not assume a compiling Typst file means the diagram is readable.
