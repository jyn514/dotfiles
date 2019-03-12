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
		apt-get install vim git build-essential cowsay default-jre shellcheck nmap texlive-base python3-pip graphviz xdot xdg-utils traceroute
		fi
}

install_security () {
	echo Installing security updates
	apt-get update
	apt-get install unattended-upgrades
	# for some reason Ubuntu disables unattended upgrades for security repos (!!)
	if ! apt-config dump | grep 'Unattended-Upgrade::Allowed-Origins::.*-security' >/dev/null; then
	echo // added automatically by setup.sh on "$(date -I)" '
Unattended-Upgrade::Allowed-Origins {
	"${distro_id}:${distro_codename}-security";
}' >> /etc/apt/apt.conf.d/50unattended-upgrades
	fi
	echo this may take a while...
	unattended-upgrades -v
}

. "$(dirname "$(realpath "$0")")"/lib.sh
if exists dpkg; then
	IS_DEB=true
else
	echo "$0: Unsupported distro"
	exit 1
fi

install_security
install_features
