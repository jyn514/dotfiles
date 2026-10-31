# Copy and paste clipboard contents

[`copy`](../../bin/copy) and [`paste`](../../bin/paste) use the installed X11, Wayland, or macOS clipboard backend.

`copy` reads stdin into the clipboard; `paste` writes clipboard contents to stdout.
Copying replaces the selected clipboard contents.
Install a backend for the current graphical session: xclip/xsel for X11, wl-clipboard for Wayland, or the macOS clipboard tools.

```sh
copy < message.txt
paste > clipboard.txt
paste --primary
paste --type image/png > clipboard.png
```

Output redirection in these examples creates or replaces the destination file.

## Selections and MIME types

Pass `--primary` for the primary selection, or `--type MIME` before it for xclip and Wayland backends.
The MIME value stays one literal backend argument, including any spaces or glob characters:
xclip receives `-target MIME`, while Wayland receives `--type MIME`. xsel and macOS reject `--type`.

## Tests

Run from the dotfiles root.
`dev/pytest tests/copy` includes native X11 tests when xclip and Xvfb are installed;
they create a disposable display without using the desktop clipboard.
