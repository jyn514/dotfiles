#set document(title: "Sensitive process read isolation")
#set page(paper: "us-letter", margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true, leading: 0.65em)
#set heading(numbering: "1.")

= Sensitive process read isolation

*Status:* Draft design candidate.

This document records a target-scoped Linux design for protecting one sensitive launcher tree from same-uid process inspection.
It is not ready for implementation until the target-cgroup lookup is proven on the supported kernels.

== Problem

A launcher can avoid writing a secret to disk and still leave it readable once the launched process starts.
An unrelated process running under the same uid can inspect memory-facing procfs entries or use ptrace-class syscalls against that process.

For example, a shell runs a launcher which obtains a secret and then starts a local tool.
Another process under the same uid can open `/proc/$pid/environ`, read `/proc/$pid/maps`, call `process_vm_readv`, or attach with `ptrace`.
File mode `0600`, vault locking after the read, and `hidepid` do not establish a boundary against that attacker.

The desired outcome is narrower than a new host-wide security model.
One protected launcher tree should reject same-uid inspection while ordinary file access, sockets, D-Bus, signals, login paths, and desktop session behavior stay unchanged.

== Threat model

The attacker already runs arbitrary code as the same unprivileged uid as the protected launcher.
She can spawn helper processes, inspect ordinary user-owned files, call normal Linux process APIs, and retry against later descendants.

The design must stop that attacker from reading or attaching to protected tasks through interfaces guarded by `ptrace_may_access()`.
That includes memory-facing procfs reads and explicit ptrace-class syscalls.

The design does not protect against root, `CAP_SYS_PTRACE`, kernel compromise, code already running inside the protected task, or secrets exposed before the protected exec begins.
It also does not hide every procfs attribute.
The boundary covers the read and attach class of process inspection, not process existence or every metadata file under `/proc`.

== Chosen boundary

Protect one cgroup, not every process under the uid.

The user-facing command is `proc-hardening run -- COMMAND ...`.
It starts the sensitive launcher itself inside a fresh protected cgroup before that launcher can obtain secrets.
Every descendant stays in the same protected cgroup unless the privileged owner explicitly ends the launch.

The protected cgroup is a target marker, not an allow domain.
Two different protected processes still may not inspect each other merely because they share the cgroup.
Only the same task or the same thread group keeps ordinary self-inspection behavior.

A small privileged daemon owns the cgroup subtree and the BPF LSM program.
The unprivileged wrapper never receives a writable handle to the cgroup and never updates the BPF policy map.
That prevents same-uid malware from moving a target out of protection or deleting its policy entry.

== Launch trace

+ The user runs `proc-hardening run -- COMMAND ...`.
+ The wrapper forks a child that keeps the caller's uid, cwd, environment, tty, and file descriptors, then blocks before `execve()`.
+ The wrapper sends a pidfd-backed registration request to the privileged daemon.
+ The daemon creates a fresh child cgroup under its root-owned subtree, registers that cgroup as protected, and moves the blocked child into it.
+ Only after registration succeeds does the wrapper release the child to execute `COMMAND`.
+ The launcher obtains secrets and starts its descendants entirely inside the protected cgroup.
+ When the last task exits, the daemon removes the policy entry and then deletes the cgroup.

The child must not execute the sensitive launcher before registration is complete.
A pipe or equivalent one-way handshake is enough.
A bare PID is not enough because PID reuse would let the daemon act on the wrong task.

== Kernel policy

The daemon loads one BPF LSM program on `ptrace_access_check`.
That hook already sits behind the procfs and syscall paths that need protection.

The program is additive.
If an earlier LSM already denied the access, it returns that denial unchanged.
Otherwise it applies this rule:

```text
if target is not in a protected cgroup:
    allow
if caller and target are in the same thread group:
    allow
if mode contains PTRACE_MODE_READ or PTRACE_MODE_ATTACH:
    deny with EPERM
allow
```

`PTRACE_MODE_READ` covers procfs reads such as `/proc/$pid/environ` and `/proc/$pid/maps`.
`PTRACE_MODE_ATTACH` covers ptrace-style access such as `ptrace` and `process_vm_readv`.
The program denies both because the kernel uses the attach class for explicit cross-process memory access.

The program must classify the hook's target task, not the current caller.
A helper that only reports the current task's cgroup cannot implement this policy.
The first implementation must prove one target-task cgroup lookup strategy against the running kernel before the design can become ready.

