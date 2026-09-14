= Trusted-service lifecycle

*Status:* Selected design; not implemented.

== Objective

Give command proxies, authenticated egress broker instances, and host capability relays one lifecycle contract without merging their authority models or application protocols.
The lifecycle owner should remove duplicated container startup, identity validation, readiness, publication, join, cancellation, and cleanup code.
It must not turn trusted services into interchangeable endpoints or grant one service another family's mounts, credentials, network, or fallback behavior.

== Service families

The lifecycle supports three families:

/ Command proxy: Performs a bounded local operation with authority unavailable to the agent. Examples are Jujutsu and `bug`. It normally owns a session socket and protected repository mounts, and has no network unless its fixed command policy requires one.
/ Authenticated egress broker: Performs bounded requests to fixed upstream services without exposing reusable credentials. Codex and Zulip use separate credential-domain instances of the shared broker component.
/ Host capability relay: Connects an agent to an explicitly selected host capability whose protocol and authority remain outside the repository-command and authenticated-HTTP models. Examples are host editing, Agent Podman, and the current Flower R2 Keychain relay.

A service belongs to exactly one family for one lifetime.
Sharing process machinery, images, or lifecycle code does not permit sharing authority between families.
R2 remains a host capability relay until a reviewed authenticated-egress profile can sign requests without disclosing credentials and preserve per-request consent.

== Ownership boundaries

/ Configuration loader: Validates trusted repository configuration, applies installed defaults, and returns normalized capability selection and project-command policy. It cannot start services, inspect host credentials, or choose services from host availability alone.
/ Capability planner: Combines normalized policy with current host authorization and installed service definitions. It produces the complete service plan before image resolution or service effects begin.
/ Image resolver: Returns immutable images for requested logical consumers under the #link("launcher-interface.typ")[image ownership contract]. It does not start services or expand the capability set.
/ Lifecycle supervisor: Owns service identity, resource registration, shared-service readiness and publication, join validation, cancellation, and cleanup. It consumes normalized service plans and does not interpret application requests or credential formats.
/ Service adapter: Owns its fixed preparation and startup sequence, including runtime-derived addresses, host listeners, peer allowlists, and family-specific container arguments. It registers every resource with the supervisor as soon as creation succeeds and cannot publish shared state or bypass generic cleanup.
/ Protocol implementation: Owns request validation, application limits, serialization, retries, and outcome semantics. The lifecycle supervisor treats its endpoint as opaque except for its declared readiness probe.
/ Credential profile: Is the sole reader and, where refresh is required, writer of one credential domain. Neither the lifecycle supervisor nor repository configuration receives reusable secret values.
/ Runtime provider: Owns engine-specific container, network, volume, forwarding, and inspection operations. It cannot reinterpret service policy.

The launcher remains the composition root for the planner, resolver, supervisor, adapters, and runtime provider.
No service may discover additional authority after planning.

== Normalized service plan

A service plan is an internal validated value, not repository syntax.
It contains only lifecycle information needed across service families:

- stable service role and family
- lifetime scope: `shared-session` or `agent-launch`
- availability for `agent-launch` services: `required` or `best-effort`
- immutable image role and image-bound UID and GID where applicable
- service-adapter name and fixed parameters
- declared endpoint kinds and publication names
- network roles, mount roles, and credential-domain identity
- shared readiness probe or best-effort client retry contract
- shutdown deadline and recovery class
- immutable service-adapter identity and explicit lifecycle-state schema version

The plan contains role names rather than host paths, credentials, ports, socket-volume names, or runtime-generated identifiers.
Repository configuration may influence only fields explicitly owned by its normalized policy; it cannot select an installed credential profile, host path, service implementation, or recovery command.

Plans are immutable after image requests begin.
After verified image resolution, the supervisor combines the service-adapter identity, immutable image digest, image-bound parameters, and fixed plan parameters into the concrete implementation identity before service preparation begins.
Adapters may perform multi-stage startup, but lifecycle state, resource ownership, publication, and cleanup remain generic; this is the demonstrated common seam rather than a claim that all starts are declarative.
Every selected shared service is required; optionality is resolved by capability selection before planning.
If host authorization narrows while planning, omit a best-effort per-launch service or fail a required service before resolution.
Authorization changes after publication do not mutate a shared service; joins revalidate current host authorization and may reject or omit only per-launch authority as specified below.

