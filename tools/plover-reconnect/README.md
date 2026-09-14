# Plover USB reconnect

Ever unplug and replug your steno device from your laptop?
Right now, to reconnect it to Plover, you have to manually reconnect it in settings.
This extensions watches USB events to automatically reconnect it.

This is currently not published to the Plover registry; you have to install it from source as shown below.
After installing, fully stop and restart Plover (don't just close the window).

Once installed, enable `plover-reconnect` in Plover's Extensions settings, open
the `USB reconnect` tool, select a device, and choose Save. The selected device
is stored persistently and can be changed without restarting Plover.

## Installation

```sh
plover -g none -s plover_plugins install --use-pep517 \
  --no-build-isolation /path/to/dotfiles/tools/plover-reconnect
```

If Plover isn't on PATH, use the fully-qualified path.
For example:

- Linux: `~/.local/bin/Plover.AppImage`
- macOS: `/Applications/Plover.app/Contents/MacOS/Plover`
- Windows PowerShell: `& 'C:\Program Files\Plover\Plover.exe'`

## Limitations

`usbx` exposes one process-global connected-device callback. This extension
assumes it is the only component in the Plover process registering that
callback; another extension can replace it, and stopping this extension clears
the shared callback. It cannot safely coexist with another consumer of that
`usbx` callback until `usbx` provides a multi-listener API.

## Development

Run the unit tests from this directory with:

```sh
python3 -m unittest discover -s tests
```

The plugin requires a running Plover 5.4–5.x host but does not declare Plover
as an install dependency, because the host is already present. The `test` extra
contains the Plover dependency for test environments. You can use `-e .`
instead of `.` to have changes reflected live, but be careful about metadata
caching, you may need to restart Plover.

This works by resetting the configured machine when the selected USB device model
is attached. It matches vendor and product IDs; descriptor text is only used to
identify devices in the selector.

## Publishing

Update `version` in `setup.cfg`, run the tests, and build the distributions:

```sh
python3 -m pip install --user build twine
python3 -m build
python3 -m twine check dist/*
```

Upload the checked distributions to PyPI with an account or trusted publisher
configured for the project:

```sh
python3 -m twine upload dist/*
```

After the package is available on PyPI, fork
[`opensteno/plover_plugins_registry`](https://github.com/opensteno/plover_plugins_registry),
add `plover-reconnect` to `registry.json` in alphabetical order, and open a pull
request. The plugin appears in Plover's Plugins Manager after that pull request
is merged and the registry cache refreshes.
