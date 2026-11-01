Implement the task described on stdin. You can re-read the packet at target/flower-worker/packet.md. Return only the schema-conforming final report.

<stdin>
# Flower Orchestrator Worker Packet

Use $orchestrator-worker.

Worker packet:
- Re-read this packet at: target/flower-worker/packet.md

Task id: template
Covered issue ids: 6df95a2

Allowed ownership paths:
- src/flower/page/source.clj
- test/flower/page/source_test.clj

Forbidden and protected paths:
- .agent-git-bug
- .git
- .jj
- target/flower-worker
- target/lint-tools

Acceptance criteria and issue text available from the plan:
- {:id "6df95a2"}

Gate expectations:
- orchestrator ownership check
- bb lint --changed
- focused tests reported by worker when relevant

Final report handling:
- Return the final JSON report as your last message.
- The orchestrator will save that final message to: /task/report.json
</stdin>