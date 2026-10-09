= Local Pi with a remote sandbox

*Status:* Proposed; remote launch and transport are not implemented.
This contract extends #link("launcher-interface.typ")[execution attachments]
without changing repository policy or the guest isolation boundary.

== Problem and selected behavior

Running the Pi terminal UI over SSH makes each echoed keystroke wait for a
network round trip. On high-latency links, run Pi locally and send structured
tool calls to a sandbox on the selected remote machine. Tool results still incur
network delay; local typing and UI navigation do not.

The human invokes `pi --ssh HOST:/absolute/project/path`. `HOST` is an SSH
configuration alias; the path selects a remote directory, not a local mount.
Require both values and reject ambiguous or malformed targets before startup.
SSH authentication and host-key checking use the human's existing SSH policy.
Both machines require an installed compatible sandbox launcher and Pi build;
this command does not provision or update the remote installation.

For a read, the trace is: local Pi submits one structured `read` request;
SSH carries it to the remote attachment connector; the existing guest worker
reads the guest path and returns its normal result frames. The remote host never
executes a model-supplied shell command outside the guest.

== Ownership and authority

“Frontend host” means the machine running Pi. “Sandbox host” means the remote
machine running the launcher. Existing guest, proxy, repository-policy, and
runtime contracts apply on the sandbox host. Local mode keeps both roles on one
machine.

- The frontend owns Pi UI, conversations, model requests, credentials, ordinary
  subagent processes, and human-created side panes.
- The sandbox host owns repository discovery, normalized policy, accepted-session
  joins, images, guest workers, trusted proxies, locks, and resource cleanup.
- The guest remains the owner of arbitrary model-selected file and process
  execution, including human `!` commands. Remote mode must not use the upstream
  SSH example's direct host filesystem and shell operations.
- Project instructions and skills come from the selected remote guest view.
  Local personal configuration and UI extensions remain frontend-owned. Project
  content cannot install executable extensions on either host.

Remote mode does not copy or mount frontend skills, instructions, or transcripts
into the guest. Guest-readable personal resources use the sandbox host's existing
staging and mounts. The frontend loads remote instructions and skill descriptions
as data, preserving their guest paths; recursive includes resolve remotely.
Local extensions must not advertise frontend file paths as guest-readable.
Guest session-history reads cover only the sandbox host's existing session store,
not the frontend conversation currently being written. Frontend session UI and
bounded session-store tools retain their existing local authority.

The remote launcher is the authority for repository identity, guest cwd, accepted
policy, and resource-path mappings. The frontend receives a validated attachment
description rather than reconstructing these from local paths. Remote host paths
are context, not frontend filesystem paths. Saved session cwd remains historical
context and cannot select another remote repository or host.

Keep frontend model credentials local. Use sandbox-host credentials for its
existing trusted services under their normal admission rules. Do not forward
the frontend SSH agent, credentials, arbitrary sockets, or environment as part
of this feature. Use a launch-owned SSH master with agent forwarding disabled,
rather than reusing an existing master whose forwarding state is unknown.
Peer panes share that master; per-call cancellation cannot terminate it.

== Startup and tool transport

Separate sandbox preparation and supervision from frontend Pi launch. A fixed
remote launcher entrypoint receives the target path as structured data over
stdin, validates it, and starts or joins the ordinary sandbox. Do not interpolate
the project path or tool arguments into a remote shell command.

The remote supervisor returns readiness only after policy admission, worker
readiness, compatibility validation, and guest-view context loading succeed.
The frontend installs guest routing and the returned project context before
accepting prompts. Startup diagnostics use stderr; protocol frames use stdout.
Local Pi starts without requiring a matching local repository checkout.

Reuse the existing guest-tool request and response semantics: tool parameters,
per-call model identity, streamed updates, text and image results, errors, and
completion. One SSH channel per call connects to the attachment's persistent
guest worker. Reuse the launch-owned connection through ControlMaster; do not
share one serial request stream across concurrent tools. The attachment binds every call to its
selected worker until completion; callers cannot select a container or proxy.

The frontend and sandbox host deploy independently. Define a versioned startup
and attachment protocol and reject unsupported versions before exposing tools.
Initially require the same Pi source revision on both ends, including the guest
worker, to preserve tool schemas and result semantics. Report mismatches with
the affected side and required update; do not upgrade automatically. Exact frame
schemas and size limits must be specified before implementation.

