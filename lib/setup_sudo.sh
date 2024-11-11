#!/bin/sh

set -ex

# this script is very opinionated. you may not want to run everything here.

install_features () {
	# moonlander configurer
	if [ -n "$SUDO_USER" ]; then
		usermod -aG plugdev $SUDO_USER
		ln -sf "$(realpath config/moonlander.rules)" /etc/udev/rules.d/50-zsa.rules
		t=$(download https://oryx.nyc3.cdn.digitaloceanspaces.com/keymapp/keymapp-latest.tar.gz)
		tar -xf $t
		chmod +x keymapp
		mv keymapp "$(getent passwd $SUDO_USER | cut -d: -f6)"/.local/bin/keymapp
	fi

	if [ -n "$IS_DEB" ]; then
		# thanks to https://github.com/zulip/zulip/pull/10911/files
		if ! apt-cache policy | grep -q "l=Ubuntu,c=universe"; then
			add-apt-repository universe
			apt-get update
		fi
		apt-get install -y vim git build-essential cowsay figlet shellcheck  nmap \
		   python3-pip graphviz xdot xdg-utils \
		   traceroute valgrind keepassxc rclone \
		   curl jq tree pkg-config libssl-dev manpages manpages-dev bpytop git-absorb \
		   ninja-build kakoune asciinema python3-pylsp shfmt libusb-1.0-0-dev \
		   unzip openvpn tcsh
		if is_wsl; then
			apt install -y keychain
		fi

		# https://learn.microsoft.com/en-us/powershell/scripting/install/install-ubuntu
		if ! exists pwsh; then
			# Download the Microsoft repository GPG keys
			wget -q "https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/packages-microsoft-prod.deb"
			# Register the Microsoft repository GPG keys
			dpkg -i packages-microsoft-prod.deb
			# Update the list of packages after we added packages.microsoft.com
			apt-get update
			# Install PowerShell
			apt-get install -y powershell
		fi

		if ! exists code && ! is_wsl; then
			download https://go.microsoft.com/fwlink/?LinkID=760868 code.deb
			apt install ./code.deb
		fi

		if [ "$(git --version | cut -d ' ' -f3 | cut -d. -f2)" -lt 35 ]; then
			# this often happens on WSL and borks because of zdiff3; install a newer version of git
			add-apt-repository ppa:git-core/ppa && apt update && apt install git
		fi

		if ! exists gh; then
			curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg > /usr/share/keyrings/githubcli-archive-keyring.gpg
			chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
			echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list
			apt update
			apt install gh -y
		fi
	elif [ -n "$IS_ALPINE" ]; then
		# Use GNU less so Delta works properly
		apk add less py3-pip zsh
	fi
}

install_security () {
	if ! [ -n "$IS_DEB" ]; then
		return
	fi
	apt-get update
	apt-get install -y unattended-upgrades
	unattended-upgrades || true
}

encrypt_home_dir() {
	if [ -z "$SUDO_USER" ]; then
		fail "don't know original home directory; giving up"
	fi

	my_home=$(getent passwd $SUDO_USER | cut -d: -f6)
	if fscrypt status $my_home >/dev/null; then
		return
	fi

	fscrypt setup
	# can't be a link because we're about to encrypt the home drive
	cp "$DIR"/lib/02-pam-unlock.sh /etc/profile.d
	echo ". /etc/profile" >> /etc/zsh/zshenv

	# this is the dangerous part
	backup=$(dirname $my_home)/$(basename $my_home).bak
	mv $my_home $backup
	mkdir $my_home
	fscrypt encrypt $my_home
	# we have to copy anyway to encrypt, may as well use cp instead of mv so we can confirm it's correct
	cp -a -t $backup/* $backup/.* $my_home
	echo "setup encrypted home drive; delete backup? [y/N]" >/dev/tty
	if read -r; [ "$REPLY" = y ]; then
		echo "deleting" >&2
		rm -rf $backup
	else
		echo "retaining backup in $backup" >&2
	fi
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
encrypt_home_dir
remove_unwanted
set +x
