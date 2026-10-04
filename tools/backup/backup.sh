#!/bin/sh

# Installation, credentials, and restore instructions: tools/backup/README.md.
# backup check-subset checks repository metadata and 5% of its data.
# backup prune applies the retention policy below and removes unreferenced data.
# Documents snapshots have one root: BACKUP_DOCUMENTS. Restore with
# `restic restore latest --tag documents-backup --target TARGET`; its contents
# are restored directly beneath TARGET.
# Set HEALTHCHECKS_URL in restic.env to receive start, success, and failure pings.

set -eu

usage() {
  echo "usage: sudo -u restic backup [backup|check-subset|prune] [restic arguments...]" >&2
	exit 2
}

if ! [ "$(whoami)" = restic ]; then
	usage
fi

backup_home=${BACKUP_HOME:-$(cd ~jyn && pwd)}
restic_home=${RESTIC_HOME:-$(cd ~restic && pwd)}
restic_env=${RESTIC_ENV_FILE:-$backup_home/.local/config/restic.env}
# The path is configurable for testing and alternate hosts.
# shellcheck disable=SC1090
. "$restic_env"

cache_dir=${RESTIC_CACHE_DIR:-$restic_home/cache}
documents=${BACKUP_DOCUMENTS:-$backup_home/Documents}
backup_tag=${BACKUP_TAG:-documents-backup}

restic() {
	command "${RESTIC_BINARY:-restic}" "$@"
}

case "${1:-}" in
backup|check-subset|prune)
	command=$1
	shift
	;;
""|-*) command=backup;;
*) command=$1;;
esac

ping() {
	[ -n "${HEALTHCHECKS_URL:-}" ] || return 0
	suffix=${1:+/$1}
	if ! curl -fsS --retry 3 --max-time 10 "$HEALTHCHECKS_URL$suffix" >/dev/null; then
		echo "backup: healthcheck ping failed: ${1:-success}" >&2
	fi
}

finish() {
	result=$?
	trap - EXIT HUP INT TERM
	if [ "$result" -eq 0 ]; then
		ping ""
	else
		echo "backup: $command failed with status $result" >&2
		ping fail
	fi
	exit "$result"
}

trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
ping start

case "$command" in
backup)
	if [ -n "${BACKUP_HOST:-}" ]; then
		set -- --host "$BACKUP_HOST" "$@"
	fi
	# Explicit roots (Mica) include notes; the historical exclusion is Documents-only.
	if [ -z "${BACKUP_ROOT:-}" ]; then
		set -- --exclude notes/ "$@"
	fi
	cd "${BACKUP_ROOT:-$documents}"
	restic backup --skip-if-unchanged \
		--cache-dir "$cache_dir" --tag "$backup_tag" "$@" .
	;;
check-subset)
	restic check --read-data-subset=5% "$@"
	;;
prune)
	restic forget --cache-dir "$cache_dir" \
		--tag "$backup_tag" \
		--keep-daily 7 --keep-weekly 5 --keep-monthly 12 --keep-yearly 3 \
		--prune "$@"
	restic check
	;;
*)
	restic "$@"
esac
