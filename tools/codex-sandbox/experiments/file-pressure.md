# Measure VirtioFS host file pressure

Run from the checkout on macOS, outside process-inspection sandbox restrictions:

```sh
python3 tools/codex-sandbox/experiments/file_pressure.py --samples 30 --interval 2 > /private/tmp/file-pressure.jsonl
```

Each JSON line contains host usage/limits and descriptor counts for visible
Virtualization.framework processes. Samples are sequential, not an atomic
accounting snapshot. Process-inspection failures are reported as errors rather
than zero counts. Match PIDs to VMs separately; the tool does not infer ownership.

The sampler uses libproc because lsof undercounted a roughly 110,000-descriptor
VM at 10,000 during an ENFILE incident. It does not scan shared trees, flush
caches, change limits or stop workloads. Record guest `/proc/sys/fs/file-nr` and
`/proc/meminfo` alongside it when distinguishing application handles from guest
cache retaining host VirtioFS resources.

Do not start a large-tree stress run with little host headroom. On September 10,
2026, pressure had recurred: host usage was 232,331 of 245,760, Docker's VZ
process held 105,195 descriptors, and its Linux guest reported only 1,984 open
files. The earlier cache flush was temporary relief, not a durable remedy.
