#!/bin/sh

set -ex

packages=

queue_install() {
	if [ "$IS_DEB" = 1 ]; then
		packages="$packages $1"
	elif [ "$IS_RPM" = 1 ]; then
		pkg="$1"
		case "$pkg" in
			manpages) pkg=man-pages ;;
			manpages-dev) return;;  # included with man-pages
			libssl-dev) pkg=openssl-devel ;;
			libusb-1.0-0-dev) return;; # not sure what this was for anyway
			python3-pylsp) pkg=python3-lsp-server ;;
			build-essential) pkg=@development-tools ;;
			*) ;;
		esac
		packages="$packages $pkg"
	elif [ "$IS_ALPINE" = 1 ]; then
	  # TODO
		packages="$packages $1"
	fi
}

# this script is very opinionated. you may not want to run everything here.

install_features () {
	# moonlander configurer
	if [ -n "$SUDO_USER" ]; then
		if [ -n "$IS_DEB" ]; then
			usermod -aG plugdev $SUDO_USER
		fi
		ln -sf "$(realpath config/moonlander.rules)" /etc/udev/rules.d/50-zsa.rules
		t=$(download https://oryx.nyc3.cdn.digitaloceanspaces.com/keymapp/keymapp-latest.tar.gz)
		tar -xf $t
		chmod +x keymapp
		mv keymapp "$(getent passwd $SUDO_USER | cut -d: -f6)"/.local/bin/keymapp
	fi

	set +x
	echo "queueing packages to install"
	for pkg in $(tr '\n' ' ' < packages.txt); do
		queue_install $pkg
	done
	set -x

	if is_wsl; then
		queue_install keychain
	fi

	if [ -n "$IS_DEB" ]; then
		# thanks to https://github.com/zulip/zulip/pull/10911/files
		if ! apt-cache policy | grep -q "l=Ubuntu,c=universe"; then
			add-apt-repository universe
			apt-get update
		fi

		# https://learn.microsoft.com/en-us/powershell/scripting/install/install-ubuntu
		if ! exists pwsh; then
			# Download the Microsoft repository GPG keys
			wget -q "https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/packages-microsoft-prod.deb"
			# Register the Microsoft repository GPG keys
			dpkg -i packages-microsoft-prod.deb
			# Install PowerShell
			queue_install powershell
		fi

		if ! exists code && ! is_wsl; then
			download https://go.microsoft.com/fwlink/?LinkID=760868 code.deb
			queue_install ./code.deb
		fi

		if [ "$(git --version | cut -d ' ' -f3 | cut -d. -f2)" -lt 35 ]; then
			# this often happens on WSL and borks because of zdiff3; install a newer version of git
			add-apt-repository ppa:git-core/ppa && queue_install git
		fi

		apt update
		apt install -y $packages
	elif [ -n "$IS_RPM" ]; then
		dnf install -y $packages
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
elif exists dnf; then
	IS_RPM=1
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
