# Proc read guard

`proc-read-guard` adds the missing Yama-style parent check to same-uid
`PTRACE_MODE_READ` access.
It blocks unrelated sibling reads of `/proc/$pid/environ` and
`/proc/$pid/maps` while keeping parent-to-child reads.

Processes holding the `onepassword` group are trusted readers and exempt from
this guard's read restriction, including reads of unrelated same-uid processes.
The loader resolves the group at load time; a missing group disables only the
exemption, not the guard.
Real, effective, saved, filesystem, and supplementary group credentials count.
Saved credentials cover helpers that temporarily drop their effective group.
There is no executable-name, ownership, or parent-only restriction on this group
exemption, and it does not override denials from other security modules.

This permits 1Password's native connector to verify the browser through
`/proc/$pid/exe` without letting ordinary same-uid processes read live secrets.

The [design](design.typ) records the threat model and why this uses a BPF LSM
instead of `hidepid`, AppArmor, or a target-only SELinux policy.

## Install

Linux needs a C compiler, `clang`, `bpftool`, `pkg-config`, and libbpf >= 1.0 development files.
Arch global setup now tracks the extra packages `bpf` and `libbpf`.
The running kernel also needs BTF at `/sys/kernel/btf/vmlinux`, the `bpf` LSM,
and `kernel.yama.ptrace_scope=1`.

From the dotfiles checkout:

```sh
./setup proc-hardening
```

The installer builds the CO-RE object as the invoking user, snapshots the
loader and unit bytes, streams them through root-owned `/usr/bin/install`, and
enables the current uid as a want of `systemd-user-sessions.service`.
It starts the instance immediately.
Later installs use `ExecReload=` to replace the pinned program in place, so
the old rule stays attached unless the new one is ready.

## Verify and operate

The probe creates one target process, then compares a parent read with a sibling
read.
Before installation, both reads should succeed.
After installation, the parent should still succeed and the sibling should fail.

```sh
python3 tools/proc-hardening/probe.py --expect protected
sudo /usr/local/libexec/proc-read-guard status "$(id -u)"
systemctl status "proc-read-guard@$(id -u).service"
```

`status` reopens the pinned link and verifies that it is the current expected
LSM program for that uid before treating it as healthy.
`unload` verifies the stable program identity and protected uid before removing
it, so it can still clean up an older compatible pin after the map layout grows.
`status` also reports and validates the configured trusted-reader gid.
After creating or changing the `onepassword` group, reload the unit to resolve
its current gid; an already-loaded rule keeps its previous configuration until
reloaded or restarted.

Stop the unit to restore the old behavior immediately:

```sh
sudo systemctl stop "proc-read-guard@$(id -u).service"
python3 tools/proc-hardening/probe.py --expect baseline
```

Starting or reloading the unit reapplies the rule.
The service is fail-open at boot: if loading fails, user sessions still start
and the unit remains failed for inspection.

## Browser cookies and desktop launch

On Linux, [`desktop.py`](desktop.py) extends the guard with private Glide profile storage.
Glide keeps the desktop user's uid and primary gid, and receives supplementary group `browser`.
1Password desktop keeps the same uid and primary gid, and receives supplementary group `onepassword`.
Do not add either group to the user's account or login session.
The existing `onepassword` group exemption lets the desktop app verify the browser without `CAP_SYS_PTRACE`.

Store the complete native Glide registry tree at `/var/lib/glide-private/profiles`.
Its parent `/var/lib/glide-private` must belong to `root:browser` with mode `0710`.
The inner tree stays owned by the desktop user.
Link `~/.config/glide/glide` to that tree, retaining the surrounding Glide TypeScript configuration and the normal HOME.
Migrate every registered profile and installation default, and move old readable cookie copies under protected storage too.
The worker resolves `profiles.ini` and `installs.ini` paths and refuses an external registered profile.
Keep an active trial profile's newer data when migrating; close every browser instance before moving any profile.
Archive displaced profiles inside protected storage instead of deleting them.

Each application has a system socket and an accepting service template, generated for one uid and primary gid.
The sockets live under root-owned `/run/dotfiles-private-desktop-UID/`, with mode-0600 socket files owned by that uid.
Systemd sets the service's user and groups before starting the worker.
The worker parses one bounded request containing arguments, the working directory, and selected desktop environment variables.
It receives the caller's standard streams, starts a fixed native executable, and waits for its exit.
The caller receives the app's exit status; disconnecting the caller leaves the app running.
The browser's process ancestry goes through the system service, not the requesting program.
The services require `proc-read-guard@UID.service`.

