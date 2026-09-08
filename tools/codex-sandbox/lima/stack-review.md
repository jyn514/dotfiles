# Lima fixture stack review

The network fixture pins nerdctl-full 2.3.5 and slirp4netns 1.3.5 for arm64.
The production VM and launcher integration remain unimplemented.

## Release provenance and authority

The [2.3.5 release](https://github.com/containerd/nerdctl/releases/tag/v2.3.5)
is an immutable upstream release with a verified signed tag. Its published
SHA256SUMS gives the arm64 archive digest
`6e4b687f1d138e750a3c8372abc0f81d3d7490b6359c48c0562fc7dfe98859b2`;
Lima verifies that digest before installation.

The bundle owns container execution, network setup, and builds inside the guest.
Its release notes select containerd 2.3.3, RootlessKit 3.0.2, BuildKit 0.31.2,
and runc 1.5.1; its source pins CNI plugins 1.9.1. Nerdctl declares compatibility
with containerd 2.3. This review inspected the tagged rootless launcher and CNI
configuration ownership, not the entire bundled implementation.

The rootless launcher still prefers slirp4netns and supports detached namespaces,
but the new bundle omits the slirp4netns executable. Its source selects
gvisor-tap-vsock when neither slirp4netns nor vpnkit is present.
The fixture must verify the pinned CIDR/DNS and reject incompatible effective
state rather than select another driver. No host package manager, shared Lima
instance, or production launcher changes are part of this fixture update.

## Separate transport dependency

[slirp4netns 1.3.5](https://github.com/rootless-containers/slirp4netns/releases/tag/v1.3.5)
uses the same slirp4netns source with libslirp 4.9.4 and libseccomp 2.5.3.
The older 1.3.3 binary contains libslirp 4.9.1; subsequent
[libslirp security fixes](https://gitlab.com/qemu-project/libslirp/-/blob/v4.9.4/CHANGELOG.md)
address TCP urgent-data and fragmented-packet information leaks.
This preserves the selected driver and network policy while updating its library.

The signed upstream release publishes SHA256SUMS; its manifest hash matches
`586e277d6f494c1bce4d98a854cd189d04bb19e5d53d3a28873084f16b9b821a`
from the release notes. The arm64 binary pin is
`a212e7acabf09e809b62ca62d1721ecab0d811d05c378ea0270ce29a70d986df`.
Review covered slirp4netns's namespace, host-loopback, and seccomp controls and
libslirp's release changelog; it was not a full code audit.

The host-owned Lima template references a separate Python dependency hook.
Lima 1.2.1 executes it before containerd setup. The hook verifies the binary before
atomic installation, reuses a matching installation, and rejects a different
existing file. The preflight remains authoritative if dependency installation fails.

## Why the old bundle cannot become the production pin

The earlier 2.1.3 bundle ran runc 1.3.0. It falls within the affected versions of
the upstream [masked-path escape advisory](https://github.com/opencontainers/runc/security/advisories/GHSA-9493-h29p-rfm2)
and [malicious-image `/dev` symlink advisory](https://github.com/opencontainers/runc/security/advisories/GHSA-xjvp-4fhw-gc47).
The fixture used an owned, digest-pinned image in an unshared VM; its network
results are not evidence that this runtime is suitable for untrusted workloads.

## Validation

The first 2.3.5 run failed preflight before workloads because slirp4netns was
missing. Adding the dependency hook resolved that failure without relaxing the
preflight. Guest output confirms slirp4netns 1.3.5, libslirp 4.9.4, the selected
slirp4netns driver, CIDR `10.0.2.0/24`, and DNS `10.0.2.3`.

On 2026-09-08, the pinned stack passed the full fixture before and after reboot:
public DNS/HTTP, owned-host denial, internal relays, restricted proxies, IPv6
checks, missing/stale policy, and four partial-policy failure cases with resource
cleanup. Both strengthened live-child interruption cases passed, preserving
status 143 and removing their owned VMs.

All four installer tests and 11 existing policy/fixture tests passed. Disabling
the verifier made both checksum regression tests fail. Native Lima template
validation and `diff-check` passed; only the pre-existing `ferrocene` instance
remained after cleanup. Production VM shares, runtime integration, credential
migration, and cutover still require their later plan gates.
