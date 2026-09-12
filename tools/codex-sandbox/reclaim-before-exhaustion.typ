#set document(title: "Reclaim before exhaustion")
#set page(margin: 1in)
#set text(size: 10.5pt)

= Reclaim before exhaustion

*Status:* Implemented and fixture-tested, 2026-09-12. New provisioning enables
reclamation after its audit; existing VM generations are unchanged.
The measured settings and replay limits are in `experiments/reclaim-timer.md`.
Paths are relative to `tools/codex-sandbox/`.

== Design

Keep a persistent container parent and a guest systemd timer that starts a
bounded reclaim job. Systemd owns scheduling and execution; no host polling,
launchd service, SSH orchestration, or custom controller is needed.

This is cache-pressure mitigation. If active work retains or creates host
descriptors faster than reclaim releases them, ENFILE remains possible.
The timer cannot detect that host pressure or warn about ineffective descriptor
reclamation. It can report job failures. Periodic reclaim may evict useful
caches even when the host has ample headroom; measure that cost before rollout.

== Three components

+ *Persistent parent.* Set the owned Docker daemon's default cgroup parent to
  `sandbox.slice`, retaining individual container scopes. Make Docker's user
  service require and start the slice, while keeping the daemon outside it.
  The slice must survive the final container exit while Docker remains active;
  prove that lifetime in the fixture. Do not add a keepalive process to the
  parent or manually migrate systemd-managed processes.
+ *Guest job.* Install a fixed systemd user oneshot service outside the slice.
  Its helper writes one configured byte amount to the parent's
  `memory.reclaim`, reports completion or partial progress, and exits.
  Use `Type=oneshot`, `Restart=no`, `RemainAfterExit=no`, and
  `KillMode=control-group`. Set finite `TimeoutStartSec` and `TimeoutStopSec`
  explicitly: oneshots have no startup timeout by default. A deadline bounds
  the manager's wait, not the lifetime of uninterruptible kernel work.
  Before opening `memory.reclaim`, the helper takes a nonblocking exclusive
  `flock` on a fixed file in the guest user's runtime directory and holds the
  descriptor until exit. Never unlink or replace that file within a boot;
  do not use a service runtime directory removed on service stop. The helper
  performs the write itself without spawning children. A surviving worker
  retains the lock, so a new invocation reports busy and exits without reclaim.
+ *Guest timer.* Activate the same service with `OnActiveSec` for the first
  run and `OnUnitInactiveSec` for subsequent runs. The interval begins after
  the previous job deactivates, avoiding immediate retries after slow reclaim.
  Set `AccuracySec` deliberately when calibrating cadence; its installed
  default is one minute. Use monotonic scheduling without wakeup or calendar
  catch-up. No retry loop runs inside the helper.

Timer semantics were checked against the guest's installed systemd 255 manual,
`/usr/share/man/man5/systemd.timer.5.gz`: an already-active service is not
restarted by its timer. Verify timeout/failure rearming in the fixture as well
as successful repetition.

The installed engine uses systemd and cgroup v2. A daemon-wide parent covers
helper creation paths that bypass `workload_argv()`; explicit per-container
parents can still override it.
#link("https://docs.docker.com/reference/cli/dockerd/#default-cgroup-parent")[Docker parent configuration].

== Running containers and failure

Containers continue during reclaim. Evicted cache may be loaded again, so
measure workload slowdown as well as descriptors released. Reclamation does
not delete files or establish durability. Open references, dirty/writeback
state, or caches charged outside the parent can prevent descriptor release.

A short reclaim result may return `EAGAIN`; judge effectiveness by actual host
descriptor counts, not requested bytes. Existing probes released 512 retained
descriptors by reclaiming their owning ancestor, including after child removal;
a later reader's sibling cgroup released pages but no descriptors.
See `experiments/enfile.md` and `experiments/enfile-causes.md`.

Treat `EAGAIN` as an expected partial/empty result, not a reason for an immediate
retry or a warning every tick. Report actual I/O/configuration errors and
timeouts in the guest journal. Existing status/doctor should show timer state,
next activation, and last job result; successful execution must not be labelled
successful host-pressure recovery. Host sampling remains a diagnostic/test tool.

The timer runs while Docker is active, including when no containers remain:
retired containers can still own cached inodes. Use these dependency directions:

- Docker has `Requires=sandbox.slice` and `After=sandbox.slice`; it stays in
  its existing service cgroup. It does not require the timer or reclaim job.
- The timer has `WantedBy=docker.service` in its install section and
  `BindsTo=docker.service`, `After=docker.service`, and `PartOf=docker.service`.
  Enabling creates Docker's weak wants link; stopping/failing Docker stops the
  timer, and restarting Docker restarts an enabled timer.
  Set `DefaultDependencies=no`: the default `Before=timers.target` would cycle
  through `basic.target` back to Docker during boot. Retain explicit
  `Conflicts=shutdown.target` and `Before=shutdown.target`; Docker supplies
  startup ordering. Verify the complete transaction with `systemd-analyze`.
- The job has `Requisite=docker.service`, `After=docker.service`, and
  `PartOf=docker.service`, plus `After=sandbox.slice`. Manual reclaim fails
  when Docker is inactive instead of starting it. Its restart/stop actions
  follow Docker; normal repetitions belong solely to the timer.

