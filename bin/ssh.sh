#!/bin/sh
# setup:
# 1. `ln -s ~/work/vpn/config.conf /etc/openssh/client`
# 2. disable `ProtectHome=true` in `/usr/lib/systemd/system/openvpn-client@.service`
# 3. set windows terminal to `wsl.exe ~/work/ssh.sh dst tmux`
s=openvpn-client@yottadb
if ! systemctl is-active $s >/dev/null; then 
  sudo systemctl start $s
  trap "sudo systemctl stop $s" EXIT
fi
if [ -z "$SSH_AGENT_PID" ]; then
	eval `ssh-agent`
	ssh-add
	ssh-add -l
fi
ssh -At "$@"
