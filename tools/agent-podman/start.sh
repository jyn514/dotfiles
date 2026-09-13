#!/bin/sh
set -eu

SAFE_PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
PATH=$SAFE_PATH
export PATH
unset CDPATH ENV BASH_ENV ZDOTDIR

SCRIPT_PATH=$(/bin/realpath "$0")
SCRIPT_DIR=$(CDPATH='' cd -P -- "$(dirname -- "$SCRIPT_PATH")" && pwd -P)
CONFIG=$SCRIPT_DIR/agent-podman.conf
[ -f "$CONFIG" ] && [ ! -L "$CONFIG" ] || { printf 'error: missing adjacent-deployment configuration: %s\n' "$CONFIG" >&2; exit 1; }
# shellcheck source=agent-podman.conf
. "$CONFIG"

PODMAN_BIN=${AGENT_PODMAN_BIN:-}
if [ -z "$PODMAN_BIN" ]; then
  PODMAN_BIN=$(command -v podman) || { printf 'error: podman is not installed or not on PATH\n' >&2; exit 1; }
fi
case $PODMAN_BIN in /*) ;; *) printf 'error: AGENT_PODMAN_BIN must be absolute\n' >&2; exit 1 ;; esac
[ -x "$PODMAN_BIN" ] || { printf 'error: Podman is not executable: %s\n' "$PODMAN_BIN" >&2; exit 1; }

/usr/bin/sudo -u "$ACCOUNT" /usr/bin/env -i \
  HOME="$ACCOUNT_HOME" USER="$ACCOUNT" LOGNAME="$ACCOUNT" \
  CONTAINERS_CONF="$ACCOUNT_HOME/.config/containers/containers.conf" \
  PATH="$(dirname "$PODMAN_BIN"):$SAFE_PATH" \
  "$PODMAN_BIN" machine start "$MACHINE"
