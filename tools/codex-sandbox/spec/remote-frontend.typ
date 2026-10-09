= Local Pi with a remote sandbox

*Status:* Proposed; the Pi resource-provider API, remote launch, and SSH
extension are not implemented.
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

The remote launcher is the authority for repository identity, guest cwd, and
accepted policy. The frontend receives a validated attachment
description rather than reconstructing these from local paths. Remote host paths
are context, not frontend filesystem paths. Saved session cwd remains historical
context and cannot select another remote repository or host.

Keep frontend model credentials local. Use sandbox-host credentials for its
existing trusted services under their normal admission rules. Do not forward
the frontend SSH agent, credentials, arbitrary sockets, or environment as part
of this feature. Use a launch-owned SSH master with agent forwarding disabled,
rather than reusing an existing master whose forwarding state is unknown.
The local SSH extension implements transport. Reuse the existing detached
frontend attachment owner to hold the shared master and remote attachment
connections; their lifetime does not depend on an extension instance.
Peer panes share that master; per-call cancellation cannot terminate it.
Pi core owns the resource-provider API and contains no SSH or sandbox-launcher
implementation.

== Pi resource provider

Add a transport-independent resource-provider API directly to Pi. An admitted
local extension registers its provider before initial project discovery and
context loading. Registration must work during ordinary CLI startup; an SDK-only
loader override or a hook after discovery is insufficient. Startup order is:
load explicitly selected local extensions and frontend personal configuration,
apply their CLI flag values, register and initialize the resource provider,
then discover resources and build the prompt. The wrapper selects the SSH
extension explicitly; this bootstrap phase does not discover frontend project
settings, packages, or extensions. The SSH extension owns `--ssh` parsing and
remote target validation. Exact API names and signatures remain to be designed
in Pi.

The provider discovers and asynchronously reads guest instructions, skill
metadata and bodies, project prompt templates, and project system-prompt
resources. Pi retains local executable extensions, themes, settings, credentials,
and transcripts; it must not discover project code or configuration from a
frontend directory chosen merely to launch remote mode. Remote project data
cannot register executable frontend code.

The provider also supplies the model-visible cwd and the guest paths for Pi's
documentation, README, and examples from the validated guest attachment. Pi uses
them to build those prompt sections with guest paths and no text rewriting.
Keep the frontend process cwd and local session storage
separate from the model-visible cwd. The guest's existing read-only Pi package
mount supplies the documentation paths.

For example, startup fetches guest `AGENTS.md` and skill descriptions through the
provider. `/skill:name` asks that same provider for the skill body using its guest
path, including when the prompt is queued as steering or follow-up input.
Instruction includes resolve recursively in the guest, with guest home and
relative-path semantics. The existing local-filesystem include extension must
not read these paths on the frontend; its remote expansion uses the provider.

Initial load and `/reload` await provider discovery before publishing a complete
resource snapshot to Pi's cached getters. Resource reads preserve guest paths
in prompts and skill metadata. No host-to-guest prompt or history rewriting is
needed: current resources already use the guest namespace, and historical paths
remain historical data. Provider failures report unavailability rather than
falling back to local discovery or reads.

Use the same provider for startup, reload, skill expansion, and resource additions
requested by local extensions. A local extension adding a project resource must
use the provider's namespace; it cannot silently introduce a frontend path.
This is a project-resource interface, not a replacement for Node's filesystem
or an interception of arbitrary extension file reads.

== Startup and tool transport

Separate sandbox preparation and supervision from frontend Pi launch. A fixed
remote launcher entrypoint receives the target path as structured data over
stdin, validates it, and starts or joins the ordinary sandbox. Do not interpolate
the project path or tool arguments into a remote shell command.

The SSH extension asks the frontend attachment owner to start the remote launcher
and installs both guest tool routing and the Pi resource provider.
The remote supervisor returns readiness after policy
admission, worker readiness, and compatibility validation. The extension obtains
resources through that attachment; Pi accepts prompts only after initial provider
loading succeeds. Startup diagnostics use stderr; protocol frames use stdout.
Local Pi starts without requiring a matching local repository checkout.

Reuse the existing guest-tool request and response semantics: tool parameters,
per-call model identity, streamed updates, text and image results, errors, and
completion. One SSH channel per call connects to the attachment's persistent
guest worker. Reuse the launch-owned connection through ControlMaster; do not
share one serial request stream across concurrent tools. The attachment binds every call to its
selected worker until completion; callers cannot select a container or proxy.
Provider discovery and reads also execute in that guest through the extension's
transport, rather than using SSH host filesystem operations. The extension owns
SSH arguments, framing, cancellation, and transport diagnostics; Pi core sees
only the resource-provider contract and registered tools.

