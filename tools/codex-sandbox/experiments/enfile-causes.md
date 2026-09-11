# ENFILE causes — follow-up on 2026-09-12

## Strongest explanation: independent caches share one limit

The [initial investigation](enfile.md) established inode retention and a scoped
reclamation mechanism. Further evidence changes the priority: account for idle
VMs and the aggregate host budget before building a reclamation controller.

At 10:04 UTC, macOS used 236,789 of 245,760 file entries. Docker's VZ process held
98,205 descriptors, Podman's 96,679, and the older nerdctl VM's 27,426.
Each was below `kern.maxfilesperproc=122880`; together they accounted for most
of the host table. Per-process descriptor counts are not an exact, atomic
decomposition of that table, and one other VZ process denied inspection.

An Apple engineer described VirtioFS retaining inode descriptors for performance
and recycling them near the process limit. Apple subsequently reported changes
in macOS 15. This supports an aggregate-budget failure hypothesis: multiple VMs
can exhaust the host before any individual cache reaches its recycling boundary.
The current framework's exact threshold was not measured; the host is too close
to exhaustion for that test. [Apple's discussion](https://developer.apple.com/forums/thread/741572).

Both the default Podman VM (rootful and rootless stores) and nerdctl VM reported
no running containers. They nevertheless retained 124,105 descriptors together,
about half the entire host allowance. Empty container listings do not prove the
absence of other guest work, so neither VM was stopped. Keeping a rollback VM
running preserves its cache as well as its images; cold standby would preserve
the images without retaining the live VM's descriptors.

## What grows the cache

Three further runs used the same idle Ubuntu 6.8 Docker fixture, fresh owned
512-file corpora, and cgroups removed afterward. The host guard required at least
4,096 free entries before another scan. Production VMs were only inspected.

| Hypothesis or operation | Observed result |
| --- | --- |
| Repeated scans leak more descriptors | A second stat of the same 512 files added none; a second reader cgroup also added none. |
| Merely listing every name opens every file | `os.listdir()` added 24 descriptors; statting every file after reclaim added 513, including the directory. |
| Low application `nofile` prevents the problem | With a hard/soft limit of 32, sequential stat/read still succeeded and retained 512 file descriptors in the host VM process. |
| Hardlink aliases multiply host descriptors | 512 names for one inode added two descriptors on stat and two more on read, versus roughly 512 for distinct inodes. |
| Guest deletion releases retained files | Deleting the 512 files inside the guest released all 512 descriptors. |
| Host deletion immediately releases them | Host deletion left all 512 after two seconds; checking those missing paths inside the guest then released all 512. |
| Reclaim the most recent reader | Reclaiming the second reader's cgroup discarded 2 MiB of cached data but released no descriptors; reclaiming the original inode owner's cgroup released 512. |

The evidence points to the number of distinct cached inodes and their ownership,
rather than an unbounded leak on repeated access to the same files. Metadata-only
stat retained about 566 KB of reclaimable slab for 512 files with zero file-data
cache. A guest can therefore retain many host descriptors without nearing its
own memory limit; more guest RAM is not a remedy for this resource mismatch.

The listing result may involve FUSE's adaptive `READDIRPLUS`, which increases
lookup references unlike ordinary `READDIR`. This is a mechanism hypothesis,
not a captured protocol trace: the fixture kernel exposed no FUSE tracepoints.
[FUSE operation contract](https://libfuse.github.io/doxygen/structfuse__lowlevel__ops.html).
Do not generalize the `os.listdir()` result to colorized listings, metadata
walkers, or search commands that stat/read entries.

Cgroup cache ownership can outlive the process that first populated it and can
differ from the current reader. This agrees with the kernel's documented
first-allocation accounting and explains why a per-session cleanup hook can
miss the relevant cache. A common ancestor is a stronger reclamation boundary.
[Kernel memory ownership](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-ownership).

## Alternatives checked

A fresh systematic sample included native inode numbers and link counts, then
compared each sampled path on the host without scanning shared trees:

- Docker: 2,009 of 2,046 samples still matched the current inode; 35 paths were
  missing and two had been replaced. Twenty sampled vnodes had zero links.
- Podman: 2,011 of 2,015 matched; one path was missing and three were replaced.

Deleted or replaced files contribute, but do not dominate these samples. Failed
builds leaving live artifact trees are a more plausible source of retained inode
cardinality than deleted-file leaks. The earlier path sample was dominated by
Paracress build outputs, test installations, worktrees, and Git metadata; it does
not identify which command originally populated each cache.

Neither guest exposed an `updatedb` timer or `/etc/updatedb.conf`. This weakens
the background locate-indexer hypothesis without excluding every scanner.
The launcher's `source_view.py` stages only necessary ancestors and runs on the
host; its implementation is not a recursive guest walk of every source subtree.

## Revised priorities

1. Confirm unused VMs have no other guest work, then use cold standby for
   rollback engines. This addresses a measured 124,105-descriptor contributor
   without changing active workload semantics. Keep the existing images/state.
2. Reduce distinct host-backed artifact inodes exposed to routine work: put
   disposable build/test caches on guest storage, prune stale live artifact
   trees through their owning tools, or exclude them from unnecessary scans.
   Narrowing a home share alone will not help if the active repository still
   contains and scans the same large artifact trees.
3. For concurrent engines that must remain active, enforce an aggregate host
   budget. Scoped guest reclamation is a demonstrated mechanism, but needs
   active-workload latency/durability tests and the correct ancestor cgroup.
   Raising application `ulimit` does not address the measured owner; raising
   the global table supplies headroom without constraining cache growth.

The per-process versus global recycling mismatch is suitable for a focused
upstream report, but has not been proven by deliberately exhausting this host.
A disposable host would permit varying the number of VMs at a fixed total inode
count to separate aggregate pressure from a single-VM recycling defect.

## Evidence and limits

Raw results: `/private/tmp/enfile-causes.jsonl`,
`/private/tmp/enfile-alias-unique.jsonl`, and
`/private/tmp/enfile-alias-hardlinks.jsonl`, with corresponding `.err` files.
Drivers: `enfile-causes-{host,guest}.py` and `enfile-alias-{host,guest}.py` in
`/private/tmp`. Native samples are `enfile-{docker,podman}-inodes.tsv`, produced
by `enfile-inode-sample.c` using installed SDK structures.
All three runs exited zero; their owned corpora and cgroups were removed.
These temporary artifacts are not durable regression tests. The experiments
changed no production limits, caches, services, or VM lifecycle.

## Subsequent shutdown and reclamation options

At jyn's request, on 2026-09-12, stopped `podman-machine-default` and the
nerdctl Lima instances `sandbox-host` and `sandbox-host-launch-20260908`.
Both Docker VMs remained running. Between 10:09:56 and 10:10:52 UTC,
`kern.num_files` fell from 236,742 to 112,234 (96% to 46% of 245,760).
The production Docker VZ process retained 98,205 descriptors in both samples.
The 124,508-entry reduction is from sequential host samples, not an isolated
accounting of the stopped processes.

Three possible reclamation policies remain:

| Policy | Benefit | Limitation |
| --- | --- | --- |
| Reclaim after the last session exits | Simple lifecycle trigger | Cannot protect long active sessions; repeated sessions lose warm caches. Idle detection must cover all repositories. |
| Guest memory budget | Kernel-managed reclamation | Memory bytes do not bound inode count or host descriptors. A low budget also pressures useful anonymous memory and file data. |
| Reclaim under measured host pressure | Responds to the scarce resource | Requires host-wide and per-VM measurements, hysteresis, bounded attempts, and one coordinator per VM. |

Prefer measured host pressure if automatic reclamation becomes necessary.
First validate an explicit, bounded reclamation operation under active reads,
writes, and container exit; the shutdown removed the immediate pressure.
Do not enable routine cache flushing on the evidence collected so far.

Production container cgroups are under `user@501.service/user.slice`, while
the Docker daemon is under `user@501.service/app.slice/docker.service`.
Reclaiming the daemon alone therefore misses container-owned caches.
The common ancestor `user@501.service` has a guest-user-owned `memory.reclaim`
file; it is a candidate boundary, not yet a validated production policy.
It also includes other services belonging to that guest user. Derive the user
identity at runtime rather than hard-coding UID 501.

Judge reclamation by actual host descriptors released, including partial
reclamation, rather than assuming requested bytes imply a descriptor reduction.
Stop unsuccessful attempts instead of repeatedly evicting useful pages.
