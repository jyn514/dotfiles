# Lima network feasibility

The outer runtime remains Podman. This opt-in prototype tests container-level
network restrictions for a possible Lima migration; it is not a production
provisioning tool or a completed network gate.

## Run the probe

On Apple Silicon macOS with Lima 1.2.1 installed:

```sh
python3 tools/codex-sandbox/tests/lima_policy_test.py
python3 tools/codex-sandbox/tests/lima_network_integration.py --reboot > /tmp/lima-network.log 2>&1
```

The integration command creates a uniquely named VM with no host shares or
forwarded SSH agent. It downloads a digest-pinned Ubuntu 24.04 image, the same
nerdctl 2.1.3 bundle used by the installed Lima template, and a digest-pinned
official Python/Alpine test image. These fixture pins are not the production
version selection required before migration. Ubuntu's archived guest image uses HTTP;
Lima must verify its SHA-256 before booting it.

The command prints the owned VM name before creation and deletes that VM on
success or failure. Use `--keep` to stop and retain it for inspection instead.
If cleanup fails or the host process is killed before cleanup, inspect the
printed instance name and remove only that instance with
`limactl delete --force INSTANCE`. It never selects `ferrocene` or a real session.
`--reboot` repeats the probes after a VM stop/start without reinstalling the policy.

## Explicit DNS configuration

[rootless-network.json](rootless-network.json) pins the existing slirp4netns
subnet `10.0.2.0/24` and its derived DNS endpoint `10.0.2.3`. Setup verifies the
effective driver, DNS, and child address before adding a persistent containerd
service override for `--cidr=10.0.2.0/24`. It refuses custom flags it would replace
and verifies that no other RootlessKit arguments changed after restart.
The slirp4netns implementation and Lima VM networks are unchanged.

Workloads explicitly select this DNS address. Nerdctl may list it twice because
it also prepends RootlessKit's DNS; duplicate entries do not grant extra access.

## Policy ownership

The fixture extracts the launcher's literal `PROHIBITED_ROUTES` without executing
launcher code. The launcher remains the single CIDR authority until migration.
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

## Current probe status

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

The full gate also still requires owned host endpoints, internal relay links,
interruption/partial-policy cleanup and representative proxy checks.
Route inspection is not proof of all endpoint behavior. No launcher selector,
credential migration, production VM setup, or default switch is implemented.
