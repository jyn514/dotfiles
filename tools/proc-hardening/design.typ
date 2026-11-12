#set document(title: "Sensitive process read isolation")
#set page(paper: "us-letter", margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true, leading: 0.65em)
#set heading(numbering: "1.")

= Sensitive process read isolation

*Status:* Implemented in dotfiles; the first live sibling-read probe passed, and the full rollout matrix is still pending.

This document records the actual security goal, the observed facts, the selected BPF design, and the remaining rollout evidence.
It exists so later work does not silently replace the goal with whichever mechanism was most recently discussed.

== Goal

The primary asset is a bearer token after a launcher has obtained it.
On this machine, `~/.local/bin/daybreak` decrypts a token and then executes `codex` with that token in `CODEX_ACCESS_TOKEN`.
The attacker is arbitrary code already running under the same unprivileged uid as that process.

The live-state property is:

```text
unrelated same-uid code must not be able to read sensitive live process state from another process
```

That includes environment, memory-facing procfs files, and ptrace-class reads.
The preferred scope is user-wide sibling isolation with the same parent-to-child exception that Yama already uses for ordinary attach-class access.
Protecting only one named launcher tree is a fallback if the user-wide rule proves too disruptive.

The investigation found a second exposure:

```text
the bearer token must not be copied into child environments or persisted state that unrelated same-uid code can read later
```

That second property is not a replacement for the live-state property.
It is required because the current launcher and Codex session already copy the token outside the original process.

Root, `CAP_SYS_PTRACE`, kernel compromise, and code already executing inside the target process are out of scope.
The goal is not to hide process existence or to stop ordinary file reads.

== Observed facts

+ The active launcher inspected on 2026-11-11 is:
+
+ ```bash
+ #!/usr/bin/env bash
+ set -eu
+ ulimit -c 0
+ config_dir=${XDG_CONFIG_HOME:-"$HOME/.config"}/daybreak
+ token=$(age -d -i "$config_dir/identity.txt" "$config_dir/token.age")
+ exec env CODEX_ACCESS_TOKEN="$token" codex -c cli_auth_credentials_store=ephemeral "$@"
+ ```
+
+ The token therefore exists in a live process environment after `execve()`.
+ The launcher already disables core dumps with `ulimit -c 0`.
+ A host probe on 2026-11-11 found `CODEX_ACCESS_TOKEN` in at least 18 same-uid processes, including `codex`, shell children, `pi`, `cargo`, and `rustc`.
+ A host probe on 2026-11-11 found the current bearer token in six `~/.codex/shell_snapshots/*.sh` files.
+ `~/.codex/shell_snapshots/` is mode `0700`, but its snapshot files are mode `0644`.
+ A separate search found the same current token in five rollout JSONL files plus `logs_2.sqlite` and `thread_history_1.sqlite`.
+ Those session and database copies were created after tool output printed a shell snapshot; they are persisted copies, not proof that Codex stores the auth token there during normal startup.
+ `~/.codex/auth.json` and `~/.config/daybreak/token.age` do not contain the current plaintext token.
+ The tracked Codex profile now sets `shell_environment_policy.exclude=["CODEX_ACCESS_TOKEN"]` in `config/agents/codex/codex.toml`.
+ jyn explicitly chose a user-wide “no sibling reads” goal on 2026-11-11, not only a Codex-specific boundary.
+ The current host has `kernel.yama.ptrace_scope=1`.
+ The current `/proc` mount does not use `hidepid`.
+ The current host loads the `bpf` LSM and has `CONFIG_BPF_LSM=y`, `CONFIG_BPF_SYSCALL=y`, and `CONFIG_DEBUG_INFO_BTF=y`.
+ The current host has `kernel.unprivileged_bpf_disabled=2`, so a live BPF LSM probe needs privilege.
+ A disposable CO-RE compile probe on 2026-11-11 verified that this host exposes `task_struct.tgid`, `task_struct.real_parent`, and `cred.uid` through BTF.
+ That probe also verified that a `lsm/ptrace_access_check` program with a 16-hop unrolled ancestry walk compiles successfully against the running kernel headers.
+ A prior `hidepid=ptraceable` probe observed that sibling `strace -p` failed while `/proc/$pid/environ` remained readable.
+ A prior target-only AppArmor probe observed that an unconfined same-uid reader could still read the target's `/proc/$pid/environ` and `/proc/$pid/maps`.
+ A prior user-session AppArmor attempt attached at `user@1000.service` and broke the graphical session.
+ Removing the `hidepid` mount option restored the desktop while keeping `systemd-oomd`.
+ On 2026-11-12 after installation, the tracked probe showed parent `/proc/$pid/environ` and `/proc/$pid/maps` reads still succeeding while same-uid sibling reads of both files failed.
+ jyn separately confirmed that sibling `/proc/$pid/environ` failed while `/proc/$pid/cmdline` remained readable, which matches the intended boundary.

