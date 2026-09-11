#set document(title: "Own subprocesses through shutdown")
#set page(margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true)

= Own subprocesses through shutdown

*Status:* Group-supervision changes proposed; findings describe the review baseline.
Review baseline: `bbb5b88a`, 2026-09-11.
Paths below are relative to `tools/codex-sandbox/` unless stated otherwise.

== Problem and recommendation

Several cleanup paths terminate a wrapper and treat its exit as completion of
the entire operation. A child can retain pipes, a transport connection, or work
after its parent exits. The problem includes SSH, Lima transports, monitor
clients, and fixture cleanup; it is not confined to `bin/ssh`.

Give each noninteractive subprocess operation an explicit lifecycle owner.
That owner either invokes a known leaf executable directly or owns a private
process group and drains it independently of the leader's exit status.
Keep remote workload cleanup separate. Improve the SSH wrapper's graceful
signal handling only as a complementary change.

== Evidence and affected paths

=== Credential transport: reproduced with local stand-ins

`sandbox_credentials.py`, `boot_credential()`, starts its transport without a
private group. On cleanup timeout it calls `process.kill()` and then an
unbounded `communicate()`. Killing the wrapper does not close output pipes
retained by its child, so cleanup can hang after its timeout has already fired.

A disposable probe exercised the real function with a wrapping client and
synthetic ready response. The wrapper died from SIGKILL; its child remained
alive holding the pipe. Communication deadlines were shortened to 0.2 seconds,
including a bound on the otherwise unbounded final call. No credentials or real
credential cache were accessed.

=== SSH through PATH: reproduced with the installed wrapper

`lima/docker_host.py`, `guest_argv()` and `runtime_epoch()`, select `ssh` through
PATH. On the reviewed host this resolves to the repository's `bin/ssh`, a shell
that runs native SSH and diagnoses failures afterward. The wrapper does not
replace itself with SSH or forward termination signals.

During the Unix-socket forwarding experiment, terminating the wrapper left its
native child holding the tunnel and stderr pipe. Disabling SSH persistence did
not fix it; invoking `/usr/bin/ssh` directly did. Ordinary guest queries use
`lima/host.py`, `command()`, whose `subprocess.run()` timeout likewise kills only
the direct child. That query failure follows from the source and wrapper probe;
it was not reproduced against a stalled production readiness query.

=== Runtime transports: source findings

`sandbox_runtime.py`, `workload()`, creates and attaches through subprocesses
without allocating private groups. Its timeout fallbacks kill the creation or
attachment PID. The Lima overrides of `forward_proxy()` and `monitor()` also
kill only their local transport PID after their remote cleanup attempts.

These paths can invoke `limactl` and SSH descendants. They need ownership of
local transport shutdown, but this review did not reproduce each failure in a
live VM. Preserve container removal, guest exec-ID cleanup, and the monitor's
graceful control-pipe message when changing local process management.

=== Monitor wait clients: reproduced with a wrapping client

`sandbox_monitor.py`, `monitor()`, terminates wait clients by PID and waits only
for their leaders. The real monitor function, supplied a disposable wrapping
client, exited with status 143 while that client's child survived.

Current Docker wait clients are invoked directly. This proves the monitor
abstraction does not supervise descendants; it does not establish a leak from
ordinary native Docker waits. Decide whether the monitor owns one group for its
whole tree or each wait has a separate owner before changing those spawns.

=== Existing group cleanup: incomplete liveness check

`codex-sandbox`, `cleanup()`'s `wait_process()`, already signals the Docker
monitor group. It escalates to SIGKILL only when waiting for the leader times
out, and skips group cleanup for leaders that exited with other statuses.

A local probe with an exited leader and a child ignoring SIGTERM reproduced
the faulty assumption: signalling the group and successfully waiting for its
leader leaves the child alive. Group shutdown must not depend on leader
liveness. `docker_runtime.py`, `stop_build()`, already checks group members
after wrapper exit and supplies a starting point for this behavior.

=== Fixture cleanup and intentional fault injection

`tests/lima_launcher_integration.py`, `terminal_run()`, creates a private session
but its emergency fallback kills only the launcher PID. Final cleanup should
drain owned groups even after their leaders exit. Separately owned nested
builder and monitor sessions still need their own cleanup owners.

Keep deliberate single-PID signals in tests that simulate loss of a supervisor
or transport. Broadcasting those test signals would hide the failure being
tested. Strengthen final cleanup without changing the injected fault.

