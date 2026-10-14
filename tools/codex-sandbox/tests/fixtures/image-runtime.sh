#!/bin/sh
set -eu
sha256sum /opt/agent-tools/libexec/jj
node --version
cat /opt/agent-pi/REVISION
/opt/agent-pi/bin/pi --version
bun --version
bun test /opt/agent-pi/check-bun.test.ts >/dev/null
printf 'bun-test-ok\n'
# sh -c leaves stdin available for the wrapper probe supplied by the caller.
exec /opt/agent-tools/libexec/bb --file /dev/stdin