== Identity and accepted state

A service's logical identity is independent of its generated container name.
It comprises:

- canonical repository identity for repository-scoped services
- shared-session identity or agent-launch identity
- service role, family, and scope
- runtime owner and runtime-policy digest
- immutable image identity and image-bound parameters
- implementation identity and lifecycle-state schema version
- accepted capability and configuration provenance
- credential-domain identity, never credential material
- endpoint kinds and their runtime-owned identities

The lifecycle supervisor derives a fresh resource owner for every created service instance.
All containers, networks, volumes, forwards, temporary files, and recovery records carry that owner where the runtime supports labels or equivalent metadata.
Cleanup verifies ownership before mutation.
Names are diagnostic projections and must never substitute for identity checks.

For a container service, implementation identity is the immutable image digest plus the service-adapter identity and fixed plan parameters.
For a host-native component, it is a digest of its installed trusted executable bytes and fixed plan parameters.
The lifecycle-state schema is a separate explicit integer changed only when persisted identity or recovery fields change.

Shared-session metadata records the complete accepted shared-service set and enough identity to validate each service and endpoint on join.
The complete record is atomically published as one owner-validated host runtime file with mode `0600`.
It may contain broker session tokens, which are passed only to their service and validated joining agents; it contains no reusable upstream credentials, application request fields, or mutable refresh state.
All agents attached to the accepted shared session receive the same route authority, so per-attachment token issuance and revocation add no useful isolation.
Final-holder cleanup removes the record after stopping the shared services; each token is useless upstream and expires when its service stops.
Per-launch services are not published as shared state and cannot be inherited by another launcher.

== Scope and availability

`shared-session` services are created once for one repository session and reused by all attached agents.
Command proxies and authenticated egress broker instances normally use this scope.
The first launcher owns publication; the final attached launcher owns cleanup.

`agent-launch` services belong to one launcher and one agent attachment.
Host editor and Agent Podman gateway listeners and Flower R2 consent relays use this scope.
They receive fresh tokens, networks, and host authorization on every launch and are cleaned independently of shared services.

Every selected shared service is required: the agent must not start or join without it ready.
Failure aborts startup and cleans every unpublished resource created for that attempt.
Metadata protection, Jujutsu, enabled authenticated routes, and other selected shared proxies follow this rule.

For per-launch services, `required` has the same meaning.
`best-effort` means the agent may start after the service's endpoint identity and authorization boundary exist but before its listener is ready.
The endpoint is projected into the agent, and its client performs bounded retries only for connection establishment or an explicit not-ready result.
If startup later fails, the launcher warns and cleans the service after its startup worker terminates; client retries end with an unavailable error.
A client never retries a request after the service may have accepted it.
Host editing may use this policy; installed policy may instead make an explicitly selected capability required.
Repository configuration cannot weaken installed availability policy.

== State machine

Normal transitions are:

```text
shared:      planned -> resolved -> preparing -> starting -> ready -> published -> stopping -> removed
required:    planned -> resolved -> preparing -> starting -> ready -> attached  -> stopping -> removed
best-effort: planned -> resolved -> preparing -> starting -> attached -> ready -> stopping -> removed
startup:     planned | resolved | preparing | starting | ready | attached -> failed -> stopping
recovery:    stopping -> cleanup-failed -> stopping -> removed
```

A published service that later disappears remains recorded; requests fail naturally and join-time validation rejects it until final-holder cleanup.
Recovery may leave `cleanup-failed` only after exclusive ownership validation.

