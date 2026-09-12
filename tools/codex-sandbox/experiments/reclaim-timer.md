# Container cache reclamation

Measured 2026-09-12. The implementation uses a persistent `sandbox.slice` and
a systemd timer: 32 MiB per invocation, 30 seconds after deactivation, 1-second
accuracy, and 10-second startup / 5-second stop deadlines. New VM provisioning
enables it after the policy audit. Existing generations retain their snapshots.

## Ownership and lifecycle

The final fresh-VM 512-file corpora produced these host VZ descriptor changes:

| Path | Retained after exit | Released by container parent | Net daemon-ancestor release |
| --- | ---: | ---: | ---: |
| Ordinary container | 517 | 512 | -5 |
| Production helper creation | 592 | 512 | -1 |
| Built-in BuildKit `COPY` | 513 | 0 | 0 |

Negative releases mean a small net increase during that sample interval.
An earlier fixture run released 960 entries through the daemon ancestor,
including older caches; the final fresh-VM batch released none. A byte request
does not guarantee release of a particular inode corpus.
BuildKit remains outside the container parent.
The replay below builds *inside ordinary containers*, not through BuildKit.
These probes establish ownership, not which path dominated the original incident.

The helper fixture used production `start_one_proxy()` creation with a synthetic
offline command and confirmed its placement beneath the parent.
`docker_reclaim_lifecycle.py` passed concurrent reads, replacement writes,
and fsync while files remained open and reclaim ran. The slice survived the
last container exit while Docker remained active.

Native lifecycle checks passed first/repeated activation, manual reclaim,
timeout followed by another activation, Docker stop/start/restart and crash
recovery, and disablement through Docker restart and configuration repair.
An independent process holding the real lock caused replacement work to exit
75 and the real disable operation to fail until the holder exited. Unit tests
also checked that contention performs no reclaim write; removing the lock in
a mutation check made that test fail.

`systemd-analyze --user verify` exposed a boot cycle missed by running-manager
tests: timer → Docker → basic.target → timers.target → timer. The final timer
disables default dependencies and explicitly retains shutdown ordering.
Fresh provisioning, manual reclaim, setup repair, and full VM stop/start then
passed with both enabled and disabled timer states. The timing trials preceded
this ordering correction; batch size, cadence, and worker code did not change.

## Replay fixed before timing

[The manifest](reclaim-replay.json) records the workload and thresholds before
measurement. Source revision observed: `c4675a85811633cee2d4b93c438d812e8f9abdcf`
in Paracress. Only `libs/blush/native/{Cargo.toml,Cargo.lock,build.rs,src,benches}`
and `resources/flower/syntax` were copied into an owned fixture share.
This is a representative native Blush/Syntect replay, not a reconstruction of
the unknown incident command or the full Flower/Graal workload.

The declared Codeberg development-image tag was unavailable. The earlier
fixture image's Rust 1.87 could not build the locked dependencies, which require
1.88. Trials used the declared Rust 1.91 toolchain from the pinned official
image in the manifest. Dependency preparation and initial compilation were
excluded; measured containers used `--network=none` and Cargo `--locked --offline`.

Each trial began with the timer disabled, guest sync and guest cache drop in
the idle disposable VM, then one complete warmup cycle. Ten measured cycles
followed, sequentially running `cargo build` and `cargo test` in new containers,
then syncing and hashing the entire native static library. Cargo used default
parallelism on four guest vCPUs. The production Docker VM and an inaccessible
unrelated VZ process remained running; Podman and nerdctl stayed stopped.

| Pair | Baseline seconds | Timer seconds | Paired slowdown |
| --- | ---: | ---: | ---: |
| 1 | 77.054 | 83.793 | 8.75% |
| 2 | 84.186 | 89.205 | 5.96% |
| 3 | 91.679 | 103.990 | 13.43% |

The ratio of median durations was 1.0596, below 1.10; every pair was below 1.20.
Tests succeeded and every finalized artifact matched SHA-256
`e1c85739cf19c14b0474ba38ce4b2ba69cfef6d229ae3d081654894eea674dad`.
Both modes slowed across successive pairs; alternating trials reduce that
confound but do not make six trials a precise cost estimate.

Source fingerprints:

| File | SHA-256 |
| --- | --- |
| `Cargo.lock` | `c4757d782a01d303330d520ead243476139db89d16c0286119877f81fac14e3f` |
| `Cargo.toml` | `117a20aadef3800f93be28ddc62f0ac3e49f38c2a7e64bb0ceff44f988699c89` |
| `src/lib.rs` | `8497810196e4a89d4775d93e7f37b72e10b4dc4d5adbdefb486defc024e33747` |
| `build.rs` | `c662b587155742244d30eefaf1691304d95aed8f75fa432040f992608b2aaaf1` |

## Sampled headroom

Global capacity was `kern.maxfiles=245760`; the kernel per-process ceiling was
`kern.maxfilesperproc=122880`. The table expresses VZ reserve against that
ceiling, not a directly read process RLIMIT. Reading the latter required
unavailable root authentication. The same fixture process held 10,743
descriptors at collection start; timed timer peaks were at most 1,682.
Assuming its limit did not decrease during the run, that observed lower bound
alone establishes at least 84% per-process reserve, exceeding the 20% gate.

| Pair/mode | Start global / VZ reserve | Minimum global / VZ reserve | Samples | Largest gap |
| --- | --- | --- | ---: | ---: |
| 1 baseline | 55.26% / 98.25% | 55.24% / 98.22% | 744 | 157 ms |
| 1 timer | 55.45% / 98.65% | 55.45% / 98.63% | 804 | 264 ms |
| 2 baseline | 55.66% / 98.68% | 55.64% / 98.65% | 812 | 174 ms |
| 2 timer | 55.67% / 98.66% | 55.66% / 98.65% | 859 | 139 ms |
| 3 baseline | 55.70% / 98.69% | 55.69% / 98.66% | 882 | 369 ms |
| 3 timer | 55.68% / 98.67% | 55.66% / 98.64% | 1003 | 129 ms |

Sampling requested 100 ms spacing and retained timestamps. No sample crossed
the 10% abort threshold; all timer samples exceeded the 20% reserve threshold.
Each timer trial recorded a new activation. Gaps prevent claims about shorter
spikes. Baselines also had ample headroom: this replay establishes the selected
cost and sampled-reserve criteria, not recovery from near-exhaustion or a
host-wide budget for multiple VMs.

Raw local records remain under the disposable fixture's `work/` directory:
`replay-host.jsonl`, `replay-lifecycle.log`, and
`paracress-replay/replay-results.jsonl`. The harnesses are
`tests/reclaim_replay_host.py` and `tests/docker_reclaim_replay.py` (paths relative
to the subsystem). The fixture was `sandbox-host-docker-gaps-20260910`, VZ PID
68048. Final ownership and boot checks used the fresh
`sandbox-host-docker-reclaim-20260912` fixture (ownership VZ PID 4385).
No production VM cache or configuration was changed.
