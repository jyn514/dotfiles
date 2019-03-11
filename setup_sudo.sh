#!/bin/sh

set -e

# this script is very opinionated. you may not want to run everything here.

exists () {
	which "$1" >/dev/null 2>&1
	return $?;
}

# takes two parameters:
# $1 - the URL to download. required.
# $2 - the file to save to. optional. defaults to $(mktemp). specify this for max compatiblity.
download () {
	if [ -n "$2" ]; then
		OUTPUT="$2"
	else
		OUTPUT="$(mktemp)"
	fi
	if exists curl; then
		curl -L "$1" > "$OUTPUT"
	else
		wget -O "$OUTPUT" "$1"
	fi
	printf "%s" "$OUTPUT"
}

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
		apt-get update
		apt-get install vim git build-essential cowsay default-jre shellcheck nmap texlive
	fi
}

install_graphics () {
	apt-get install xdg-utils
	if ! { exists keepassxc || [ -x bin/keepassxc ]; }; then
		download "https://github.com/keepassxreboot/keepassxc/releases/download/2.3.4/KeePassXC-2.3.4-x86_64.AppImage" keepassxc
		mv keepassxc bin
		chmod +x bin/keepassxc
		OLD_USER="$USER"
		USER="$(who | awk '{print $1}')"
		chown "$USER":"$USER" bin/keepassxc
		USER="$OLD_USER"
		bin/keepassxc >/dev/null 2>&1 &
	fi
}

install_opinionated () {
	apt-get install unattended-upgrades
	ln -s "$(which bat)" ~/.local/bin/cat
}

if exists dpkg; then
	IS_DEB=true
else
	echo "$0: Unsupported distro"
	exit 1
fi


install_features
install_graphics
install_opinionated