/ `planned`: Policy, authority, image role, scope, service-adapter identity, and state schema are fixed; no service resource exists.
/ `resolved`: Required immutable images and image-bound parameters are verified, and the concrete implementation identity is fixed; no service resource exists.
/ `preparing`: The supervisor creates runtime-owned networks, volumes, forwards, temporary files, and credential mounts. Every successful creation is registered immediately for reverse-order cleanup.
/ `starting`: The service process or container exists but no endpoint is usable by the agent or host router.
/ `ready`: All declared endpoints passed their service-adapter probe. Shared authenticated services have their session token installed and reject unauthenticated requests; required per-launch relays have installed their token, peer allowlist, or equivalent admission. Credential readiness validates only local source identity, permissions, structure, and mount availability; it performs no upstream request, OAuth refresh, or persistent credential write.
/ `published`: One atomic shared-session record exposes the complete ready shared-service set. Individual shared services are never published incrementally.
/ `attached`: A per-launch service has been projected into one agent's mounts or environment. Required services enter only from `ready`; best-effort services may enter from `starting` after their endpoint identity and authorization boundary exist.
/ `stopping`: New attachment and routing are disabled; the service adapter may perform one bounded protocol-specific graceful shutdown, then the runtime forcibly terminates remaining owned processes.
/ `removed`: All owned runtime resources and temporary authority are gone.
/ `failed`: Resolution, startup, or readiness failed before shared publication or required attachment, or best-effort startup failed after projection. The instance cannot return to `starting`; retry requires a new plan instance and resource owner.
/ `cleanup-failed`: At least one owned resource remains. Recovery metadata must name its identity and removal failure without containing credentials.

Invalid transitions fail closed.
A service cannot prepare before `resolved`, publish before every shared service is ready, attach a required per-launch service before readiness, or attach a best-effort service before its endpoint identity and authorization boundary exist.
No service may reuse an owner after `failed` or `removed`.
`cleanup-failed` is durable failure state; only exclusive owner-validated recovery may re-enter `stopping` to finish removal.

== Planning and startup

The first launcher creates a shared session as follows:

+ Validate repository identity, protected paths, configuration, and current host authorization.
+ Produce the complete capability and service plan.
+ Request only images reachable from selected services and wait for the launcher-owned resolver results. Resolver process supervision, cancellation, joining, temporary resources, and dependency graphs remain outside the lifecycle supervisor under the #link("launcher-interface.typ")[image ownership contract].
+ Verify resolved images and finalize each concrete implementation identity, moving the service from `planned` to `resolved` without creating runtime resources.
+ Prepare shared services concurrently where their service adapters declare no fixed ordering constraint.
+ Start each service and run its bounded readiness probe.
+ On any shared-service failure, cancel unfinished starts, join their workers, and clean all unpublished resources.
+ Build one accepted shared-state value from the complete selected shared-service set.
+ Publish that state atomically, then release creation coordination.
+ Prepare per-launch services concurrently. Wait for required services to become ready; for best-effort services, wait only until endpoint identity and authorization are complete, then project them while startup continues.
+ Construct the agent environment and start the agent. A best-effort client owns bounded connection retries until readiness or terminal failure.

Concurrency is preserved for independent image resolution, network creation, service startup, and readiness checks.
The supervisor owns service preparation, start, and readiness workers. It joins shared and required workers before publication or agent start, and joins every remaining best-effort worker before cleanup so background creation cannot race deletion.
It waits for image-resolution results but never signals, reaps, or cleans resolver processes or resources.
It does not introduce a generic dependency graph: a service adapter may declare a small fixed prerequisite such as “network before container,” while image dependencies remain with resolvers and application dependencies remain with protocols.

Readiness proves only that the accepted endpoint and local authorization boundary can serve a minimal non-mutating probe.
It does not execute repository mutations, contact an authenticated upstream, refresh OAuth state, consume a model request, retrieve R2 credentials, or perform another externally visible application effect.
A protocol with no safe active probe uses a passive condition such as a bound socket plus locally validated credential input; the service adapter records that weaker evidence explicitly.
Semantic credential failure or upstream unavailability is therefore a request failure, not a reason to reject an otherwise healthy join.

== Publication and joining

Shared publication is one atomic operation.
The record includes accepted policy provenance, service identities, verified immutable images, runtime ownership, endpoints, implementation identities, and lifecycle-state schema versions.
If publication fails, no joining launcher may discover a partial service set; the publisher retains coordination through cleanup.

A joining launcher uses the accepted plan and images without reloading repository configuration or invoking resolvers.
It validates:

- repository and runtime identity
- runtime-policy digest, immutable implementation identities, and lifecycle-state schema versions
- every required service container or process
- immutable image and image-bound parameters
- endpoint identity, network or forwarding attachment, and readiness
- current host authorization required to attach

