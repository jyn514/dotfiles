#!/bin/sh
set -eu

# The worker wrapper must not pass the caller's agent state to Pi.
[ ! -e "$HOME/caller-agent" ] || exit 89
[ "${PI_OFFLINE:-}" = 1 ] || exit 90
[ "${PI_CODING_AGENT_DIR:-}" = "$HOME/agent" ] || exit 91
[ "${PI_CODING_AGENT_SESSION_DIR:-}" = "$HOME/sessions" ] || exit 92
[ "${NODE_COMPILE_CACHE:-}" = "$HOME/node-cache" ] || exit 93
[ "${XDG_CACHE_HOME:-}" = "$HOME/cache" ] || exit 94
[ "${TMPDIR:-}" = "$HOME/tmp" ] || exit 95
[ ! -e "$HOME/.pi" ] || exit 96
[ "${1:-}" = --offline ] || exit 97
shift

case "$#:${1:-}" in
	1:--help) printf 'Usage: pi [options]\n' ;;
	1:--version) printf '0.85.1\n' ;;
	*) exit 98 ;;
esac
