---
name: operational-lifecycle
description: "Design or review how an installed tool, service, or stateful workflow is set up, operated, updated, recovered, and removed. Use for installers and deployment workflows, service and reboot integration, recurring refresh or publication, independent code/configuration/data updates, and operational runbooks whose behavior is unsettled. Also use when one-time setup and repeatable operations are confused. Trace actual entrypoints and persistent state; reuse existing tools. Not for in-process resource lifetimes, product-development stages, prose-only edits with settled behavior, or routine commands and localized fixes with unchanged operational contracts."
---

# Operational lifecycle

Establish what an operator does, what each operation changes, and how the system remains usable afterward.
Start with the requested operating outcome, not an installer, preparation directory, or service manager.

## Establish the task

Identify the system, operator, desired outcome, current starting state, and permission to investigate, design, review, or implement.
A review authorizes findings, not repairs or live deployment.
Writing a runbook does not authorize changing the system it describes.
Separate observed behavior, required outcomes, and proposed changes.

Use only the phases relevant to the request.
A question about boot startup may need one unit-file check, not a complete deployment design.
For settled behavior that only needs explaining, use [holistic writing](../holistic-writing/SKILL.md) and its documentation checks.
Do not turn a request for clarity into a design choice when the operating outcome is already settled.
Use [architecture design](../architecture-design/SKILL.md) when the operating workflow exposes an unresolved subsystem, interface, or authority boundary.
[new-tool development](../new-tool-development/SKILL.md) owns development stages, not operation of an installed system.

## Trace an operation through its next use

Read the existing entrypoints, native tool interfaces, service configuration, state locations, and relevant operator instructions.
Follow one concrete operation from the operator's starting state through effects, selection, and the result its consumer actually uses.
Then trace the next normal invocation or update; first-run success alone can hide a required reinstall or stale consumer.

Distinguish one-time setup from recurring work, including code installation, source-data refresh, publication, and activation when those are separate operations.
Establish which code, configuration, data, credentials, and process state persist or change together.
Identify the actor, permissions, authoritative inputs, resulting state, and repeat trigger for the operations in scope.
A compact comparison can help when several operations interact; do not require a new inventory document.

Check current process state separately from configured startup behavior.
Starting a service need not enable it at boot; enabling it does not establish that required mounts, network routes, or credentials will be available.
Where credentials are required, establish their availability under the actual runtime identity and session; interactive success alone does not establish unattended access.
Trace public access through the actual proxy or tunnel to the local listener rather than equating a successful loopback request with external reachability.
For a batch command without a resident process, do not invent service or reboot integration.

## Choose the smallest complete operating workflow

Compare the existing package manager, application command, supervisor, and publisher with any proposed wrapper.
Let an existing owner perform the whole operation when its supported interface meets the outcome.
Do not add manual export/build/copy steps, temporary bundles, receipts, or persistent coordination merely to reproduce native behavior.
When the approach changes, retrace its steps and options: remove those whose purpose the new interface already satisfies, and check defaults before adding overrides.
Keep preparation or staging when it provides a required isolation, consistency, or publication property; do not remove it just to reduce command count.
For paths and other platform conventions, identify the concrete requirement they satisfy before making them mandatory; preserve conventions when they serve the actual environment.

Determine which updates actually require reinstalling code, rebuilding data, restarting a process, or changing external configuration.
Distinguish supported setup and migration procedures from completed one-off work; describe the latter only where it changes a current operator action or contract.
Trace the consumer's supported reload or restart boundary; changing a file or selector does not by itself establish that a running consumer uses it.
Do not require separate update mechanisms for inputs that necessarily change together.
When removal or replacement is in scope, identify which owned resources are disabled or deleted and which data or external effects remain.
Removing an installation does not necessarily remove its published artifacts or undo delivered effects.

Name trust changes explicitly, including who can replace executable code as well as who can change data.
Check the authority of the resulting running process and privileged hooks, not just filesystem ownership or the installer account.
Resolve consequential unsettled choices before implementing dependent work, without adding a separate approval process for routine applications of established decisions.

For independently updated components, persisted formats, migrations, or rollback, read [Deployment and evolution](../references/deployment-and-evolution.md).
For interrupted or multi-step effects, use the existing [partial-failure and recovery checks](../references/failures-and-recovery.md#partial-failure-and-recovery).
For identifying an unsuccessful operation and its safe next action, use [Diagnosability](../references/failures-and-recovery.md#diagnosability).
These are conditional checks, not a requirement to add compatibility layers, transactions, monitoring, or recovery machinery.

## Work through the recurring case

Suppose a browser reads a published copy of a working database.
Fetching more records changes the working database, but the browser can still serve its older selected copy.
Trace how the publisher prepares and selects a replacement, and whether the browser watches that selection or needs an explicit reload.
If the installed application has not changed, a data refresh need not repeat its installation.
If the publisher already prepares, verifies, and selects the replacement, reuse that operation rather than requiring a second manual preparation pipeline.
Retain a separate preparation step if review before public release is a requirement.

For a batch report generator that reads the selected data on each invocation, the next run may already consume the replacement.
Use that behavior instead of importing the browser's restart step or creating a daemon.
The same operating question can therefore yield different commands and owners.

## Verify and hand off

Check changed lifecycle guarantees at the relevant consumer using disposable state where possible.
Include a repeat operation or interruption case when it can distinguish the proposed workflow from the failure it must prevent.
Reuse evidence for unchanged phases; do not repeat large builds or data preparation to validate a prose rearrangement.
Do not mutate real installations, services, credentials, or external routes without authorization for those effects.

Distinguish syntax and configuration checks from exercised installation, reboot behavior, public routing, or recovery.
Record which integrations remain unverified without turning every untested environment into a prerequisite investigation.
Use existing status, version, or selection evidence when sufficient.

Deliver the requested explanation, review findings, implementation, or runbook with one-time and recurring operations clearly separated.
When an operator must configure an external system, give its control plane or entrypoint, required fields and values, and a verifiable result, or link to a usable procedure.
Include applicable failure behavior, safe repetition or recovery, and remaining decisions.
Do not create an additional specification, checklist, or runbook unless the task needs one.
For substantial prose, finish with the [shared editorial pass](../holistic-writing/references/editorial-pass.md).