The frontend and sandbox host deploy independently. Define a versioned startup
and attachment protocol and reject unsupported versions before exposing tools.
Initially require the same Pi source revision on both ends, including the guest
worker, to preserve tool schemas and result semantics. Report mismatches with
the affected side and required update; do not upgrade automatically. Exact frame
schemas and size limits must be specified before implementation.

== Lifetime, failure, and recovery

The remote supervisor owns workload lifetime; each frontend pane holds a live
attachment connection. Normal pane exit releases its attachment. The existing
detached frontend attachment owner holds the shared SSH master and live
attachments across reload and original-pane exit while peer panes remain. The
remote owner releases a lost connection after bounded transport-failure
detection and removes the workload only after the final attachment closes. SSH
master persistence is not an attachment lease.

`/reload` replaces extension handlers and reloads resources through the same
attachment. Its extension shutdown event must not release that attachment or
stop SSH. The attachment owner observes Pi process exit and releases that
pane's lease, while keeping the shared master and peer attachments alive.
Reloaded handlers use the inherited owner connection rather than starting a
second master or remote workload. Failed reload leaves remote operations
unavailable; retry uses the same live attachment and workload.

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
Every child and side pane loads the SSH extension and registers the inherited
resource provider before discovery. Children open independent call channels to
the same guest worker. Their parent
continues to own startup, cancellation, transcripts, and shutdown.

Human `/side` creates a local tmux pane and Pi session with copied conversation
context. The frontend requests a separate attachment to the same remote worker
before starting the pane and supplies its remote connector to the fixed wrapper.
The remote owner allocates and validates attachments; it never launches frontend
processes or returns local executable paths. Failed pane startup releases only
the new attachment.

Each pane holds its own live attachment connection. Closing the original pane
ends its ordinary children but preserves side panes and their remote worker.
The remote owner cleans the workload after final attachment release.
The frontend attachment owner keeps the shared SSH master until the final local
pane closes, then stops it and exits.
Reuse the existing attachment acquire, release, and worker-loss semantics;
define their SSH wire representation before implementation.

One remote directory is selected per session. Remote `/cd` reports that directory
changes require a new CLI launch, without releasing the current attachment.
Changing the SSH host also requires a new launch. Resume uses frontend
conversations and loads context from the explicitly selected remote guest;
no live processes or extension state transfer between attachments.

== Delivery and acceptance

First add Pi's resource-provider API, including early extension registration,
async skill expansion, and reload integration. Then expose sandbox preparation
and supervision without launching remote Pi. Add the local SSH extension with
versioned startup, guest-tool connectors, and guest resource operations.
Integrate child-wrapper inheritance and side-pane attachments. Update the operator
guide when the command becomes available; local invocation remains unchanged.

Acceptance requires a disposable remote host and guest, including these cases:

- Local typing and navigation remain responsive with injected network delay;
  tool results retain the expected delay and streamed output.
- Read, write, edit, search, shell, and `!` calls reach the guest. Fixtures readable
  only on either host remain inaccessible to guest tools.
- Remote instructions, project skills, paths, and resume context refer to the
  selected guest view; local project files cannot replace remote discovery.
- The SSH extension receives its CLI target before resource discovery. Startup
  in a frontend directory containing project settings or extensions does not
  load them. Generated cwd and Pi documentation prompt sections use guest paths.
- Startup, queued `/skill` input, recursive includes, prompt templates, resource
  additions, and `/reload` use the provider. A frontend-only file at the same
  path cannot satisfy a guest resource read. No prompt-path rewriting is required.
- Concurrent calls do not serialize behind a long shell call. Cancellation
  affects only its call, and closing one pane preserves peer attachments.
- Protocol or Pi revision mismatch fails before prompt admission. Failed startup
  cleans only its own resources and reports incomplete cleanup.
- Disconnect before a response to a write yields an unknown outcome without
  replay, fallback, or a false rollback claim. Final attachment loss triggers
  bounded remote cleanup; an unrelated SSH master survives.
- Subagents inherit the remote connector without launching a local sandbox.
  Children and side panes load resources through their inherited provider.
  A side pane survives original-pane exit; final-pane exit cleans remote work.
- Remote `/cd` rejects handoff without disrupting the session. Resume reloads
  remote context while retaining the frontend transcript.
- Successful or failed `/reload` retains remote guest routing or reports
  unavailability without host-local execution.
  Reload preserves the attachment and shared SSH master; retrying a failed
  reload does not create a second workload.

Automatic reconnect, transparent call replay, directory handoff, cross-machine
resource sharing, repository synchronization, remote provisioning, and a second
Pi frontend or subagent manager are outside this change.
