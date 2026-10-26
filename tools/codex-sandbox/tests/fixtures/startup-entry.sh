#!/bin/sh
set -eu
printf 'Startup boundary: container entry\n' >&2
printf 'Startup boundary: agent command\n' >&2
exec /opt/agent-tools/bin/with-github-token "$@"
