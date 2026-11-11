# Workstation control map

Read this after naming the asset and attacker.
Use it to distinguish controls that block a path from controls that only look adjacent to it.

| Attacker path | Distinguishing check | Controls that can help | Does not establish the boundary |
| --- | --- | --- | --- |
| Same-uid code reads another process’s secret | Inspect the real launcher and test a sibling `/proc/$pid/` or ptrace read from the same session tree. | Separate uid; target-specific LSM confinement for a named process; a user-wide LSM rule only when its matching model covers the relevant processes and peer operations; shorter secret lifetime; disabled core dumps where relevant. | File mode `0600`; `hidepid` alone; a profile on one executable proving a uid-wide boundary; locking a vault after a CLI already returned the secret. |
| A stolen password is replayed for local privilege | Inspect the PAM stack that the real sudo or login path uses and the enrolled hardware-token paths. | Hardware-backed PAM; removing password fallback when recovery is acceptable; trusted invocation path for `sudo`. | A hardware touch proving the requesting process is benign; SSH password settings proving local sudo behavior. |
| Remote login reaches the host | Inspect SSH authentication settings and authorized keys separately from local PAM. | FIDO-backed SSH keys; disabled remote password auth; removal of old software-backed keys when no longer needed. | Local PAM changes proving the remote path is closed. |
| Physical access tampers with pre-boot code | Inspect whether `/boot` is outside the encrypted volume, the active boot loader, Secure Boot state, and whether the actual boot artifact is signed. | Secure Boot with signed UKIs; firmware key enrollment that preserves required vendor keys; measured boot when the threat model needs it. | Disk encryption alone; signing only a kernel while leaving mutable initramfs or command-line inputs unsigned. |
| A sole hardware token is lost | Count enrolled tokens and identify a recovery path that does not depend on the missing device. | Spare token; recovery secret; admin replacement path that remains available without the lost token. | “I can always replace it later” when replacement itself requires the missing token. |

When several rows apply, rank them by current exposure and the user’s stated friction budget.
Do not add a control from one row merely because another row is unresolved.
