---
name: workstation-hardening
description: >-
  Assess and improve a developer workstation or local host that stores or invokes sensitive credentials or capabilities.
  Use for same-uid process isolation, launcher secret handling, hardware-token workflows, PAM or sudo trade-offs,
  SSH key posture, Secure Boot, encrypted-disk limits, and other host hardening choices driven by a concrete attacker path.
  Not for web application review, network perimeter design, incident response, or a generic checklist with no named asset.
---

# Workstation hardening

Reduce the path by which the named attacker can reach the named local capability.

## Start with the asset and attacker

Name what access matters, where it appears in the system, and which attacker matters now.
Do not collapse same-uid code execution, password replay, remote login, physical access, and hardware-token loss into “local attacker.”
If the user corrects the credential source or access path, discard conclusions built on the old path and inspect the new one.

Read [the control map](references/control-map.md) after the asset and attacker are clear.
It helps choose a control class without turning the task into a baseline checklist.

## Inspect the real path

Inspect the launcher, secret source, file modes, process environment, service state, PAM stack, SSH configuration, boot chain, and enrolled hardware keys that actually participate in the path.
Use the smallest read-only probe that can distinguish the live behavior from a plausible alternative.
For host services, EFI state, or other facts hidden by sandboxing, request an unsandboxed read-only check before drawing a conclusion.

Treat installed, configured, loaded, and effective as different states.
A package on disk, an enabled service, or a written config file does not establish that the relevant boundary is active in the current boot or session.
Verify the consumer that matters: the running service, the real session root, the active PAM stack, or the firmware state.

## Choose the smallest matching control

Prefer the smallest supported control that blocks the current attacker path and fits the user’s friction budget.
Do not recommend a control because it sounds stronger in the abstract.
Explain what path it blocks, what path remains, and what user cost it adds.
Label general hygiene separately from controls that protect the named capability directly.

Some distinctions recur:

For same-uid isolation, first decide whether the goal is to protect one named target or to impose a rule across the whole uid.
A target-specific boundary can attach to one launcher, executable, or service.
A user-wide sibling rule must cover the full set of processes and peer operations that the chosen mechanism uses to decide access.
Transition-based confinement usually has to cover the relevant launch paths.
Operation-based mediation usually has to cover the relevant read or trace hooks.
For AppArmor specifically, a target-only profile does not block ordinary unconfined same-uid readers because AppArmor skips the ptrace cross-check for an unconfined tracer.
Do not treat that shape as a target boundary unless the reader side is also confined.
For a user-wide sibling rule, prefer operation-based mediation when the kernel hook can express the denied read or trace directly.
Treat launch-tree allowlists as fragile.
If the design names trusted session roots, such as `user@.service`, ssh, mosh, or a display manager, inspect the live session tree before rollout and show that every required root is covered.
Missing one root can both break legitimate sessions and leave an uncovered path.
Do not present a target-specific confinement mechanism as a user-wide boundary unless that coverage has been shown.

- same-uid secret exposure needs a same-uid boundary such as a separate account or mediated `/proc` and ptrace access;
  file mode `0600` and `hidepid` do not solve same-uid reads by themselves;
- password replay can justify hardware-backed authentication;
  removing a password fallback also changes lockout and recovery behavior;
- physical boot tampering needs a verified boot chain such as signed UKIs under Secure Boot;
  disk encryption alone leaves mutable unencrypted boot components outside that guarantee.

Before a broad host control such as a `/proc` mount option, login or session-root policy, or user-wide LSM rule, verify the exact attacker action first.
If the candidate does not block that read, trace, login, or boot path in a representative case, stop before accepting its broader host cost.

When the user rejects the stronger boundary, state the residual exposure precisely and continue with the best remaining option.
Use [work-selection](../work-selection/SKILL.md) before adding another substantive prerequisite, workaround, or hardening layer.
Use [human-review-packets](../human-review-packets/SKILL.md) before asking the user to approve a lockout-prone auth change or firmware-key enrollment.

## Keep public and private state separate

Public configuration can track generic hardware-token support, generic launcher plumbing, and reusable host policy.
Keep machine-local secret names, ciphertext, serial numbers, service names, recovery data, and admin paths in local state unless the user explicitly wants them published.
Document local rotation and recovery beside the local state that needs it.

## Verify the boundary

Verify the control at the attacker’s observation point.
For same-uid isolation, test the actual sibling read or trace path from the real session tree.
For LSM or service changes, confirm the kernel or service loaded the policy after the required reboot, reload, or relogin.
For PAM or hardware-token changes, inspect the real stack order and confirm a recovery path before removing a fallback.
For Secure Boot, verify firmware state and the signed boot artifact that will actually run.

Do not claim a control works when only the configuration step is complete.
State what remains unverified until the reload boundary has happened.

## Worked choices

### A launcher exports a secret into a child process

If the concern is same-uid malware, a locked secret store and `0600` files stop being relevant once the launcher has already placed the secret in memory.
Inspect whether a sibling can read or trace that process.
If it can, prefer a real same-uid boundary first.
If the user keeps one account, use the best supported mediation available, shorten secret lifetime where practical, disable avoidable dumps, and keep the residual exposure to the target process explicit.

### A user wants fresh hardware presence for sudo

First distinguish replay of a stolen password from code already running under the user’s uid.
A hardware-backed PAM path can stop password replay.
It does not prove that the command asking for the touch is benign, because malicious code under the same uid can wait for the same touch and piggyback on it.
Before removing password fallback, count enrolled recovery paths and make the lockout consequence concrete.

### An encrypted laptop still has mutable boot files

If `/boot` is outside the encrypted volume, an attacker with physical access can replace code that runs before the disk unlock prompt.
Use Secure Boot only with the signed artifact that contains the kernel, initramfs, and command line that will actually boot.
Check the current boot loader and artifact layout before choosing the enrollment path.

## Finish

Report the observed facts, the chosen control, the effective state, the remaining exposure, and any recovery step the user still needs.
Keep the assessment tied to the named attacker path rather than expanding into unrelated hardening.

This skill must trigger for “can sibling processes read the token my launcher passes to a local tool?”
It must trigger for “should I remove password fallback from sudo if I use a YubiKey?”
It must trigger for “does Secure Boot still matter if my disk is encrypted?”
It must not trigger for “review this web app for XSS” or “scan my cloud account for exposed keys.”
