# Lima network feasibility

Lima-Docker is the default. This page describes the nerdctl network fixture;
the [host setup](host-setup.md), [credential migration](credentials.md), and
[opt-in launcher](launch.md) are implemented separately.
For Docker setup and its remaining validation limits, see
[Lima-Docker](docker.md#default-readiness).
New Docker VMs also enable a
[container-cache reclamation timer](docker.md#container-cache-reclamation).

The 2.3.5 bundle omits slirp4netns. Lima's dependency hook installs a checksum-pinned
slirp4netns 1.3.5 before containerd setup; see the
[stack review](stack-review.md).

## Run the probe

On Apple Silicon macOS with Lima 1.2.1 installed:

```sh
python3 tools/codex-sandbox/tests/lima_policy_test.py
python3 tools/codex-sandbox/tests/lima_slirp_install_test.py
python3 tools/codex-sandbox/tests/lima_network_integration.py --reboot > /tmp/lima-network.log 2>&1
python3 tools/codex-sandbox/tests/lima_interruption_integration.py > /tmp/lima-interruption.log 2>&1
```

The integration command creates a uniquely named VM with no host shares or
forwarded SSH agent. It downloads a digest-pinned Ubuntu 24.04 image, the
nerdctl 2.3.5 bundle, and a digest-pinned official Python/Alpine test image.
The [stack review](stack-review.md) records the
candidate versions and validation status. Ubuntu's archived guest image uses HTTP;
Lima must verify its SHA-256 before booting it.

The [transport installer](install-slirp4netns.py) verifies the upstream binary
before publishing it atomically at `/usr/local/bin/slirp4netns`. Repeated setup
verifies the installed file without downloading it again; a different existing
binary is rejected. Download or checksum failure leaves the executable path
untouched. Lima can continue later boot scripts after a dependency-hook failure,
so the fixture's network preflight still rejects a missing or different transport
before running any workload.

The command prints the owned VM name before creation and deletes that VM on
success or failure. Use `--keep` to stop and retain it for inspection instead.
If cleanup fails or the host process is killed before cleanup, inspect the
printed instance name and remove only that instance with
`limactl delete --force INSTANCE`. It never selects `ferrocene` or a real session.
`--reboot` repeats the probes after a VM stop/start without reinstalling the policy.
The interruption command runs separate fixtures, waits for a live startup or
probe subprocess, sends SIGTERM, and requires exit status 143 and VM removal.
The network fixture also owns a loopback-only host HTTP listener, which serves
only a random marker and closes during cleanup.

## Relay and failure probes

The fixture directly configures a CNI internal link with no bridge gateway,
masquerading, or default route. Its tuning plugin disables IPv6 on that attachment
only; namespace-wide restoration during DEL could undo another attachment's policy.
See the CNI [bridge](https://www.cni.dev/plugins/current/main/bridge/) and
[tuning](https://www.cni.dev/plugins/current/meta/tuning/) contracts.

A non-root, read-only relay joins the internal link and a separate egress network.
It forwards HTTP only to the owned host listener. Root agent and restricted
non-root proxy probes must receive the marker through that relay while direct
access to the live host IP is denied by policy. An internal-only client must
reach the relay, lack an IPv4 default route and non-loopback IPv6 addresses,
and fail to re-enable IPv6 or reach the host directly.

The fixture-only `policy-fault` wrapper invokes the installed policy and injects
an error or SIGKILL after a real prohibited-route or TCP DNS-rule mutation.
Each case requires recorded kernel evidence, no workload output, removal of
container metadata, namespace, IPAM allocation, and veth, then valid startup on
the same network. Bridge inspection explicitly enters RootlessKit's detached
network namespace and requires the running peer's bridge as a positive control.
Missing policy, stale digest, and a correctly hashed wrong DNS address must also
reject process startup.

## Explicit DNS configuration

[rootless-network.json](rootless-network.json) pins the existing slirp4netns
subnet `10.0.2.0/24` and its derived DNS endpoint `10.0.2.3`. Setup verifies the
effective driver, DNS, and child address before adding a persistent containerd
service override for `--cidr=10.0.2.0/24`. It refuses custom flags it would replace
and verifies that no other RootlessKit arguments changed after restart.
The slirp4netns driver and Lima VM networks are unchanged; the binary pin includes
libslirp security fixes.

Workloads explicitly select this DNS address. Nerdctl may list it twice because
it also prepends RootlessKit's DNS; duplicate entries do not grant extra access.

## Policy ownership

The launcher and fixture use [network_policy.py](../network_policy.py) as the
single CIDR authority. Provisioning snapshots its serialized policy; ordinary
runtime startup verifies installed files rather than executing checkout policy.
Trusted installation copies the candidate plugin into `/usr/local/libexec/cni`
and the versioned policy into `/usr/local/share/codex-sandbox`; neither path is
mounted into workloads. The generated CNI configuration records the policy's
SHA-256 and retains nerdctl's `same-bridge` firewall.

The chained plugin uses guest `nsenter`, `ip`, and `sysctl` before process startup.
It disables IPv6, installs all prohibited IPv4 routes, verifies effective state,
and preserves the preceding CNI result. Missing/stale policy or any command failure
rejects startup. DEL retains restrictions until runtime-owned namespace destruction,
because removing one attachment must not expose another. See the
[CNI execution contract](https://www.cni.dev/docs/spec/).

Inside each workload network namespace, routing table 1053 supplies a route to
the pinned DNS address through the existing gateway. Only two policy-routing
rules select it: TCP destination port 53 and UDP destination port 53, at
priorities 1053 and 1054. Other traffic to that address still encounters the
prohibited route in the main table. The helper verifies the selectors, successful
DNS route lookups, and rejected non-DNS route lookups before startup.

Before modifying a namespace, the helper checks RootlessKit's control API for the
expected slirp4netns driver and DNS address. With `--detach-netns`, the daemon's
`resolv.conf` is not the workload's resolver configuration; the API is authoritative.
An unavailable API or a mismatched address rejects startup.

RootlessKit copies `/etc` at startup, so subsequently installed policy there was
invisible to the plugin. `/usr/local/share` remains visible. Guest-root ownership
is compared with `/usr` ownership because guest root is unmapped in RootlessKit's
user namespace.

## Recorded network validation — 2026-09-08

The 2026-09-08 fixture reproduced working same-network HTTP/name lookup and
cross-bridge isolation. Prohibited route lookups failed, container root could not
delete routes or re-enable IPv6, and a stale digest prevented process startup;
a subsequent valid startup succeeded.

The initial blanket `10.0.0.0/8` prohibition also blocked RootlessKit's synthetic
DNS endpoint. The explicit port-scoped allowance fixes that failure: public HTTP
and TCP/UDP DNS succeed, while TCP/UDP ports 22, 54, 80, and 443 at the DNS address
are rejected by policy. The exception does not permit arbitrary access to that IP.
The fresh-instance probe passed before and after VM reboot without reinstalling
policy, including rejection of a correctly hashed policy with the wrong DNS IP
and successful startup after restoring the valid policy.

The nerdctl 2.3.5 / slirp4netns 1.3.5 fixture passed owned-host denial, authorized
internal relay access, root and restricted-proxy egress, internal IPv6 checks,
and partial-policy cleanup before and after reboot. The separate live-child
interruption tests passed during both startup and probing, preserving status 143
and removing their owned VMs. The four installer tests passed, including checksum
rejection, interrupted download cleanup, and reuse without another download.

Route inspection is not proof of endpoint behavior for every prohibited range.
These network results do not establish daily-use readiness. The host and launcher
have their own integration fixtures; `dev/test --lima` runs the nerdctl host gate,
not the Docker gates. The nerdctl backend remains opt-in.
