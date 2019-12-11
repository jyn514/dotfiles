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
		apt-get install vim git build-essential cowsay shellcheck nmap \
		   texlive-base python3-pip graphviz xdot xdg-utils \
		   traceroute valgrind keepassxc rclone \
		   curl jq
		if ! exists bat; then
			download "$(latest_version sharkdp/bat)" bat.deb
			PACKAGES="$PACKAGES bat.deb"
		fi
		if ! exists rg; then
			download "$(latest_version BurntSushi/ripgrep)" rg.deb
			PACKAGES="$PACKAGES rg.deb"
		fi
		[ -n "$PACKAGES" ] && apt install $PACKAGES
	fi
}

install_security () {
	apt-get update
	apt-get install unattended-upgrades iptables-persistent
	DEST=/etc/iptables/rules.v4
	force=y
	if [ -e "$DEST" ]; then
		printf "$DEST already exists, overwrite? y/[n]: "
		read -r force
		[ "$force" = y ] && mv "$DEST" "$DEST".bak
	fi
	[ "$force" = y ] && ln -s "$DIR/iptables" "$DEST" || true
	iptables-restore "$DIR/iptables"
	unattended-upgrades
}

remove_unwanted () {
	dpkg --purge apt-xapian-index
	purge
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
remove_unwanted