== Findings from the unknowns

=== Concrete read paths

The baseline host probe on 2026-11-11 produced:

```text
reader    environ    maps       mem        process_vm_readv    ptrace attach
sibling   readable   readable   denied     denied              denied
parent    readable   readable   readable   readable            allowed
```

The live leak today is therefore the read-class procfs side, especially `environ` and `maps`.
Yama already blocks sibling attach-class reads under the current `ptrace_scope=1` setting.

=== One hook does cover the relevant live reads

Linux routes `/proc/$pid/environ` and `/proc/$pid/maps` through `PTRACE_MODE_READ`.
It routes `/proc/$pid/mem`, `process_vm_readv`, and ptrace attach through `PTRACE_MODE_ATTACH`.
All of those checks reach `security_ptrace_access_check()`.

Yama only adds its ancestry rule when `mode & PTRACE_MODE_ATTACH` is true.
That matches the baseline: sibling attach-style reads already fail while sibling `environ` and `maps` reads still work.

`PTRACE_TRACEME` uses a separate hook.
A policy attached only to `ptrace_access_check` would not block the usual “launch under `gdb` or `strace`” flow where the child opts into tracing.

=== `PR_SET_DUMPABLE=0` is strong but not a wrapper-only fix

When the target process called `prctl(PR_SET_DUMPABLE, 0)`, both sibling and parent readers lost access to all five tested interfaces.

```text
reader    environ    maps       mem        process_vm_readv    ptrace attach
sibling   denied     denied     denied     denied              denied
parent    denied     denied     denied     denied              denied
```

A separate probe produced `before_exec=0` and `after_exec=1`.
Setting dumpable in a launcher does not survive a normal `execve()`.
The final process must cooperate after exec, or a preload or runtime hook must do it.

=== PID namespaces do not create the required boundary

A process started in a fresh PID namespace remained readable from the host user session through `/proc/$hostpid/environ`.
Bubblewrap or `unshare --pid` alone does not stop a same-uid reader outside that namespace.

=== Codex now has a narrower immediate mitigation

The tracked Codex profile now sets `shell_environment_policy.exclude=["CODEX_ACCESS_TOKEN"]`.
The installed Codex CLI accepts that field.
Upstream Codex applies the shell environment policy both when it spawns shell-like tools and when it renders shell snapshots.
Its default policy inherits the full parent environment and skips the default `*KEY*`, `*SECRET*`, and `*TOKEN*` exclusions.

That exact exclude should stop future shell-tool inheritance and future shell-snapshot copies.
A fresh Codex session still needs to verify that the installed build loads the profile and omits the variable from new snapshots.
It does not remove the token from the parent Codex process itself.
No supported per-run auth handoff was found that gives Codex an ephemeral access token without leaving it in the parent environment.

=== SELinux is a target-domain option, not the smallest user-wide fix

The prior SELinux source inspection corrected the earlier plan.
For this kernel path, SELinux checks `PTRACE_MODE_READ` procfs access as file reads, while the stock `deny_ptrace` boolean only removes `process:ptrace`.
A small targeted-policy add-on therefore does not close `/proc/$pid/environ` or `/proc/$pid/maps` for ordinary `unconfined_t` readers.
A larger SELinux policy could still protect labeled targets.
That becomes a host label-model choice instead of the smallest rule for user-wide sibling isolation.

=== Compatibility evidence

