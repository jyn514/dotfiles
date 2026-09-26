#!/bin/sh
# Lima discovers this daemon through the private QEMU vhost-user directory.
set -eu

: "${CODEX_SANDBOX_VIRTIOFSD:?missing virtiofsd executable}"
case "${1:-}" in
	--version) exec "$CODEX_SANDBOX_VIRTIOFSD" "$@" ;;
esac
: "${CODEX_SANDBOX_UID_MAP:?missing virtiofs UID map}"
: "${CODEX_SANDBOX_GID_MAP:?missing virtiofs GID map}"
exec "$CODEX_SANDBOX_VIRTIOFSD" "--uid-map=$CODEX_SANDBOX_UID_MAP" \
	"--gid-map=$CODEX_SANDBOX_GID_MAP" "$@"
