#!/bin/sh
set -eu
printf 'Startup boundary: container entry\n' >&2
exec /opt/agent-tools/bin/with-github-token /bin/sh /startup-probe/startup-command.sh "$@"
