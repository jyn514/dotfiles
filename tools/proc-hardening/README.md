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

## Policy tests

From the repository root:

```sh
dev/test-environment python3 tools/proc-hardening/tests/policy_test.py
```

These compile the actual policy as native C with test-only kernel-access shims.
They check group credentials and supplementary membership, unchanged parent and
sibling behavior, and preservation of prior security denials.
They do not replace kernel-verifier acceptance or a fresh live 1Password connection.

## Build

```sh
make -C tools/proc-hardening
```

Generated BTF, skeleton, and loader artifacts stay under
`target/proc-hardening/`.
