# Prototype native nftables isolation

Experimental packet-policy replacement; the launcher and VM provisioner do not
use it. Docker keeps its iptables backend. `policy.nft` owns two tables:
`inet codex_sandbox` filters routed and host-bound traffic; `bridge codex_sandbox`
blocks IPv6 within sandbox bridges. Address substitutions use `network_policy.py`.

Both `bridge-nf-call-iptables` and `bridge-nf-call-ip6tables` must be zero. This
keeps bridged packets out of the IP hooks, so rejecting routed relay traffic
does not also reject ordinary traffic within the relay. No packet marks,
`physdev` matches, Docker-chain edits, or jump-order checks are needed.

## Run the probes

Run from the dotfiles checkout on an Apple Silicon host with the existing
Docker Lima VM running:

```sh
limactl shell --workdir /tmp sandbox-host-docker sudo python3 \
  "$PWD/tools/codex-sandbox/experiments/nftables/probe.py"
limactl shell --workdir /tmp sandbox-host-docker python3 \
  "$PWD/tools/codex-sandbox/experiments/nftables/docker_probe.py"
```

The first command creates fresh Linux network namespaces with no external
interface. It changes rules, routes and sysctls only there; child processes own
the peer namespaces. It runs the same packet cases without filtering, with the
existing policy, and with the candidate. The 26 cases cover public/private access,
UDP DNS, gateway access, relay isolation, IPv6, and forged Ethernet packets that
distinguish bridging from same-link routing. It also checks atomic replacement
failure and repeat installation. Positive controls prevent unroutable fixtures
from masquerading as successful denials.

`rejected-output.nft` preserves a disproved candidate. Its bridge output hook
cannot see the original ingress interface; three egress-routing leaks must
reproduce for this negative control to pass.

The second command starts a separate rootless Docker daemon with temporary
state, socket and RootlessKit namespaces. It creates no containers, imports no
credentials, and changes no systemd units. Ordinary public/internal/egress
network creation leaves both sysctls at zero. Creating an `icc=false` network
re-enables IPv4 bridge filtering. The probe stops its daemon and removes its
temporary state on exit.

## Migration boundary

This is a packet-policy prototype, not a replacement for runtime verification.
Before deployment, pin and verify `userland-proxy=true`, reject `icc=false`
networks, and verify both sysctls after network creation and daemon activation.
Docker can otherwise restore bridge traversal and break legitimate relay traffic.
Do not disable bridge traversal on an arbitrary Docker installation: it can
change inter-container filtering and published-port behavior.

A migration still needs installed-policy verification using nftables JSON,
provisioning snapshots, restart/failure coverage, and full launcher tests with
actual containers. The private-daemon probe tests network creation, not those
container, NAT or lifecycle behaviors; TCP DNS and public same-bridge traffic
also need coverage. Keep the existing firewall until those checks pass.
