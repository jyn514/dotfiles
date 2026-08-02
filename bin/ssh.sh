#!/bin/sh
# setup:
# 1. `sudo ln -s ~/work/udp-vpn/config.conf /etc/openvpn/client/yottadb.conf`
# 2. set `ProtectHome=read-only` in `/usr/lib/systemd/system/openvpn-client@.service`
# 3. copy over /etc/hosts
# 4. set windows terminal to `wsl.exe ~/work/ssh.sh dst tmux`
s=openvpn-client@yottadb
agent_started=
vpn_started=
cleanup() {
	result=$?
	trap - EXIT HUP INT TERM
	if [ -n "$vpn_started" ]; then
		sudo systemctl stop "$s" || true
	fi
	if [ -n "$agent_started" ]; then
		ssh-agent -k >/dev/null || true
	fi
	exit "$result"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if ! ssh-add -l >/dev/null 2>&1; then
	agent_env=$(ssh-agent -s) || exit
	eval "$agent_env" || exit
	unset agent_env
	agent_started=1
	ssh-add
	ssh-add -l
fi
if ! systemctl is-active "$s" >/dev/null; then
	sudo systemctl start "$s"
	vpn_started=1
	# hack: wait for dns server to startup
	# i tried doing this the "proper" way with openvpn3 but it's horribly broken (it has a stateful "import" mechanism that doesn't work)
	sleep 3
fi
ssh -At "$@"