The wrappers [`glide-bin`](../../bin/glide-bin) and [`1password`](../../bin/1password) use the installed client and worker protocol together.
Before `/usr/local/libexec/dotfiles-private-desktop` is installed, they forward to the ordinary native executables.
After installation, a missing socket is an error, not a fallback to an ungrouped process.
Glide arguments pass through unchanged.
1Password accepts only `--silent` and `onepassword:` / `onepassword8:` URLs: Electron debugging switches can execute commands with its trusted group.
On Wayland the worker supplies 1Password's `--ozone-platform=wayland` option.
The worker fixes HOME and omits loader variables and `XDG_CONFIG_HOME`, keeping the registry at the path it validates.

The browser and its configuration remain trusted.
Directly spawned browser helpers inherit its group; that includes an untrusted application opened directly by the browser.
This arrangement protects profile files and guarded process reads, not against deliberately driving the trusted browser to disclose data.

### Prepare and install launch services

Install the native Glide and 1Password packages first, including 1Password's vendor-managed `onepassword` group.
The [guard build and kernel prerequisites](#install) apply too.
From the dotfiles checkout, as the desktop user:

```sh
./setup private-desktop
```

This builds the guard without privilege and prepares the worker, four units, and an `install.fish` command block under `target/private-desktop-*/`.
The command prints the exact file to review and paste into Fish; do not sudo or blindly execute that file.
Every privileged command names `sudo -u root` and a native operation directly.
The block creates only the `browser` group, installs the guard and launch services, and refreshes both desktop entries.
UID, primary GID, and HOME come from the invoking account, not this workstation's values.
Neither the current session nor the account's persistent groups may contain `browser` or `onepassword`.

For initial migration, close every Glide instance and quit 1Password before pasting the block.
It moves the complete `~/.config/glide/glide` tree into protected storage and leaves a symlink at its original path.
Profile contents and registry files stay unchanged; an empty installation lets Glide create its own first profile.
External registered profiles, unexpected registry symlinks, and partial installations stop preparation for inspection instead of being rewritten or merged.
Registry changes between preparation and migration stop the command block before the move.
Rerunning setup on an already managed installation prepares updates without moving profiles again.
If any migration operation fails, inspect the state before retrying; do not rerun the block blindly.

Refresh only the two application launchers without changing MIME defaults:

```sh
python3 libexec/setup/setup_mimetypes.py --private-desktop-only
```

This preserves Glide's new-window, private-window, and profile-manager actions.
It rewrites an existing 1Password autostart entry but does not enable autostart.
Normal MIME setup also maintains these overrides.
KDE may need `kbuildsycoca6 --noincremental` to refresh the application launcher.
Keep the same desktop entry identifiers so existing default-browser and URL associations still apply.
Use the wrappers or desktop entries, not the package's absolute `/usr/bin/glide-bin` or `/opt/1Password/1password` paths.
If 1Password recreates its native autostart entry after changing its autostart setting, refresh these launchers again.

Socket activation and group membership need host acceptance after installation.
Check the actual main-app credentials, forbidden ordinary-user file/proc reads, and a fresh 1Password extension connection.
Also exercise Command–Space, URL opening, downloads, and lock/unlock with the final launch path.
If you use 1Password's SSH agent or `op` CLI integration, check those against the restarted desktop app too.
The transport/desktop fixtures run through `dev/test --integration`, or directly:

```sh
dev/pytest tools/proc-hardening/tests/desktop_test.py tools/proc-hardening/tests/prepare_desktop_test.py tests/setup/private_desktop_test.py tests/setup/glide_test.py
```

### Retiring an earlier separate-user trial

An existing `browser` account and `/var/lib/browser` may still own protected rollback profiles.
The new launch path does not use that account; setup leaves the account and its files alone.
Retire that data only after deciding it is no longer needed.
Keep the `browser` group when retiring the account: the active supplementary-group services and profile storage still use it.

## Policy tests

From the repository root:

```sh
dev/test-environment python3 tools/proc-hardening/tests/policy_test.py
```

These compile the actual policy as native C with test-only kernel-access shims.
They check group credentials and supplementary membership, unchanged parent and
sibling behavior, and preservation of prior security denials.
They do not replace kernel-verifier acceptance or a fresh live 1Password connection.

The native skeleton regressions need the build dependencies and host BTF, but
not root:

```sh
dev/test-environment python3 tools/proc-hardening/tests/skeleton_failure_test.py
```

They use the generated skeleton and installed libbpf, inject failure into each
constructor allocation, and force cleanup to overwrite `errno` during an update.
BPF loading, attachment, pin changes, and filesystem mutation are blocked in the
modeled update path.

The loader keeps an allocation-failure compatibility shim around generated
cleanup: libbpf 1.8.0 can dereference a missing program array when its count is
already set. The shim clears that count only when the array is absent, then uses
the public libbpf destructor. Generated headers remain unchanged, and normal
allocated arrays receive normal cleanup.
The loader also preserves the original skeleton-open error before releasing
old link and program references, so cleanup cannot replace the primary diagnostic.

## Build

```sh
make -C tools/proc-hardening
```

Generated BTF, skeleton, and loader artifacts stay under
`target/proc-hardening/`.
