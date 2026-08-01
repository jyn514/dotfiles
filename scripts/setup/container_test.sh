#!/bin/sh
set -eu

image=${1:?usage: $0 <container-image>}
setup_command_prefix=${SETUP_COMMAND_PREFIX:-./setup.sh}

if [ -n "${CONTAINER_ENGINE:-}" ]; then
	engine=$CONTAINER_ENGINE
elif command -v podman >/dev/null 2>&1; then
	engine=podman
else
	engine=docker
fi

case $image in
	alpine:*) install='apk add --no-cache coreutils python3';;
	fedora:*) install='dnf install -y coreutils python3';;
	archlinux:*) install='pacman --sync --refresh --sysupgrade --noconfirm --disable-sandbox coreutils python';;
	ubuntu:*) install='export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y --no-install-recommends coreutils python3';;
	*) echo "$0: unsupported image: $image" >&2; exit 2;;
esac

container=$("$engine" create --env SETUP_COMMAND_PREFIX="$setup_command_prefix" --workdir /work "$image" sh -ec "
		$install
		python3 scripts/setup/setup_test.py
		python3 scripts/track/track_test.py
		python3 scripts/setup/install_test.py
		python3 scripts/setup/mise_smoke_test.py
		python3 scripts/setup/profile_test.py
")
trap '"$engine" rm --force "$container" >/dev/null' EXIT HUP INT TERM

"$engine" cp . "$container:/work"
"$engine" start --attach "$container"