== Lifetime, failure, and recovery

The remote supervisor owns workload lifetime; the frontend holds a live
attachment connection. The frontend releases that attachment on normal exit.
The remote owner releases a lost connection after bounded transport-failure
detection and removes the workload only after the final attachment closes. SSH
master persistence is not an attachment lease.

Closing a call channel cancels its guest tool signal. Cancellation, connection
loss, and missing responses can leave a write committed with unknown outcome.
Never replay such calls automatically. Loss of the attachment ends the affected
Pi session and its ordinary children; recovery requires a new CLI launch, using
normal remote startup or accepted-session joining. Preserve the local transcript
and report any outstanding calls with unknown outcomes.

Unavailable guest routing must reject calls rather than use host-local tools.
This strengthens the existing failed-reload limitation for remote mode: remote
support is not complete until failed `/reload` also leaves tools unavailable
instead of restoring frontend-local execution. It does not expand host-extension
authority or promise containment of malicious frontend code.

Follow #link("process-ownership.typ")[process ownership] for local SSH children
and remote cleanup. Per-call shutdown must not kill a shared SSH master.
Remote cleanup uses owner-validated resource identities, not names supplied by
the frontend. Retain remote recovery records when cleanup cannot be verified;
frontend transport exit alone does not establish that guest work stopped.

== Local subagents and side panes

Ordinary subagent Pi processes run on the frontend. Reuse the existing child
manager and `PI_SUBAGENT_PI_BIN` wrapper override; the wrapper inherits the
parent's remote attachment and connector instead of starting a local sandbox.
Children open independent call channels to the same guest worker. Their parent
continues to own startup, cancellation, transcripts, and shutdown.

Human `/side` creates a local tmux pane and Pi session with copied conversation
context. The frontend requests a separate attachment to the same remote worker
before starting the pane and supplies its remote connector to the fixed wrapper.
The remote owner allocates and validates attachments; it never launches frontend
processes or returns local executable paths. Failed pane startup releases only
the new attachment.

Each pane holds its own live attachment connection. Closing the original pane
ends its ordinary children but preserves side panes and their remote worker.
The remote owner cleans the workload after final attachment release. The local
transport owner keeps the shared SSH master until the final local pane closes.
Reuse the existing attachment acquire, release, and worker-loss semantics;
define their SSH wire representation before implementation.

One remote directory is selected per session. Remote `/cd` reports that directory
changes require a new CLI launch, without releasing the current attachment.
Changing the SSH host also requires a new launch. Resume uses frontend
conversations and loads context from the explicitly selected remote guest;
no live processes or extension state transfer between attachments.

== Delivery and acceptance

First expose sandbox preparation and supervision without launching remote Pi.
Then add versioned SSH startup and per-call connectors behind the existing
guest-tool extension. Integrate remote context loading before prompt admission,
then local child-wrapper inheritance and side-pane attachments. Update the operator
guide when the command becomes available; local invocation remains unchanged.

Acceptance requires a disposable remote host and guest, including these cases:

- Local typing and navigation remain responsive with injected network delay;
  tool results retain the expected delay and streamed output.
- Read, write, edit, search, shell, and `!` calls reach the guest. Fixtures readable
  only on either host remain inaccessible to guest tools.
- Remote instructions, project skills, paths, and resume context refer to the
  selected guest view; local project files cannot replace remote discovery.
- Concurrent calls do not serialize behind a long shell call. Cancellation
  affects only its call, and closing one pane preserves peer attachments.
- Protocol or Pi revision mismatch fails before prompt admission. Failed startup
  cleans only its own resources and reports incomplete cleanup.
- Disconnect before a response to a write yields an unknown outcome without
  replay, fallback, or a false rollback claim. Final attachment loss triggers
  bounded remote cleanup; an unrelated SSH master survives.
- Subagents inherit the remote connector without launching a local sandbox.
  A side pane survives original-pane exit; final-pane exit cleans remote work.
- Remote `/cd` rejects handoff without disrupting the session. Resume reloads
  remote context while retaining the frontend transcript.
- Successful or failed `/reload` retains remote guest routing or reports
  unavailability without host-local execution.

Automatic reconnect, transparent call replay, directory handoff, cross-machine
resource sharing, repository synchronization, remote provisioning, and a second
Pi frontend or subagent manager are outside this change.