Upstream systemd v262 source has a BPF LSM guard for PID 1 that intentionally leaves `PTRACE_MODE_READ` allowed because monitoring tools and `systemctl` read procfs data.
On this host, `strace systemctl --user status` showed reads of `/proc/1/root` and `/proc/sys/kernel/ngroups_max`, not same-uid sensitive files.

`ps -u 1000` performed 1,512 opens of proc entries named `stat`, `status`, and `cmdline`.
That proves ordinary inspection tools use procfs heavily.
The rollout matrix below distinguishes expected breakage from regressions.

== Selected BPF design

The production rule adds Yama's default parent-ancestry rule to the missing read-class operations.
It relies on `kernel.yama.ptrace_scope=1` to keep handling attach-class access.
The BPF LSM program attaches only to `ptrace_access_check` and applies only when `mode & PTRACE_MODE_READ` is set.

```text
if an earlier LSM already denied the access:
    return that denial
if caller uid != protected uid or target uid != protected uid:
    allow
if caller and target are in the same thread group:
    allow
if caller's process leader appears in the target process leader's `real_parent` chain within 16 hops:
    allow
deny with EPERM
```

This blocks sibling `/proc/$pid/environ`, `/proc/$pid/maps`, and other read-class procfs inspection.
It keeps parent-to-child reads and post-hoc debugging for the normal shallow process trees on this host.
The ancestry walk normalizes both sides to thread-group leaders before comparing, matching Yama's process-level semantics for multithreaded parents.
The host probe observed a maximum same-uid ancestry depth of 7, so a 16-hop bound leaves headroom without an open-ended walk.
If the ancestry chain exceeds 16 hops, the program denies by default.
The program does not add `PR_SET_PTRACER` or active-tracer exceptions.
It leaves `PTRACE_TRACEME` unchanged, so `gdb ./prog` and `strace ./prog` still use the existing launch-under-debugger path.

=== Loader and lifecycle

This rule has no per-launch state, so it does not need a daemon or writable policy map.
A concrete implementation uses `proc-read-guard.bpf.c` for the CO-RE program, a generated libbpf skeleton, and a tiny C loader in `proc-read-guard.c`.
The loader owns only load, in-place update, pin, unpin, and health output.
systemd owns lifecycle.
The setup path builds as the invoking user, snapshots the loader and unit bytes, and streams those bytes through root-owned `/usr/bin/install`; it does not re-execute checkout Python as root.
That removes post-elevation checkout races, but it does not make an already-compromised uid a trusted build source before those bytes are snapshotted.
A root-owned `proc-read-guard@UID.service` oneshot loads one program instance for one uid, pins the attached link at `/sys/fs/bpf/proc-read-guard/UID/link`, and exits.
The loader resolves `%i` as the numeric uid and writes it into BPF `.rodata` before load.
The loader refuses to attach unless `/proc/sys/kernel/yama/ptrace_scope` is `1`.
Changing that sysctl after load is unsupported because it weakens attach-class protection that this program intentionally leaves to Yama.
`ExecStop` reopens and unpins that link, which detaches the program when the last reference disappears.
When `load` sees an existing pin, it reopens that link, verifies the stable program identity and protected uid, loads the replacement program, and swaps the link with `BPF_LINK_UPDATE`.
That keeps the old rule attached unless the new program is ready.
`status` verifies the current program name, program type, program tag, exact rodata map shape, and protected uid.
`unload` verifies the stable program identity, a compatible rodata prefix, and protected uid, but does not require the current build to load successfully first.
The stable recovery contract is one `.rodata` array map whose first field remains `protected_uid`; later fields and unrelated maps may be added without making old pins impossible to remove.
Multiple protected users use multiple service instances.
The unit uses `RemainAfterExit=yes`, so systemd keeps it active after the loader exits, runs `ExecReload` for in-place upgrades, and still runs `ExecStop` on stop.
Each installed instance is enabled as a want of `systemd-user-sessions.service`.
The unit orders before `systemd-user-sessions.service`, which removes `/run/nologin` and permits PAM logins.
V1 is fail-open: if load or pin fails, the unit is failed and the login path stays available because the dependency is a want rather than a requirement.
The service status and the negative sibling-read probe are the health check.

== Verification

