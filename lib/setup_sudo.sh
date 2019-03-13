#!/bin/sh

set -e

# this script is very opinionated. you may not want to run everything here.

install_features () {
	if [ -n "$IS_DEB" ]; then
		if ! exists bat; then
			download "https://github.com/sharkdp/bat/releases/download/v0.10.0/bat_0.10.0_amd64.deb" bat.deb
			PACKAGES="$PACKAGES bat.deb"
		fi
		if ! exists rg; then
			download "https://github.com/BurntSushi/ripgrep/releases/download/0.10.0/ripgrep_0.10.0_amd64.deb" rg.deb
			PACKAGES="$PACKAGES rg.deb"
		fi
		if ! exists rclone; then
			download "https://downloads.rclone.org/v1.46/rclone-v1.46-linux-amd64.deb" rclone.deb
			PACKAGES="$PACKAGES rclone.deb"
		fi
		[ -n "$PACKAGES" ] && dpkg -i $PACKAGES
		rm -f $PACKAGES
		# thanks to https://github.com/zulip/zulip/pull/10911/files
		if ! apt-cache policy | grep -q "l=Ubuntu,c=universe"; then
			add-apt-repository universe
			apt-get update
		fi
		apt-get install vim git build-essential cowsay default-jre shellcheck nmap texlive-base python3-pip graphviz xdot xdg-utils traceroute bison flex valgrind
	fi
}

install_security () {
	apt-get update
	apt-get install unattended-upgrades iptables-persistent
	DEST=/etc/iptables/rules.v4
	force=y
	if [ -e "$DEST" ]; then
		printf "$DEST already exists, overwrite? y/[n]:"
		read -r force
		[ "$force" = y ] && mv "$DEST" "$DEST".bak
	fi
	[ "$force" = y ] && ln -s "$DIR/iptables" "$DEST" || true
	iptables-restore "$DIR/iptables"
	unattended-upgrades
}

DIR="$(dirname "$(realpath "$0")")"
. "$DIR"/lib.sh
if exists dpkg; then
	IS_DEB=true
else
	echo "$0: Unsupported distro"
	exit 1
fi

install_security
install_features
