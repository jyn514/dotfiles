---
name: unavailable-issue
description: Isolated unavailable-issue evaluation worker with captured Docker-only tools
thinking: medium
tools: task_read,task_edit,task_write,task_bash
extensions: ./tests/behavioral/unavailable_issue/subagent.ts
disabledExtensions: pi-codex-subagents, ./config/pi-agent/pi-extensions/index.ts, ~/.pi/agent/pi-extensions/index.ts
---
Complete the assigned coding task.
