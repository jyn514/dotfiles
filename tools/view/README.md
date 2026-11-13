# view

`view [PATH]` opens Metabrowser for a local file or directory.
With no path, it opens the current directory.

The command runs pinned `metabrowser==0.12.0` through `uvx` and loads the local view plugins from this directory.
The first run may populate uv's cache for Metabrowser and `docutils==0.23`.

The RST plugin renders `.rst` files with Docutils' HTML5 writer and keeps relative document and media links inside the same Metabrowser session.
Sphinx-only roles and directives stay ordinary Docutils diagnostics.
The renderer disables raw HTML and file-including directives so a viewed document cannot read or execute content outside Metabrowser's own trust boundary.

The Markdown plugin keeps Metabrowser's built-in KPress renderer and upgrades fenced `mermaid` blocks into diagrams with vendored Mermaid 11.12.1.
It only runs in trusted rendered Markdown views; `--untrusted` and `--no-active-content` keep Mermaid blocks as source code.
