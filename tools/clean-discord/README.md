# Clean a copied Discord transcript

[`clean-discord`](../../bin/clean-discord) converts Discord copy-pasted text to `[HH:MM] <name> message` lines; requires Babashka (`bb`).

Read a copied conversation from stdin or a file.
The default writes cleaned text to stdout; `-i` replaces the named input file after successful parsing.

```sh
clean-discord chat.txt
paste | clean-discord
clean-discord -i chat.txt
```

## In-place updates

In-place mode requires a file, preserves permissions, follows symlinks, and atomically replaces the file only after cleaning succeeds.
It produces no stdout output.
Failed cleaning leaves the original unchanged; already-cleaned IRC text is not accepted as Discord input.

## Supported paste format

It recognizes timestamp/name/colon headers split across lines, including a missing opening bracket on the first timestamp.
It removes trailing `[badge],` name decorations, detached copies at message boundaries, and blank lines.
An opening four-space-indented block separated from the reply by blank lines becomes a `>` quote; other indentation stays unchanged.
Other UI layouts are not supported; unrecognized text before the first header fails without output.
