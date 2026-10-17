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
	should_copy_global "$FIXTURE_NAME" "$FIXTURE_DEST"
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
