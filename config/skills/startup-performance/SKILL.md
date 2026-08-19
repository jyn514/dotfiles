---
name: startup-performance
description: Diagnose or improve startup, launch, shell initialization, command-resolution, configuration reload, and runtime-configuration performance. Use for slow startup reports, startup regressions, repeated freshness checks, hidden initialization work, and changes that could affect launch latency.
---

# Startup Performance

Benchmark every process boundary under the user's actual command resolution. Distinguish the agent's inherited environment from the user's interactive shell.

Measure cold and warm paths separately. When explicit restart exists, avoid redundant freshness checks on every launch.

For runtime-configuration regressions, inspect effective state as well as source. Check reload idempotence and hidden callbacks or subprocesses.