The first rollout is complete only when the real host shows all of these:

+ an unrelated same-uid sibling cannot read `/proc/$pid/environ` or `/proc/$pid/maps`;
+ sibling `/proc/$pid/mem`, `process_vm_readv`, `gdb -p`, and `strace -p` remain denied under Yama;
+ a parent can still read its child's `environ` and `maps` and can still attach with `gdb -p`;
+ `gdb ./prog` and `strace ./prog` still work;
+ `ps -u UID`, `systemctl --user status`, graphical login, a fresh tty or terminal, a fresh tmux session, ssh, and mosh still work;
+ `ps e` or equivalent sibling environment readers fail as the expected changed behavior;
+ a fresh Codex session no longer writes `CODEX_ACCESS_TOKEN` into shell children or shell snapshots;
+ stopping the unit removes the pinned link and immediately restores the previous read behavior; and
+ reboot loads the rule before `systemd-user-sessions.service` permits the first protected user session.

== Mechanism inventory

There are five basic control points:

+ Stop copying the token into shell children and shell snapshots.
+ Stop keeping the token in the parent process after startup.
+ Move the sensitive process into a different trust domain, such as another uid, a VM, or another kernel-enforced container boundary.
+ Mediate cross-process reads at the kernel operation that grants access.
+ Accept a narrower target-scoped boundary and protect only the launcher tree that holds the secret.

Mount options, file modes, vault locking, and core-dump settings can reduce exposure around the edges.
They do not create the required same-uid boundary by themselves.

== Compare and contrast

#table(
  columns: (1.55fr, 1.05fr, 1.05fr, 2.35fr),
  inset: 5pt,
  [*Option*], [*Stops live sibling reads*], [*Stops child or snapshot leak*], [*Main cost or limit*],
  [Shell env exclude], [No], [Yes], [Low-friction immediate mitigation; parent Codex env remains readable.],
  [New auth handoff], [Maybe], [Maybe], [Best outcome if supported; no supported per-run path has been found yet.],
  [`PR_SET_DUMPABLE=0`], [Yes], [No], [Blocks parent reads too and resets across `execve()` unless the final process cooperates.],
  [PID namespace only], [No], [No], [Host same-uid readers still see the target through host `/proc`.],
  [Uid-wide BPF LSM], [Yes], [No], [Best match for the preferred live-state goal; adds Yama's default parent-ancestry rule to read-class access.],
  [Target-scoped BPF LSM], [Yes, for marked targets], [No], [Preserves more observability; implements a narrower goal.],
  [SELinux target domain], [Yes, with broader policy work], [No], [A small targeted add-on does not subtract stock proc `file:read` allows.],
  [Separate uid or VM], [Yes], [Yes, if secrets stay inside], [Strongest boundary; highest workflow and recovery cost.],
)

The shell environment exclude is already tracked because it reduces real exposure without choosing a kernel policy.
It should be treated as an independent fix, not as a replacement for live same-uid isolation.

The selected BPF design is still the best match for the live-state goal.
It adds the read-side ancestry check that Yama omits while leaving attach behavior with Yama.

`PR_SET_DUMPABLE=0` is attractive only if Codex or another final-process hook can set it after exec.
It is not a clean launcher-only answer.

SELinux remains the strongest target-scoped non-BPF alternative.
It is a worse fit for the user-wide sibling rule because the small add-on policy does not close the read-side procfs leak.

The separate-uid or VM path is the clean fallback if the live uid-wide rule is too disruptive.

== Known false shortcuts

+ `hidepid` does not by itself establish the desired boundary.
+ A target-only AppArmor profile does not by itself establish the desired boundary against unconfined same-uid readers.
+ A session-root profile is not automatically safe merely because it covers more processes.
+ A PID namespace alone does not establish the desired boundary against host same-uid readers.
+ Setting dumpable in the launcher does not survive `execve()`.
+ Stock targeted SELinux plus `deny_ptrace` does not close the read-side procfs leak.
+ A target-scoped design is not the same goal as user-wide sibling isolation.

== Next step

Finish the remaining rollout matrix above on the real host.
Verify the Codex exclude in a fresh session before rotating the bearer token and removing the persisted copies that already exist.
