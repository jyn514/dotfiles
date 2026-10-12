# Agent forwarding alongside mosh

Mosh closes its bootstrap SSH connection, so normal agent forwarding disappears before the terminal session starts.
`mosh-agent HOST` keeps a separate SSH connection open for the lifetime of mosh and configures the remote session's agent automatically.
It requires POSIX sh, OpenSSH with Unix socket forwarding, autossh, and mosh on the local machine.
Only use it with a trusted remote account: that account can use your agent while the tunnel is connected.

## Setup and usage

Install autossh through your normal OS package manager.
Run `bin/mosh-agent` from this checkout, or put that directory on PATH.
On the server, the administrator must enable these sshd settings:

```text
AllowStreamLocalForwarding yes
StreamLocalBindUnlink yes
```

The first setting normally defaults to yes.
The second lets sshd replace a socket left by a disconnected tunnel; setting it in the client does not change server behavior.
Restrict these settings to your account with `Match User USER` if needed.
Validate with `sshd -t`, reload the host's SSH service, and verify the effective settings with `sshd -T -C user=USER,host=HOST,addr=CLIENT_IP`.
Keep your current SSH connection open while checking a new connection.

Run this from the machine with your agent:

```sh
mosh-agent devbox
```

Host aliases and authentication use the normal SSH configuration.
The wrapper discovers the remote home directory through SSH and uses `~/.ssh/mosh-agent.sock` there.
The remote `.ssh` directory must already exist and be private to your account.
Mosh starts with `SSH_AUTH_SOCK` set to this path; no remote shell configuration is needed.
Ordinary SSH sessions keep their normal agent selection.
Remove any global fixed-socket override added for the earlier two-argument version.
Existing tmux panes keep their old environment; set `SSH_AUTH_SOCK` to this path once in those panes, or start new shells from the mosh session.
The local agent must be available through `SSH_AUTH_SOCK`; an `IdentityAgent` setting alone does not select the socket being forwarded.
Use one wrapper per remote account at a time, including across laptops and host aliases.
A second tunnel would replace the first tunnel's socket.
Mosh options and remote command arguments are deliberately outside this initial interface.

## Design

The wrapper checks its arguments, executables, and local agent before starting the tunnel or mosh.
It runs a checked SSH command to expand the socket path using the remote login shell's `HOME`.
Discovery failure stops startup without leaving children running.
The relative socket path has one owner in the wrapper; discovery and mosh's environment command both use it.
It starts autossh in the background without daemonizing it, forwarding the discovered socket to the local `SSH_AUTH_SOCK`.
SSH multiplexing is disabled for this connection so its lifetime belongs to the wrapper.
SSH runs without a remote command and uses batch authentication, a connection timeout, and keepalive checks.
Autossh retries initial failures and restarts SSH after disconnects.
The wrapper then runs mosh with its ordinary terminal input and output.
Mosh's `--server` command invokes `env SSH_AUTH_SOCK=... mosh-server`, expanding the same path remotely without writing configuration.
On normal exit or HUP, INT, or TERM, it stops and waits for autossh, which stops its SSH child.
It preserves mosh's exit status, or the conventional signal exit status.

After laptop sleep, mosh resumes its terminal session independently.
Autossh reconnects the tunnel, and sshd replaces the old socket at the same path.
Existing tmux shells keep using that path without an environment refresh.
Agent operations fail while the tunnel is disconnected and can be retried after reconnect.
Startup is asynchronous: opening mosh does not prove that the tunnel is ready.
Run `ssh-add -l` remotely to check readiness; autossh and SSH diagnostics stay on the local terminal.
The wrapper does not remove the remote socket on exit; it becomes unusable until the next tunnel replaces it.
It does not change remote configuration, install dependencies, or manage tmux.

## Verification

Run `dev/test-environment python3 tools/mosh-agent/tests/mosh_agent_test.py` from the checkout.
These tests exercise the executable with disposable command fixtures: prerequisites, remote discovery, child ownership, exit status, and termination.
When mosh is installed, a native bootstrap test verifies its `--server` command sets the remote environment using disposable SSH, server, and client fixtures.
They are discovered by the repository's normal pytest configuration.
Shellcheck validates the shell wrapper.
Real acceptance requires starting the wrapper from the local agent machine, checking `ssh-add -l` remotely, reconnecting the network, and checking again from the same tmux pane.
That live check also establishes that the running sshd loaded the socket replacement setting.

## References

- [Mosh's connection lifecycle](https://github.com/mobile-shell/mosh#how-it-works)
- [OpenSSH remote socket forwarding](https://man.openbsd.org/ssh_config#RemoteForward)
- [Server socket replacement](https://man.openbsd.org/sshd_config#StreamLocalBindUnlink)
- [Autossh lifecycle and monitoring](https://www.harding.motd.ca/autossh/README.txt)
