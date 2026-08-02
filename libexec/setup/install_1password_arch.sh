#!/bin/sh
set -eu

cd "$(dirname "$0")/../.."
. lib/shell/lib.sh

fingerprint=3FEF9748469ADBE15DA7CA80AC2D62742012EA22
workdir=$(tmp_dir 1password.XXXXXX)
trap 'rm -rf "$workdir"' EXIT HUP INT TERM
key=$workdir/1password.asc

download https://downloads.1password.com/linux/keys/1password.asc "$key"
actual=$(gpg --batch --show-keys --with-colons "$key" \
	| awk -F: '$1 == "fpr" { print $10; exit }')
if [ "$actual" != "$fingerprint" ]; then
	echo "1Password signing key fingerprint mismatch: ${actual:-missing}" >&2
	exit 1
fi
gpg --batch --import "$key"

git clone --quiet --depth=1 https://aur.archlinux.org/1password.git "$workdir/package"
if ! grep -F "$fingerprint" "$workdir/package/PKGBUILD" >/dev/null; then
	echo "1Password PKGBUILD does not require the expected signing key" >&2
	exit 1
fi
(
	cd "$workdir/package"
	makepkg --syncdeps --install --needed
)
