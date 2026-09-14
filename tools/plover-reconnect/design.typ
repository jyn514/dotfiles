#set page(paper: "us-letter", margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true, leading: 0.65em)
#set heading(numbering: "1.")

= Plover USB reconnect plugin

== Purpose

Provide a Plover extension that resets Plover's configured machine when a
user-selected USB device is attached. The first target is the ZSA Moonlander
Mark I, but selection works for any device reported by `usbx`.

The user selects a friendly device name. She does not enter or maintain USB
vendor or product IDs.

Automatic device discovery for Plover, serial-port selection, periodic polling,
and reconnection after failures unrelated to USB attachment are not goals.

== Package

The Python package provides two Plover entry points:

- `plover.extension`: observes attachment and requests reconnection;
- `plover.gui.qt.tool`: selects the device to observe.

The extension class is constructed with one `StenoEngine`. The GUI class inherits
`plover.gui_qt.tool.Tool`, defines `TITLE` and `ROLE`, and is constructed with one
engine argument.

It supports 64-bit Windows, Linux, and macOS. It requires `plover >= 5.4, < 6`,
Python 3.10 or later, and `usbx >= 0.8.3, < 0.9`. `usbx` is the only host-device
backend; the plugin contains no platform-specific USB code.

== Learned device

The configuration tool lists devices returned by `usbx` as
`Manufacturer — Product`. Selecting *Use this device* records this fingerprint:

```json
{
  "schema": 1,
  "device": {
    "vid": 12951,
    "pid": 6505,
    "manufacturer": "ZSA Technology Labs",
    "product": "Moonlander Mark I"
  }
}
```

The example's numeric values are `0x3297` and `0x1969` in decimal. VID and PID
identify the model and are the complete matching authority. Manufacturer and
product are display labels. Any attached device of the learned model triggers a
reset.

The tool is the sole writer of `CONFIG_DIR/plover-reconnect.json`. It validates
the selected device and publishes the complete file with atomic replacement.
The extension loads and validates the file on each attachment, so a new
selection takes effect without restarting Plover. Missing, malformed, or
unsupported configuration disables reconnection and produces one useful log
message.

== Runtime behavior

The extension has three states: `stopped`, `watching`, and `reset-pending`.

+ `start()` registers one `usbx.usb.on_connected` callback, then calls
  `usbx.usb.get_devices()` to start usbx's lazy monitor. If initialization fails,
  it unregisters the callback before propagating the failure to Plover. Devices
  already present during startup do not trigger a reset.
+ Each attachment callback loads the fingerprint and returns unless the
  attached device matches it.
+ A match schedules one reset after a fixed one-second settling delay. A second
  matching event replaces the pending timer rather than adding another reset.
+ When the timer fires, it calls the public `engine.reset_machine()` API. Plover
  queues the reset on its engine thread.
+ `stop()` marks the extension stopped, cancels its timer, and calls
  `usbx.usb.on_connected(None)`. It is idempotent; cleanup failures are logged
  and do not escape into Plover.

The usbx callback runs on its monitor thread and must only validate, match, and
schedule. It must not reset Plover directly. The timer callback checks its
lifecycle generation and calls `reset_machine()` while holding the extension
lock. `stop()` acquires the same lock, so work from an earlier lifecycle cannot
enqueue a reset after `stop()` returns.

Timer cancellation is best effort. If two matching callbacks overlap timer
execution, both may queue a reset. This bounded race can cause an extra reconnect
but cannot corrupt plugin state; the design does not add coordination to prevent
it.

The process-global usbx monitor thread remains alive until Plover exits. This is
usbx behavior and is acceptable because the design assumes this plugin is its
only caller within the Plover process.

== Ownership boundaries

- usbx owns OS monitoring, native handles, enumeration, and its daemon thread.
- The extension owns its callback registration, timer, lifecycle generation,
  and reset decision.
- The configuration tool owns user selection and configuration publication.
- `plover-reconnect.json` is the authoritative selected fingerprint; friendly
  list labels are derived from current USB descriptors.
- Only Plover owns machine construction and teardown. The plugin uses
  `reset_machine()` and never reads `engine._machine` or constructs a machine.

== Failure behavior

An unreadable configuration or usbx initialization failure is logged without
terminating Plover. `reset_machine()` only queues work; Plover owns and logs any
later machine-reset failure. The plugin neither observes nor retries it. A later
matching attachment is the next retry opportunity.

After `stop()` returns, the plugin does not request another reset. A reset
already queued in Plover may still run.

== Verification

Tests use fake USB and engine boundaries and must show:

- initial enumeration does not reset;
- unrelated devices do not reset;
- a learned Moonlander attachment causes one reset after the delay;
- identical devices with the learned VID and PID both match;
- duplicate events before timer execution coalesce;
- malformed or missing configuration does not reset;
- stopping before the timer fires prevents the reset; and
- failed startup unregisters its callback, while idempotent stop and a stop/start
  cycle reject work from the earlier lifecycle.

Before release, one integration test per supported platform must verify an
actual attach event with a disposable USB device. Install the plugin through
Plover's plugin manager and exercise it on a packaged Plover build: success in
the source interpreter does not establish bundled-runtime compatibility.
