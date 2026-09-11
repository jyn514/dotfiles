# ENFILE investigation — 2026-09-12

## Finding

The observed pressure is host-side VirtioFS inode retention, shared by the
Docker and Podman VMs. Guest process file limits do not describe that pressure.
An owned cgroup experiment released retained host descriptors through
`memory.reclaim`, including after the worker cgroup was removed. This is a
candidate for bounded recovery, not a validated production pressure controller.

## Live baseline

Read-only samples at 09:45 UTC on macOS 26.6.2 recorded 238,102–238,103 host file
entries against `kern.maxfiles=245760`; `kern.maxfilesperproc=122880`.
The [libproc sampler](file_pressure.py) counted the complete descriptor lists.
VM disk paths from `lsof -a -p PID -d 0-24` established ownership:

| VM | Host descriptors | Guest allocated files |
| --- | ---: | ---: |
| `sandbox-host-docker` | 98,205 | 1,856 |
| `podman-machine-default` | 96,679 | 1,352 |
| `sandbox-host` (nerdctl) | 27,426 | not sampled |
| `sandbox-host-docker-gaps-20260910` (idle fixture) | 4,615 | 1,344 |
| `sandbox-host-launch-20260908` (older fixture) | 351 | not sampled |

These sequential observations are not an atomic accounting total. A sixth VZ
process denied inspection and is not counted as zero. Docker had about 3.0 GB
of available guest memory, Podman 14.2 GB; both reported zero recent memory PSI.
Neither had swap. The host was close to its file-table limit while the guests
had reclaimable memory and no contemporaneous memory-pressure signal.

A separate native helper sampled every 48th descriptor and resolved vnode paths
through `proc_pidfdinfo(PROC_PIDFDVNODEPATHINFO)`, using the installed SDK structs.
Of 2,046 Docker vnode samples, 1,486 were under Paracress's `target/` and 206 under
its `.git/`. Of 2,015 Podman samples, 841 were under `target/`, 745 under
`editors/` (743 in `.vscode-test`), and 245 under `ignored/`.
This systematic sample identifies dominant observed paths; it is not a random
sample or an exact count of every subtree. No shared-tree traversal was needed.

## Bounded reclamation experiment

The idle Docker fixture ran Ubuntu kernel 6.8.0-63-generic with cgroup v2 and
`vfs_cache_pressure=100`. Its Docker container listing was empty before each run.
Each run created 512 owned host files of 4 KiB, then used a fresh guest cgroup
to stat or read them. The reader closed every file and exited before sampling.
The host driver refused another scan below 4,096 available host file entries.
No production VM cache, limit, service, or workload was changed.

| Operation | Fixture host descriptors before → after |
| --- | --- |
| First run: reclaim after metadata-only stat | 5,151 → 4,639 |
| First run: reclaim after reading all file data | 5,152 → 4,640 |
| First run: `POSIX_FADV_DONTNEED` on all files | 5,153 → 5,153 |
| First run: reclaim after that eviction | 5,153 → 4,641 |
| Second run: remove exited worker cgroup | 5,155 → 5,155 |
| Second run: reclaim through its surviving parent | 5,155 → 4,643 |

Every successful reclamation released exactly 512 host descriptors. Evicting
file data reduced the cgroup's reported file cache from 2 MiB to zero but left
all 512 descriptors. Removing the worker cgroup also left them. This separates
cached inode lifetime from open application files and cached file data.
The fixture baseline varied slightly between operations; production Docker and
Podman descriptor counts stayed unchanged at the sampled boundaries.

The experiment requested 32 MiB through `memory.reclaim`. Calls returned `EAGAIN`
because less memory was available, even though host descriptors were released.
The kernel documents this partial-success behavior; recovery must measure its
result instead of treating that errno as proof that nothing happened.
[Kernel cgroup documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html).
The measured writes took approximately 0.6–1.4 ms, excluding SSH, sampling,
subsequent cache misses, and sustained workload effects.

All owned corpora and cgroups were removed. Temporary evidence remains in
`/private/tmp/enfile-reclaim-probe.jsonl`,
`/private/tmp/enfile-retired-cgroup-probe.jsonl`, and the corresponding `.err`
files. The second run's drivers are `/private/tmp/enfile-host-probe.py` and
`/private/tmp/enfile-guest-probe.py`; the first run used the cgroup directly,
before the driver was extended to test a retired child. Native path evidence
is in `/private/tmp/enfile-{docker,podman}-paths.tsv` and
`/private/tmp/enfile-path-sample.c`. These temporary files are not durable tests.

## Decision and next validation

The [follow-up](enfile-causes.md) puts unused VM lifecycle and the aggregate
host budget ahead of a new controller: Podman and nerdctl retained about half
the host allowance despite having no running containers.
For VMs that must remain active, investigate host-pressure-triggered, bounded
cgroup reclamation before periodic whole-VM cache flushing or a file-limit
increase. The trigger must observe the
host-wide table and per-VM descriptors: a guest can retain many host files while
having ample memory. Select the owning ancestor cgroup, since exited containers
can leave cached inodes after their child cgroups disappear. Verify that
reclamation releases host entries, and stop or report ineffective recovery.

Increasing `vfs_cache_pressure` changes the relative preference for inode/dentry
reclaim; it does not establish a host descriptor budget. Large values can also
increase reclaim cost. [Kernel VM documentation](https://docs.kernel.org/admin-guide/sysctl/vm.html#vfs-cache-pressure).
A larger host file-table limit supplies headroom but leaves the demonstrated
retention mechanism unchanged. Moving disposable build caches to guest storage
would address many sampled paths, but repository metadata and ordinary source
scans still require a general pressure response.

Before implementing a controller, repeat the probe with active readers/writers,
shared files charged to different cgroups, and deleted container cgroups under
the real rootless service hierarchy. Check data durability, interactive latency,
reclaim amount versus released descriptors, and repeated scans with Podman
coexisting. The 512-file experiment does not establish those properties.
