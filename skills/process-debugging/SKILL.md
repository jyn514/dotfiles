---
name: process-debugging
description: Diagnose Linux native-process crashes, hangs, spins, and missing debugger symbols using GDB, core dumps, and bounded syscall traces. Use when a live process or crash artifact needs stack-level investigation, ptrace fails, or debuginfod does not load matching symbols. Not for ordinary application bug fixes, managed-runtime debugging, general benchmarking, or performance optimization.
---

# Process debugging

Own process inspection and debugger setup, not permission to restart services or modify live execution.
For latency measurements and sampling scope, use `performance-investigation` when its triggers apply.

## Identify the process and boundary

Resolve the process serving the failing request, not just the installed command or its launcher.
Record its PID, executable, runtime version, and relevant process tree or cgroup.
Recheck identity before attaching or signaling; a PID can disappear or be reused.
For an unresponsive client, distinguish transport failure from an unresponsive server with a bounded request to each endpoint.

Inspect the owning project's recovery guidance before recommending restart or termination.
Preserve the failing process long enough to collect evidence when recovery would erase the diagnosis.
If permission prevents inspection, report the unavailable evidence rather than inferring process state from that error.

## Make symbols work before collecting stacks

Check the debugger's actual `DEBUGINFOD_URLS`, its debuginfod setting, and the package provenance of each relevant executable or library.
Read the host's `/etc/debuginfod/*.urls` when available; shared shell overrides and sudo filtering can change the effective URLs.
Match symbols by ELF build ID, not package version alone.
Distribution rebuilds can need their own server even when the version matches upstream.
For example, this Arch/CachyOS host provides both `https://debuginfod.archlinux.org` and `https://debuginfod.cachyos.org`.
Do not carry those URLs to another distribution without checking its installed configuration.

Use `debuginfod-find debuginfo /path/to/library` to test an actual lookup.
Use an isolated `DEBUGINFOD_CACHE_PATH` for comparison with another server; cached misses can hide a corrected URL.
Bound network lookups and distinguish unavailable symbols from a network failure.
An HTTP HEAD error does not prove symbols are absent; test with the debuginfod client.

Enable downloads with GDB `-iex`, before loading the executable, libraries, or attachment.
`-ex 'set debuginfod enabled on'` runs too late for the initial load.
In batch mode, GDB's default `ask` declines downloads because input is not a terminal.
Pass the verified URLs with `-iex 'set debuginfod urls ...'` when inherited or privileged environments are uncertain.
Confirm GDB resolves a source line or local type; a successful download alone does not prove it loaded the symbols.

For a privileged backtrace handoff, set `pid` to the verified target and `debug_urls` to the verified space-separated URLs:

```sh
sudo gdb -q -n -batch \
  -iex "set debuginfod urls $debug_urls" \
  -iex 'set debuginfod enabled on' \
  -ex 'thread apply all bt full' \
  -p "$pid"
```

The user runs this command when the agent cannot run sudo on the host.
Omit sudo when the available execution context already permits attachment.
For a core dump, load the matching executable and core instead of attaching.

## Inspect before recovering

Debugger attachment pauses the target and changes timing, even when it only reads memory.
Start with a stack snapshot or bounded syscall sample that distinguishes the competing diagnoses.
If ptrace fails, distinguish sandbox restrictions, ownership, and kernel ptrace policy before proposing privilege changes.
Use the authorized execution context or prepare a privileged handoff; do not disable host-wide ptrace restrictions just to inspect one process.

Read surrounding source at the matching revision before explaining a sampled function as the cause.
One stack is a location sample, not proof of an infinite loop or deadlock.
Corroborate it with repeated stacks, CPU-time deltas, syscall repetition, or a reproducer as needed.
If symbols remain unavailable, a function-entry breakpoint can expose arguments through the verified architecture's calling convention.
Do not read argument registers from an arbitrary instruction as though it were function entry.

Distinguish inspection from GDB commands that change execution: `return`, `jump`, memory writes, inferior function calls, and injected signals.
State the proposed live modification and its consequences before using it, and obtain authority if the session has not already granted it.
A normal stack trace must not silently become a recovery script.
When authorized recovery uses catchpoints or breakpoints, account for debugger signal handling, detachment, and the process state after interruption.
Confirm the server handles requests after recovery; an accepted signal or debugger exit does not establish recovery.

Report the observed mechanism, source-based explanation, remaining uncertainty, and any recovery effects separately.
Preserve raw evidence and review environments and full backtraces for secrets before sharing them externally.