Validation is concurrent but completes before any per-launch capability or agent starts.
A missing, unavailable, or mismatched required shared service rejects the join without replacing it, reading current policy, or disturbing attached agents.
A failed shared service is not removed from accepted state or replaced in place; repair waits for final-holder cleanup and a new shared session.

After shared validation, the joiner reads authenticated service tokens from the owner-validated accepted-session record and creates per-launch services from the accepted opt-ins and current host authorization.
A missing, misowned, malformed, or mismatched record rejects the join without changing the running service.
Current authorization may narrow per-launch capabilities but cannot expand beyond accepted repository policy.
Per-launch failure follows the service's installed availability rule and never mutates shared metadata.

== Endpoint publication and routing

The supervisor publishes endpoints by role, not by caller-selected addresses.
An endpoint record identifies its transport kind, runtime-owned socket volume or private network attachment, expected service identity, implementation identity, and state schema.
Reusable upstream secrets remain only with credential profiles.
Broker session tokens live in the owner-validated accepted-session record and are passed only to accepted services and agents.

Agent mounts and environment variables are derived only after accepted-record validation.
A required per-launch service is projected after readiness; a best-effort service is projected once its endpoint identity and authorization boundary exist, even while listener startup continues.
The agent starts only after every required shared token and per-launch admission is installed.
Agent root may invoke every endpoint granted to that agent but cannot replace its socket, join its egress network, inspect sibling mounts, or select another service instance.

The host router resolves a host-routable endpoint from accepted shared metadata.
It validates repository, runtime, service, image, and endpoint identity before opening the runtime transport.
The caller supplies only the stable service role and protocol request.
Transport failure never triggers execution of a more privileged local command while the shared-session lock is held.
Outside an active session, a host shim may use its separately reviewed local implementation under the existing host coordination contract.

== Cancellation and shutdown

The launcher signal owner initiates cancellation.
The supervisor stops accepting new work, cancels startup workers, and waits for service adapters to transfer all created resources into the cleanup registry.
Each service adapter gets at most one bounded graceful-shutdown hook appropriate to its protocol; generic lifecycle code does not invent application cancellation messages or retries.
After the deadline, the runtime terminates the complete owned process or container and reaps descendants according to #link("process-ownership.typ")[process ownership].

Per-launch services stop when their agent attachment ends or its startup fails.
Shared services stop only after the final launcher proves final ownership through the host session lock.
Cleanup runs in reverse dependency order: disable host forwards and agent reachability, stop service processes, remove containers, remove socket volumes and temporary credential views, then remove networks and temporary files.
Independent removals may run concurrently when ownership and dependency order permit it.

Cleanup preserves the agent's exit status.
Failures are collected rather than stopping at the first removal error.
Diagnostics name resource identities and runtime errors but never credentials or token values.

== Recovery

Stable host lock files remain the authority for detecting abandoned shared state.
A later launcher that obtains exclusive session ownership may treat published metadata as stale, validate every recorded resource owner, and remove only those resources.
It must not infer ownership from a generated name or delete an unrecorded matching resource.

Service adapters may add recovery fields only for runtime resources that cannot be rediscovered safely, such as Lima-Docker socket forwards.
Those fields identify the resource and required removal operation, not an executable command.
Recovery does not restart individual shared services, adopt an unknown process, refresh credentials, or synthesize a new accepted plan.
After cleanup, a new launch plans and publishes a new session from current trusted configuration.

A cleanup failure retains bounded recovery metadata until the resource is proven absent or removed.
An unavailable runtime or host service is an error, not proof that its resources disappeared.

== Family-specific boundaries

=== Command proxies

Command proxies retain their fixed executable, argument grammar, repository identity, protected mounts, serialization, and Landlock or equivalent policy.
The lifecycle may create their containers and sockets but cannot generalize their protocols into arbitrary command execution.
Jujutsu's writable metadata filesystem identity remains an adapter-specific requirement.

=== Authenticated egress brokers

Each credential trust domain receives a separate broker instance, session token, credential mount, network pair, limits, and failure state.
The lifecycle shares image and orchestration machinery, not credentials or process address spaces.
HTTP route and typed-adapter behavior remains authoritative in #link("proxy-design.typ")[the authenticated egress broker specification].

=== Host capability relays