Disable reclamation by disabling and stopping the timer, then stopping the job.
Wait for the helper to exit; report a remaining lock holder as unsettled even
if the unit is failed. Do not remove its lock file. Removing the timer's enable
link keeps it disabled across Docker restart and guest reboot; do not add a
static Docker `Wants=` entry or silently re-enable it in start/setup repair.
First provisioning enables it after validation; explicit enable restores the
link and starts the timer while Docker is running. Status distinguishes
operator-disabled from failed; doctor accepts the disabled state.
Fixture tests must cover these transactions, including Docker failure and
automatic service restart, not just explicit stop/start. A guest timer cannot
start a stopped VM. Launch, cancellation, and cleanup retain existing behavior.

No synchronous startup handshake or per-command policy audit is added.
Preserve revision `6b3e4689`: configuration audits belong to setup/doctor.
Use one named service for timer and manual reclaim. Systemd serializes normal
activation; the helper's lock covers surviving workers after failed termination.
No supervisor or state journal is needed.

== Implementation and validation

+ *Placement and active reclaim.* Use
  `tests/docker_reclaim_integration.py` in an owned fixture. Cover workload and
  helper placement, parent survival after exit, retired-child charges,
  concurrent reads/writes/fsync, and files deliberately kept open. In this first
  fixture, separately measure descriptor retention/reclaim for ordinary
  containers, helper containers, and the built-in BuildKit/daemon path. Record
  actual cgroup membership and which ancestor releases each corpus. If the
  dominant measured source lies outside the parent, stop before timer tuning
  and revisit ownership. Verify correctness and responsive cancellation;
  do not deliberately exhaust the host.
+ *Provisioning ownership.* `lima/docker/daemon.json`,
  `lima/docker/configure-user.py`, `lima/docker/policy.py`, and the source
  snapshot in `lima/docker_host.py` own installation and validation. Keep
  slice/timer/service definitions and the helper in separate files under
  `lima/docker/`. Guest/runtime tests protect installed configuration,
  readiness, and old-state handling.
+ *Validate scheduling and cost.* Test first and repeated activation, partial
  reclaim, manual activation during a running job, timeouts/stuck workers,
  Docker stop/restart, and timer disable while reclaim is active. Simulate a
  surviving lock holder independently of unit state; a replacement must issue
  no reclaim write until that holder exits. Calibrate
  batch size, interval, timer accuracy, and deadlines with alternating
  real-workload baseline/timer trials using comparable caches and including
  artifact finalization. Measure host descriptors externally, including growth
  between ticks, and repeated warm-workload latency. Use the acceptance gate
  below. The selected values are 32 MiB per batch, a 30-second interval,
  1-second accuracy, and 10-second startup / 5-second stop deadlines.
+ *Roll out explicitly.* Existing provisioning snapshots are immutable; use
  a fresh VM/state generation first, then a drained migration. Recreate old
  containers under the parent and use a scheduled VM restart to clear earlier
  cache ownership. `lima/docker.md`, `lima/README.md`, and command help document
  setup, status, manual reclaim, and timer/job shutdown behavior.
  Reclamation never kills or pauses containers.

Process migration does not transfer earlier memory charges.
#link("https://docs.kernel.org/admin-guide/cgroup-v2.html")[Kernel cgroup v2 reference].

== Acceptance gate

These are the release criteria fixed before the recorded replay, not guarantees
for other workloads. Fix the workload manifest before tuning; do not weaken
the criteria to fit a result.

- *Workload:* Paracress build/test replay, chosen because its artifacts dominate
  the incident's path samples. Before trials, record the revision, exact build
  and test argv, toolchain, concurrency, artifact finalization commands, and
  warm-cache preparation in `experiments/`. The incident did not identify the
  original cache-populating command; reconstruct a representative replay and
  label it as such. An incomplete manifest blocks calibration.
- *Runs:* At least three alternating baseline/timer pairs, each with ten
  consecutive replay cycles and the same initial cache preparation and declared
  background VMs. Sample global and owned-VZ descriptor counts externally at
  100 ms intervals, also recording sampling gaps and unit events. Report sampled
  peaks as sampled, not a proof that no shorter spike occurred.
- *Headroom:* Every valid timer-run sample retains at least 20% of both the
  host global file-table limit and the VZ process's applicable descriptor limit.
  Abort a trial if either reserve falls below 10%; an aborted timer trial fails.
  Identify limits and record starting headroom before each run. Busy host
  baselines that already miss the target require a quieter test window.
- *Cost and correctness:* The median of the three timer-run total durations is
  at most 10% above the baseline median; no paired total exceeds 20% slowdown.
  Finalized artifacts and test results must match the baseline's expected
  results. Require zero unexpected worker overlap, lost timer rearming, or
  unrecovered shutdown jobs in lifecycle fixtures.

Keep automatic reclamation disabled until ownership, lifecycle, and replay
gates pass. Publish the chosen batch size, interval, accuracy, and deadlines
with the results. If adequate headroom requires unacceptable cache cost or a
hard stop, return to the policy decision with evidence; neither automatic
freezing nor a broader reclaim target is implicit implementation work.
