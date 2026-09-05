# Coordination Dialect

Shared shorthand for human-agent and inter-agent coordination. Use these fields when structure improves a request, handoff, or status report; otherwise use English.

## Fields

| Field | Meaning |
| --- | --- |
| `TASK` | Stable name for the work or hypothesis under investigation. |
| `OBS` | Direct observation: something seen, read, or measured. |
| `HYP` | Possible explanation or interpretation. |
| `QUERY` | Request for information. |
| `REQ` | Request that `TARGET` perform an action. |
| `PROP` | Suggested action, not selected for execution. |
| `FORBID` | Prohibited action. |
| `STAT` | Lifecycle state of named work. |
| `RESULT` | Outcome of a named action or tested hypothesis. |
| `ACK` | Receipt only; not acceptance or completion. |
| `CONF` | Confidence in an attached claim. |
| `SCOPE` | Effect boundary. |
| `TARGET` | Agent or role expected to act. |
| `OWNER` | Agent currently responsible for named work. |
| `RET` | Information the response must contain. |
| `RET_TO` | Agent, role, task, or channel that should receive the response. |
| `HOLD` | Pause a named action until a stated condition changes. |
| `PRECOND` | Condition to verify before a named action begins. |
| `SRC` | Origin of an observation or relayed claim. |
| `BASED_ON` | State, revision, or evidence supporting a result. |

`OWNER` and `TARGET` may differ: one holds responsibility; the other is expected to act.

## Canonical values

### Status

| Value | Meaning |
| --- | --- |
| `queued` | Accepted but not started. |
| `working` | In progress. |
| `blocked` | Unable to proceed. |
| `done` | Completed; accompanied by `RESULT`. |
| `failed` | Ran without completing successfully. |
| `cancelled` | Intentionally stopped before completion. |

### Confidence

| Value | Meaning |
| --- | --- |
| `low` | Weak or incomplete support. |
| `medium` | Supported, with material uncertainty. |
| `high` | Strongly supported by available evidence. |

Use numerical confidence only when measured or calibrated.

### Scope

| Value | Meaning |
| --- | --- |
| `readonly` | No intentional mutation. |
| `local` | Effects remain in the owned local environment. |
| `test` | Effects remain in an identified test environment. |
| `prod` | Effects may reach production. |
| `shared` | Effects may alter state visible to other actors. |

Values may be combined: `SCOPE: local, readonly`.

### Prohibitions

| Form | Meaning |
| --- | --- |
| `NO_WRITE` | No intentional filesystem, repository, service, or other state mutation. |
| `NO_EXTERNAL_CONTACT` | No messages, requests, posts, or other outside contact. |
| `NO_NETWORK` | No network access. |

Use `FORBID` when a canonical form is too broad: `FORBID: repository writes`.

## Syntax

Use one field per line for substantial packets. Short packets may separate fields with semicolons.

`CONF`, `SRC`, and `BASED_ON` qualify the most recent `OBS`, `HYP`, or `RESULT` unless they name another claim explicitly. Use distinct `TASK` names when several tasks or hypotheses coexist.

Unknown fields have no protocol meaning and are never implicitly executable.

## Request example

```text
TASK: investigate H2 independently
TARGET: agent 2
OWNER: agent 2
REQ: inspect relevant code and tests
PRECOND: repository state recorded
SCOPE: readonly
NO_WRITE
RET: evidence, conclusion, confidence, and unresolved questions
```

## Result example

```text
TASK: H2 investigation
STAT: done
OBS: three failing tests enter through the same parser branch
SRC: local test output
HYP: that branch mishandles empty values
CONF: high
RESULT: H2 investigation completed; hypothesis supported; no files changed
BASED_ON: repository revision qpvuntsm
```
