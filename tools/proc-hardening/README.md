# Proc read guard

`proc-read-guard` adds the missing Yama-style parent check to same-uid
`PTRACE_MODE_READ` access.
It blocks unrelated sibling reads of `/proc/$pid/environ` and
`/proc/$pid/maps` while keeping parent-to-child reads.

The [design](design.typ) records the threat model and why this uses a BPF LSM
instead of `hidepid`, AppArmor, or a target-only SELinux policy.

## Install

Linux needs `clang`, `bpftool`, `pkg-config`, and libbpf >= 1.0 development files.
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

Stop the unit to restore the old behavior immediately:

```sh
sudo systemctl stop "proc-read-guard@$(id -u).service"
python3 tools/proc-hardening/probe.py --expect baseline
```

Starting or reloading the unit reapplies the rule.
The service is fail-open at boot: if loading fails, user sessions still start
and the unit remains failed for inspection.

## Build

```sh
make -C tools/proc-hardening
```

Generated BTF, skeleton, and loader artifacts stay under
`target/proc-hardening/`.
