#!/bin/sh
set -eu

# Run on the macOS host. Account and machine targets are fixed and provenance-checked.

SAFE_PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
PATH=$SAFE_PATH
export PATH
IFS=' 	
'
umask 077
unset CDPATH ENV BASH_ENV ZDOTDIR

ACCOUNT=_agentpodman
ACCOUNT_GROUP=_agentpodman
MACHINE=agent-podman
ACCOUNT_HOME=/Users/$ACCOUNT
MARKER_DIR=/var/db/agent-podman
MARKER=$MARKER_DIR/$ACCOUNT
GROUP_MARKER=$MARKER_DIR/group
PF_RULES=$MARKER_DIR/pf.rules
PF_ENABLE_LOG=$MARKER_DIR/pf-enable.log
PF_ANCHOR=com.apple/000.agent-podman

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

release_network_guard() {
  if [ -e "$PF_RULES" ] || [ -L "$PF_RULES" ]; then
    [ -f "$PF_RULES" ] && [ ! -L "$PF_RULES" ] || die "unsafe PF rules marker: $PF_RULES"
    /sbin/pfctl -q -a "$PF_ANCHOR" -F rules
    [ -z "$(/sbin/pfctl -a "$PF_ANCHOR" -sr)" ] || die "PF anchor still contains rules"
    rm -f "$PF_RULES"
  fi

  if [ -e "$PF_ENABLE_LOG" ] || [ -L "$PF_ENABLE_LOG" ]; then
    [ -f "$PF_ENABLE_LOG" ] && [ ! -L "$PF_ENABLE_LOG" ] || die "unsafe PF token marker: $PF_ENABLE_LOG"
    pf_token=$(awk '$1 == "Token" && $2 == ":" { print $3 }' "$PF_ENABLE_LOG")
    case "$pf_token" in *[!0-9]*|'') die "invalid retained PF enable-reference token" ;; esac
    /sbin/pfctl -X "$pf_token"
    rm -f "$PF_ENABLE_LOG"
  fi
}

