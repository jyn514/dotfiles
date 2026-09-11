# Own proxy connections through Lima

Findings from 2026-09-11. The disposable forwarding implementations were removed
after adopting session-owned OpenSSH forwards. The maintained behavior is specified
in the [proxy contract](../proxy-design.typ); setup and migration are in
[Lima-Docker](docker.md).

## Why this transport

Docker exposes no operation to kill one exec instance. Terminating the host
`docker exec` client does not establish termination of its remote process.
The previous backend therefore created a forwarding container for each request,
using container removal as its cancellation boundary. That added startup cost.

Lima 1.2.1, installed during investigation, cannot register Unix-socket forwards
through a live configuration API: `limactl edit` rejects running instances,
`limactl tunnel` supports SOCKS only, and the host-agent API exposes only info.
Source inspection of 2.0.3 found the same limitations. Unix-socket forwards use
OpenSSH control operations even when dynamic TCP forwarding uses gRPC.
Sources: [edit](https://github.com/lima-vm/lima/blob/v2.0.3/cmd/limactl/edit.go),
[host-agent API](https://github.com/lima-vm/lima/blob/v2.0.3/pkg/hostagent/api/server/server.go),
[forwarding](https://github.com/lima-vm/lima/blob/v2.0.3/pkg/hostagent/hostagent.go).

The backend now uses that existing SSH master directly: one `-O forward`
registration per cached proxy, cancelled with `-O cancel` during proxy cleanup.
Each request owns only its connection. The launcher retains responsibility for
identity checks, private listener paths, short guest aliases, and recovery state.
It never kills Lima's master to cancel a request.

## Historical measurements

The initial experiment compared a per-request forwarding container with a fresh,
dedicated native SSH tunnel, with sharing and persistence disabled. Each sample
started a fresh Python router, performed real session/runtime/repository/image
checks, ran warm `jj status`, and finished response handling, router exit, and
local process-group cleanup. Setup and warmup were excluded; five pairs per path
length alternated transport order against the same repository and proxy.

| Guest socket path | Container median | Dedicated SSH median |
| --- | ---: | ---: |
| 72 bytes | 0.826 s | 0.508 s |
| 169 bytes, temporary short alias | 0.985 s | 0.701 s |

The image was `jj-proxy:ac6dcadf30c8a10bcbf7265c610b0b28557b2909`.
These aggregates were checked against the local `target/forwarding-probe.log`
before removal of the experimental code; that ignored log is not a durable test
artifact. Host load varied. These are neither Pi startup measurements nor
measurements of the adopted shared-master implementation.

## Compatibility and lifecycle evidence

The JJ experiment preserved framed success, failed revision lookup, and policy
rejection responses, including request half-close and response EOF. It rejected
wrong proxy and volume owners. A partial-request cancellation released the
sequential server for a subsequent request; owned resources were cleaned up.

Trailing bytes exposed a transport difference: both paths returned the same
107-byte rejection frame with application exit 2, but the container client exited
125 after a socket reset and SSH exited 0. Stream completion cannot establish
application success. The adopted contract requires command-specific callers to
validate response framing and application status.

The initial fixture manually created a JJ proxy. It did not exercise manifest
builders or declared mounts, and its fixed 130-second timeout was not a generic
protocol requirement. The adopted transport has no command-specific timeout.

The maintained `tests/docker_forwarding_integration.py` subsequently passed
against a disposable repository with Paracress's bug manifest and cached image:
declared entrypoint/workdir/network and proxy/agent mounts, valid and malformed
response-byte comparisons, TERM/KILL after sending a partial request, long guest
paths, old/incomplete/stale cache rejection, and repeated stale-listener cleanup.
It uses prepared images, so it does not validate the repository's image builder.
Seven recovery unit tests passed; an in-memory mutation confirmed the live-listener
test rejects ignoring a failed cancellation. Existing proxy and Docker runtime
suites passed 59 and 20 tests respectively.

Review caught three gaps before adoption: reuse of caches without listeners,
cleanup after master replacement, and assuming the guest shares the checkout.
The implementation rejects unusable caches, removes stale listeners only after
connection refusal when cancellation fails, and sends the separate guest helper
on SSH stdin. Final independent review found no remaining blocker.

## Remaining limits

Disconnecting does not promise cancellation of a command already accepted by the
server. Arbitrary host crashes at every publication boundary and full interactive
Pi startup were not retested in this change. Per-request volume inspection still
uses the Docker CLI; its remaining cost has not been isolated. Restarting Lima's
master invalidates existing listeners and requires session exit and relaunch.
