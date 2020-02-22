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
		   python3-pip graphviz xdot xdg-utils \
		   traceroute valgrind keepassxc rclone \
		   curl jq tree pkg-config libssl-dev
		PACKAGES=
		# TODO: this should work for platforms besides amd64 :(
		if ! exists bat; then
			VERSION="$(latest_release sharkdp/bat)"
			VERSION_NO_V="$(echo "$VERSION" | tr -d v)"
			download https://github.com/sharkdp/bat/releases/download/"$VERSION/bat_$VERSION_NO_V"_amd64.deb bat.deb
			PACKAGES="$PACKAGES ./bat.deb"
		fi
		if ! exists rg; then
			VERSION="$(latest_release BurntSushi/ripgrep)"
			download https://github.com/burntsushi/ripgrep/releases/download/"$VERSION"/ripgrep_"$VERSION"_amd64.deb rg.deb
			PACKAGES="$PACKAGES ./rg.deb"
		fi
		if [ -n "$PACKAGES" ]; then
			chmod a+r $PACKAGES
			apt install $PACKAGES
		fi
	fi
}

install_security () {
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
	apt autoremove --purge apt-xapian-index
}

DIR="$(dirname "$(realpath "$0")")"
. "$DIR"/lib.sh
if exists dpkg; then
	IS_DEB=true
else
	echo "$0: Unsupported distro"
	exit 1
fi

set -x
install_security
install_features
remove_unwanted
set +x