No parent or child exception is part of the base policy.
A process tree is not a trust boundary once unrelated same-uid code can exist beside it.
If debugging is needed later, add an explicit short-lived exception bound to a live debugger task identity.
Do not add a broad parent, ancestor, or same-cgroup bypass.

== Daemon lifecycle

`proc-hardening.service` is a root-owned system service with a delegated private cgroup subtree.
The service owns every protected child cgroup and keeps the BPF link alive for as long as protection is available.
The host must boot with cgroup v2, BTF, and the `bpf` LSM active before the service accepts launches.

The service must fail closed.
If the BPF program cannot load, if the target cgroup cannot be registered, or if the daemon loses its policy state, the wrapper must not release the child.
If the daemon dies after a launch begins, `KillMode=control-group` must make systemd kill the protected child cgroups rather than let them continue without the LSM rule.

The first version should avoid pinned maps or long-lived bpffs state.
Fresh daemon startup should load a fresh empty policy set.
That keeps stale cgroup identities from surviving a crash or reboot.

The daemon does not need to parse or synthesize the child command's environment.
The unprivileged wrapper constructs the child process and preserves the caller's ordinary execution context.
The privileged daemon only verifies the requester's uid, binds the child identity, moves the child into the owned cgroup, and manages policy lifetime.

== Interfaces and ownership

The wrapper owns command-line parsing, fork and exec, tty behavior, and user-visible exit status.
It treats the daemon as a narrow registration service.

The daemon owns:

- the root-owned cgroup subtree;
- the BPF object, link, and protected-cgroup set;
- request authentication and pidfd validation;
- launch registration and cleanup; and
- fail-closed behavior on restart or crash.

The BPF program owns only the access decision at `ptrace_access_check`.
It does not own launch policy, command parsing, logging, or recovery.

The protected-cgroup set is the authoritative policy state for active launches.
Process names, executable paths, parentage, and shell ancestry are not authority.

Ordinary launch requests do not need a trusted same-uid caller.
Asking the daemon to protect another child does not grant access to protected tasks.
Any later interface that relaxes policy, such as a debugger exception, needs a separate authority path.

== Preserved behavior

The design does not change ordinary file permissions, sockets, D-Bus, signals, cgroups outside the daemon subtree, login managers, ssh, mosh, or desktop startup.
That is the reason to prefer the operation hook over a profile graph rooted in session launchers.

Unprotected processes under the same uid keep existing inspection behavior.
The user can still use `gdb -p`, `strace -p`, `ps e`, and similar tools against ordinary processes.
Protected processes reject those operations unless a future explicit debugger exception exists.

== Rejected alternatives

`hidepid` is insufficient because same-uid access still reaches the ptrace permission model.
On this host it also interacted badly with `systemd-oomd`, so it is not an acceptable shortcut.

A user-wide AppArmor profile is too fragile for this outcome.
It requires modeling every relevant session root and exec transition, and a missing root can both break the desktop and leave an uncovered path.

A uid-wide BPF rule is simpler:
deny when caller and target share the configured uid but have different thread groups.
That avoids cgroup registration entirely, but it also disables normal same-uid debugging and inspection across the whole session.
Keep that as a separate optional mode rather than the default design.

Smack or SELinux can express broader process labels, but they change the host's general label model.
That is a larger operational choice than this boundary requires.

== Verification

The implementation is complete only when all of these are shown on the real host:

- a protected launcher can run from an ordinary terminal, ssh session, mosh session, and graphical login;
- an unrelated same-uid process cannot read `/proc/$pid/environ` or `/proc/$pid/maps` for the protected task;
- an unrelated same-uid process cannot attach with `ptrace` or read memory with `process_vm_readv`;
- the protected process and its own thread group still work normally;
- an unrelated unprotected process remains inspectable, proving the rule is target-scoped;
- daemon failure kills protected children rather than leaving them running without policy;
- reboot and service restart restore protection before the next protected launch; and
- uninstall and recovery steps remove the daemon, BPF state, and cgroup subtree cleanly.

The test must observe the denial from the attacking process, not only inspect configuration or loaded programs.

== Open proof point

The design depends on classifying the `child` task passed to `ptrace_access_check` by protected cgroup membership.
Before implementation, prove one verifier-accepted method on the supported kernel set and record its compatibility range.
If that proof fails, stop and revisit the boundary rather than replacing it with a weaker PID map or a user-writable cgroup.
