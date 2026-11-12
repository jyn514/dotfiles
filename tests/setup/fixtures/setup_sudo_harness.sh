#!/bin/sh

set -e

# Keep the actual script's $0 and both library sources, but never dispatch main.
mode=$1
DOAS_USER=
SUDO_USER=
dpkg() { :; }
set -- :
# shellcheck source=libexec/setup/setup_sudo.sh
. "$0"

record() {
	"$FIXTURE_PYTHON" "$FIXTURE_RECORDER" "$@"
}

if [ "$mode" = prompt ]; then
	should_copy_global "$FIXTURE_NAME" "$FIXTURE_DEST" "$FIXTURE_SOURCE"
	exit "$?"
fi

if [ "$mode" = pcscd-socket ] || [ "$mode" = pcscd-service ]; then
	exists() {
		[ "$1" = pcscd ] || [ "$1" = systemctl ]
	}
	systemctl() {
		record systemctl "$@"
		if [ "$1" = cat ] && [ "$2" = pcscd.socket ]; then
			[ "$mode" = pcscd-socket ]
		fi
	}
	setup_pcscd
	exit "$?"
fi

if [ "$mode" = reload-systemd ] || [ "$mode" = reload-no-systemd ]; then
	exists() {
		[ "$mode" = reload-systemd ] && [ "$1" = systemctl ]
	}
	systemctl() { record systemctl "$@"; }
	reload_systemd_after_globals
	exit "$?"
fi

if [ "$mode" = browser ] || [ "$mode" = browser-main ]; then
	SUDO_USER=${FIXTURE_BROWSER_INVOKER-$FIXTURE_USER}
	browser_present=${FIXTURE_BROWSER_PRESENT:-0}
	browser_groups=${FIXTURE_BROWSER_GROUPS:-browser}
	uname() { printf '%s\n' "${FIXTURE_BROWSER_OS:-Linux}"; }
	getent() {
		[ "$1" = passwd ] && [ "$2" = browser ] || return 99
		if [ -n "${FIXTURE_BROWSER_LOOKUP_FAILURE:-}" ]; then
			return "$FIXTURE_BROWSER_LOOKUP_FAILURE"
		fi
		[ "$browser_present" = 1 ] || return 2
		printf 'browser:x:%s:4321::%s:%s\n' \
			"${FIXTURE_BROWSER_UID:-4321}" \
			"${FIXTURE_BROWSER_HOME:-/var/lib/browser}" \
			"${FIXTURE_BROWSER_SHELL:-$(command -v nologin)}"
	}
	id() {
		if [ "$1" = -u ] && [ "$2" = browser ]; then
			printf '%s\n' "${FIXTURE_BROWSER_UID:-4321}"
		elif [ "$1" = -gn ] && [ "$2" = browser ]; then
			printf '%s\n' "${FIXTURE_BROWSER_PRIMARY_GROUP:-browser}"
		elif [ "$1" = -gn ] && [ "$2" = "$SUDO_USER" ]; then
			record owner-group "$2"
			if [ -n "${FIXTURE_BROWSER_GROUP_FAILURE:-}" ]; then return 17; fi
			printf '%s\n' "${FIXTURE_BROWSER_OWNER_GROUP:-desktop-group}"
		elif [ "$1" = -Gn ] && [ "$2" = browser ]; then
			printf '%s\n' "$browser_groups"
		else
			return 99
		fi
	}
	stat() { printf '%s\n' "${FIXTURE_BROWSER_HOME_STATE:-4321:700}"; }
	useradd() {
		record useradd "$@"
		if [ -n "${FIXTURE_BROWSER_USERADD_FAILURE:-}" ]; then return 19; fi
		browser_present=1
		if [ -n "$SUDO_USER" ]; then
			browser_groups="browser ${FIXTURE_BROWSER_OWNER_GROUP:-desktop-group}"
		fi
	}
	usermod() {
		record usermod "$@"
		if [ -n "${FIXTURE_BROWSER_USERMOD_FAILURE:-}" ]; then return 23; fi
		browser_groups="browser ${FIXTURE_BROWSER_OWNER_GROUP:-desktop-group}"
	}
	# Tripwires catch regressions that try to repair real account files.
	# shellcheck disable=SC2317
	chmod() { record unexpected-chmod "$@"; return 99; }
	# shellcheck disable=SC2317
	chown() { record unexpected-chown "$@"; return 99; }
	if [ "$mode" = browser-main ]; then
		# Exercise main's registration without running unrelated host setup.
		exists() { return 1; }
		install_security() { :; }
		install_device() { :; }
		copy_globals() { :; }
		reload_systemd_after_globals() { :; }
		setup_pcscd() { :; }
		remove_unwanted() { :; }
		encrypt() { :; }
		main
	else
		setup_browser_account
		if [ "${FIXTURE_BROWSER_REPEAT:-0}" = 1 ]; then setup_browser_account; fi
	fi
	exit "$?"
fi

# No privileged command or profile installation escapes this fixture.
setup_fscrypt_profile() { record setup_fscrypt_profile; }
fscrypt() { record fscrypt "$@"; }
df() {
	record df "$@"
	printf 'Filesystem\n%s\n' "$FIXTURE_DEVICE"
}
dumpe2fs() {
	record dumpe2fs "$@"
	printf 'Filesystem features: ext_attr\n'
}
tune2fs() { record tune2fs "$@"; }
mv() { record mv "$@"; }
mkdir() { record mkdir "$@"; }
chown() { record chown "$@"; }
rsync() { record rsync "$@"; }
rm() { record rm "$@"; }
cp() { record unexpected-cp "$@"; return 99; }

my_home=$FIXTURE_HOME
SUDO_USER=$FIXTURE_USER
if [ "$mode" = failed-read ]; then
	# A failed read must not authorize deletion using an old affirmative reply.
	REPLY=y
	read() { return 1; }
fi
encrypt_home_dir
