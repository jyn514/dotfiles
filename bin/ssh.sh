#!/bin/sh
# setup:
# 1. `sudo ln -s ~/work/udp-vpn/config.conf /etc/openvpn/client/yottadb.conf`
# 2. set `ProtectHome=read-only` in `/usr/lib/systemd/system/openvpn-client@.service`
# 3. copy over /etc/hosts
# 4. set windows terminal to `wsl.exe ~/work/ssh.sh dst tmux`
s=openvpn-client@yottadb
if ! ssh-add -l >/dev/null 2>&1; then
	eval $(ssh-agent)
	ssh-add
	ssh-add -l
fi
if ! systemctl is-active $s >/dev/null; then
  sudo systemctl start $s
  trap "sudo systemctl stop $s" EXIT
	# hack: wait for dns server to startup
	# i tried doing this the "proper" way with openvpn3 but it's horribly broken (it has a stateful "import" mechanism that doesn't work)
	sleep 3
fi
ssh -At "$@"