Relays remain per-launch unless a separate specification proves that sharing preserves consent, peer authorization, and cleanup.
The host listener owns host-side authorization; the relay container owns only fixed byte transport.
Peer allowlists or equivalent admission must be installed before readiness.
A best-effort relay that fails before endpoint identity and authorization exist leaves no agent-visible endpoint.
Failure after attachment leaves the projected endpoint unavailable until bounded client retries end and cleanup removes the owned resources.

== Rejected generalizations

/ One universal request protocol: Rejected because Jujutsu arguments, Zulip typed reads, HTTP streaming, editor bytes, Podman SSH, and Keychain consent have different validation and outcome semantics.
/ One container for all trusted services: Rejected because compromise would combine metadata, model, communication, container, and publication authority.
/ Repository-declared credentials or host paths: Rejected because trusted project policy is not authority to select a human credential source.
/ Generic service dependency graph: Rejected because it would duplicate image-resolver graphs and hide the few security-relevant startup prerequisites inside data.
/ Automatic service restart: Rejected because replacing one published instance would change accepted authority and endpoint identity beneath attached agents.
/ Best-effort fallback: Rejected for required services and all privileged local execution. Before attachment, best-effort failure means omission; after attachment, it means a bounded unavailable endpoint, never weaker isolation or privileged fallback.

== Migration

+ Introduce normalized service plans and adapters around existing behavior without changing service scope or authority. Add bounded automatic connection retries to best-effort clients that currently require manual retry; test that they stop at the deadline and never replay a request after connection or send outcome becomes uncertain.
+ Move common resource registration, readiness supervision, identity recording, and reverse-order cleanup into the lifecycle supervisor.
+ Migrate command proxies first because their shared-session publication and host routing already exercise the full shared lifecycle.
+ Migrate Codex and Zulip to separate instances of the authenticated egress broker component under the same supervisor.
+ Migrate per-launch gateway and R2 relays after their installed required-versus-best-effort behavior is explicit and regression-tested.
+ Remove service-specific lifecycle branches only after differential tests show identical mounts, networks, credentials, readiness, joins, interruption cleanup, and fallback behavior.

Each migration slice must leave the launcher with one owner for the migrated resource.
Do not retain a service-specific cleanup path beside generic cleanup as a fallback.

== Acceptance checks

- Planning fixes authority and service-adapter identity before image resolution; verified images finalize implementation identity before resource creation.
- Every created resource is registered once under a fresh owner before another worker can fail or cleanup can begin.
- Independent service starts remain concurrent; shared publication and required attachment wait for readiness, while best-effort attachment waits only for endpoint identity and authorization.
- One atomic mode-`0600` accepted-session record publishes the complete required shared-service set and broker session tokens; joins never observe partial state.
- Joins load no current repository policy or images and reject missing, unavailable, mismatched, or unauthorized required services without disturbing holders.
- Post-publication service loss requires no mutable health record: requests fail naturally, joins reject through live validation, and final-holder cleanup removes the recorded service.
- Best-effort clients retry only connection establishment or explicit not-ready results within a bound; they never replay a possibly accepted request.
- Every selected shared service is required; optionality is resolved before planning rather than recorded as partial shared state.
- Per-launch capabilities receive fresh authorization, tokens, networks, and cleanup and cannot expand accepted repository opt-ins.
- Required per-launch failure prevents agent startup; best-effort failure leaves its projected endpoint unavailable, reports failure after bounded retries, and completes owned cleanup without terminating the agent.
- Agent root cannot use lifecycle metadata to select another endpoint, credential domain, repository, executable, mount, or runtime operation.
- Host routing validates published service and endpoint identity and never falls back to privileged local execution while a session is active.
- Codex and Zulip share broker implementation but not containers, credentials, tokens, networks, mutable state, or failure domains.
- Jujutsu retains its repository-specific grammar, writable metadata identity, and Landlock boundary.
- R2 retains per-use consent and dedicated relay semantics until a separately reviewed signing profile replaces them.
- Cancellation joins startup workers before cleanup and leaves no creator racing a remover.
- Final-holder cleanup removes only owner-validated resources in dependency order and preserves the agent exit status.
- Cleanup failure retains credential-free recovery identity; later recovery neither adopts nor restarts an unknown service.
- Service-specific retries, mutation outcomes, and graceful shutdown protocols remain with their application owners.