== Ownership model

A PID identifies one process. A process group is a signal destination, not a
recursive process tree. Children normally inherit the group, but can leave it;
an SSH master or a nested session may have a different lifetime and owner.

For a noninteractive operation that needs group ownership:

+ Create the private group at spawn. `start_new_session=True` makes the child's
  PID its group ID and prevents shutdown signals from reaching the caller.
+ Register ownership before waiting or publishing the process to another worker.
  Nested work stays in that group unless a separate owner is responsible for it.
+ Attempt protocol-specific graceful shutdown first: close credential input,
  send the monitor's control message, or remove the owned remote workload.
+ On cancellation or timeout, signal the owned group with SIGTERM, then SIGKILL
  after a bounded grace period if live members remain. Inspect group membership
  independently of `Popen.poll()` and `wait()`; an exited leader is not completion.
+ Reap the direct child and finish or close owned pipes with bounded waits.
  Report incomplete cleanup without obscuring the primary failure or exposing
  credential output. Do not retain process-group IDs as durable recovery handles.

Do not substitute `killpg(getpgid(pid), ...)` for `terminate()` on arbitrary
existing processes: their group may contain the launcher or unrelated commands.
Group supervision covers cooperative subprocesses, not hostile descendants
that deliberately detach. Interactive terminal clients need separate validation
of foreground groups, terminal input, and signal delivery before changing their
session arrangement.

Prefer a small shared owner for the demonstrated lifecycle needs over parallel
ad hoc cleanup loops. Extract the useful group-draining behavior from the builder
implementation only when migrating a second caller; keep Docker verification,
remote identities, and credential handling with their current owners.

== What an SSH trap can and cannot fix

A TERM trap can make `bin/ssh` forward graceful termination and reap its native
child while retaining post-exit diagnostics. A shell waiting on a foreground
command may defer its trap, so a working implementation needs an interruptible
wait strategy. If it backgrounds SSH, explicitly preserve stdin, terminal
behavior, exit status, and repeated-signal handling; background shell commands
can otherwise receive different input semantics.

SIGKILL cannot be trapped. Python's `process.kill()` and `subprocess.run()`
timeout cleanup use it on POSIX. A wrapper trap therefore cannot fix those
paths or other wrappers. Replacing the wrapper with `exec` simplifies PID
ownership but loses its after-the-fact diagnostics. Native SSH is suitable for
internal calls that do not need those diagnostics, provided shared connection
lifetime is handled explicitly.

Do not kill Lima's shared SSH master as per-request cleanup. Closing a local
transport also does not prove its guest command stopped: retain the guest-side
ownership protocol or container identity checks that establish that separately.

== Direct proxy forwarding remains a separate change

Native SSH can forward a private host Unix socket to a guest socket using
`-L local_socket:remote_socket`. Disposable tests against a guest Python server
inside an owned Docker volume preserved request half-close and response EOF;
terminating native SSH delivered EOF to the open guest connection. The probe
used a dedicated connection with connection sharing and persistence disabled.

This establishes transport feasibility, not complete proxy parity or a speedup.
One fresh connection took 0.308 seconds without a container-forwarding comparison.
Existing proxy socket paths measured 96–99 bytes; longer guest paths can exceed
Unix-socket address capacity. A replacement still needs ownership checks,
private listener cleanup, path-length handling, and real proxy integration tests.
Disconnecting the transport does not cancel a command already accepted by the
JJ server. Command cancellation requires a separate protocol design.

== Implementation order and acceptance

First repair the credential transport's bounded cleanup and the monitor group's
leader-independent drain. Then migrate noninteractive runtime transports to the
same ownership rule. Treat wrapper cooperation and interactive job control as
separate changes; do not couple this repair to replacing proxy forwarding.

Before accepting each migrated caller, exercise:

- a wrapper that exits while a child retains stdout or stderr;
- a live child ignoring SIGTERM after its leader exits;
- timeout and cancellation before readiness, plus repeated shutdown signals;
- successful completion, original failure status, and secret-safe diagnostics;
- an unrelated process outside the owned group surviving cleanup;
- existing remote cleanup and terminal behavior on a disposable VM where needed.

Negative controls must fail when group draining is replaced with PID-only killing
or when escalation depends solely on leader exit. Promote the local probes to
subsystem-owned fixtures during implementation; do not depend on ignored files.
The disposable review probes were not retained as supported tests. Their reported
survivors were removed, and temporary Docker volumes were deleted.
