# Native nftables differential probes

New Lima-Docker VMs install [network.nft](../../lima/docker/network.nft).
Docker keeps its iptables backend. The sandbox owns two native tables:
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
historical `legacy_policy.py`, and with the installed policy source. The 26 cases
cover public/private access, UDP DNS, gateway access, relay isolation, IPv6, and forged Ethernet packets that
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

## Runtime boundary

These probes complement [runtime verification and container tests](../../lima/docker.md#disposable-validation).
Provisioning pins `userland-proxy=true`, rejects `icc=false`
networks, and verifies both sysctls after network creation and daemon activation.
Docker can otherwise restore bridge traversal and break legitimate relay traffic.
Do not disable bridge traversal on an arbitrary Docker installation: it can
change inter-container filtering and published-port behavior.

The private-daemon probe tests network creation. The runtime tests separately
cover native JSON verification, restart and failed activation, TCP DNS,
same-bridge traffic, forged packets, and interactive Pi launch and cleanup.