[ "$(uname -s)" = Darwin ] || die "this script must run on macOS"
[ "$(id -u)" -eq 0 ] || die "run with sudo: sudo $0"
CALLER_USER=${SUDO_USER:-}
[ -n "$CALLER_USER" ] || die "invoke this script through sudo from the owning user"
CALLER_HOME=$(dscl . -read "/Users/$CALLER_USER" NFSHomeDirectory | awk '{print $2}')
case "$CALLER_HOME" in /Users/*) ;; *) die "unexpected caller home: $CALLER_HOME" ;; esac
OUTPUT_DIR=$CALLER_HOME/.agent-podman-access
[ -d "$MARKER_DIR" ] && [ ! -L "$MARKER_DIR" ] || die "unsafe marker directory: $MARKER_DIR"
[ "$(stat -f %u "$MARKER_DIR")" = 0 ] || die "root must own $MARKER_DIR"
[ "$(stat -f %Lp "$MARKER_DIR")" = 700 ] || die "$MARKER_DIR must have mode 700"
[ -f "$MARKER" ] && [ ! -L "$MARKER" ] || die "missing safe ownership marker: $MARKER"
IFS= read -r MARKER_HOME < "$MARKER" || die "could not read marker account home"
MARKER_OUTPUT=$(tail -n +2 "$MARKER" | head -n 1)
[ "$MARKER_HOME" = "$ACCOUNT_HOME" ] || die "marker account home mismatch"
[ "$MARKER_OUTPUT" = "$OUTPUT_DIR" ] || die "marker access directory mismatch"

run_worker() {
  /usr/bin/sudo -u "$ACCOUNT" \
    /usr/bin/env -i HOME="$ACCOUNT_HOME" USER="$ACCOUNT" LOGNAME="$ACCOUNT" \
    CONTAINERS_CONF="$ACCOUNT_HOME/.config/containers/containers.conf" \
    PATH="$PODMAN_DIR:$SAFE_PATH" \
    "$PODMAN_BIN" "$@"
}

if dscl . -read "/Users/$ACCOUNT" >/dev/null 2>&1; then
  RECORDED_HOME=$(dscl . -read "/Users/$ACCOUNT" NFSHomeDirectory | awk '{print $2}')
  [ "$RECORDED_HOME" = "$ACCOUNT_HOME" ] || die "account home mismatch: $RECORDED_HOME"
  ACCOUNT_UID=$(id -u "$ACCOUNT")

  # Setup creates the home before its first Podman call. No home means there
  # can be no script-created machine to inventory.
  if [ -e "$ACCOUNT_HOME" ] || [ -L "$ACCOUNT_HOME" ]; then
    [ -d "$ACCOUNT_HOME" ] && [ ! -L "$ACCOUNT_HOME" ] || die "unsafe worker home: $ACCOUNT_HOME"
    PODMAN_BIN=${AGENT_PODMAN_BIN:-}
    if [ -z "$PODMAN_BIN" ]; then
      PODMAN_BIN=$(command -v podman) || die "podman is not installed or not on PATH"
    fi
    case "$PODMAN_BIN" in /*) ;; *) die "AGENT_PODMAN_BIN must be an absolute path" ;; esac
    [ -x "$PODMAN_BIN" ] || die "Podman executable is not executable: $PODMAN_BIN"
    PODMAN_DIR=$(dirname "$PODMAN_BIN")

    MACHINE_LIST=$(run_worker machine list --format '{{.Name}}') || \
      die "could not list Podman machines; retaining provenance"
    if printf '%s\n' "$MACHINE_LIST" | grep -qxF "$MACHINE"; then
      run_worker machine rm --force "$MACHINE"
    fi

    MACHINE_LIST=$(run_worker machine list --format '{{.Name}}') || \
      die "could not verify Podman machine removal"
    if printf '%s\n' "$MACHINE_LIST" | grep -qxF "$MACHINE"; then
      die "Podman machine still exists; retaining account and ownership marker"
    fi
  fi

  if pgrep -U "$ACCOUNT_UID" >/dev/null 2>&1; then
    die "worker processes remain after VM removal; retaining the account"
  fi

  release_network_guard

  sysadminctl -deleteUser "$ACCOUNT" -secure
  if dscl . -read "/Users/$ACCOUNT" >/dev/null 2>&1; then
    die "worker account still exists; retaining ownership marker"
  fi
  [ ! -e "$ACCOUNT_HOME" ] && [ ! -L "$ACCOUNT_HOME" ] || \
    die "worker home still exists; retaining ownership marker"
else
  [ ! -e "$ACCOUNT_HOME" ] && [ ! -L "$ACCOUNT_HOME" ] || \
    die "worker account is absent but its home remains"
  release_network_guard
fi

if [ -e "$GROUP_MARKER" ] || [ -L "$GROUP_MARKER" ]; then
  [ -f "$GROUP_MARKER" ] && [ ! -L "$GROUP_MARKER" ] || die "unsafe group marker: $GROUP_MARKER"
  RECORDED_GROUP=$(head -n 1 "$GROUP_MARKER")
  [ "$RECORDED_GROUP" = "$ACCOUNT_GROUP" ] || die "group marker mismatch"
  if dscl . -read "/Groups/$ACCOUNT_GROUP" >/dev/null 2>&1; then
    dseditgroup -o delete -q -n . "$ACCOUNT_GROUP"
  fi
  if dscl . -read "/Groups/$ACCOUNT_GROUP" >/dev/null 2>&1; then
    die "worker group still exists; retaining provenance"
  fi
  rm -f "$GROUP_MARKER"
fi

rm -f "$MARKER"
rmdir "$MARKER_DIR" 2>/dev/null || true
printf 'Verified removal of machine %s, account %s, its group, and PF rules.\n' "$MACHINE" "$ACCOUNT"
printf 'Remove caller-owned credentials yourself after inspection:\n'
printf '  rm -f %s/id_ed25519 %s/id_ed25519.pub %s/known_hosts %s/connection.env\n' \
  "$OUTPUT_DIR" "$OUTPUT_DIR" "$OUTPUT_DIR" "$OUTPUT_DIR"
printf '  rmdir %s\n' "$OUTPUT_DIR"
