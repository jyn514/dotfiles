#!/bin/sh

set -e

# this script is very opinionated. you may not want to run everything here.

install_features () {
	if [ -n "$IS_DEB" ]; then
		# thanks to https://github.com/zulip/zulip/pull/10911/files
		if ! apt-cache policy | grep -q "l=Ubuntu,c=universe"; then
			add-apt-repository universe
			apt-get update
		fi
		apt-get install -y vim git build-essential cowsay shellcheck nmap \
		   python3-pip graphviz xdot xdg-utils \
		   traceroute valgrind keepassxc rclone \
		   curl jq tree pkg-config libssl-dev manpages manpages-dev bpytop git-absorb \
		   ninja-build

		# https://learn.microsoft.com/en-us/powershell/scripting/install/install-ubuntu
		if ! exists pwsh; then
			# Download the Microsoft repository GPG keys
			wget -q "https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/packages-microsoft-prod.deb"
			# Register the Microsoft repository GPG keys
			sudo dpkg -i packages-microsoft-prod.deb
			# Update the list of packages after we added packages.microsoft.com
			sudo apt-get update
			# Install PowerShell
			sudo apt-get install -y powershell
		fi

		if ! exists code; then
			download https://go.microsoft.com/fwlink/?LinkID=760868 code.deb
			sudo apt install ./code.deb
		fi
	elif [ -n "$IS_ALPINE" ]; then
		# Use GNU less so Delta works properly
		apk add less py3-pip
	fi
}

install_security () {
	if ! [ -n "$IS_DEB" ]; then
		return
	fi
	apt-get update
	apt-get install unattended-upgrades iptables-persistent
	DEST=/etc/iptables/rules.v4
	force=y
	if [ -e "$DEST" ]; then
		set +x
		printf "$DEST already exists, overwrite? y/[n]: "
		read -r force
		set -x
		[ "$force" = y ] && mv "$DEST" "$DEST".bak
	fi
	[ "$force" = y ] && ln -s "$DIR/iptables" "$DEST" || true
	iptables-restore "$DIR/iptables"
	unattended-upgrades
}

remove_unwanted () {
	if ! [ -n "$IS_DEB" ]; then
		return
	fi
	apt autoremove --purge apt-xapian-index
}

DIR="$(dirname "$(realpath "$0")")"
. "$DIR"/lib.sh
if exists dpkg; then
	IS_DEB=1
elif exists apk; then
	IS_ALPINE=1
else
	echo "$0: Unsupported distro"
	exit 1
fi

set -x
install_security
install_features
remove_unwanted
set +x
