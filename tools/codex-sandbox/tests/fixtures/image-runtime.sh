#!/bin/sh
set -eu
probe_root=$(mktemp -d)
tar -xf - -C "$probe_root"
test -L /opt/agent-pi/standalone
test -f /opt/agent-pi/standalone/pi
test -d /opt/agent-pi/src/packages/coding-agent/docs
test -d /opt/agent-pi/src/packages/coding-agent/examples
test ! -e /opt/agent-pi/src/node_modules/typescript/package.json
test ! -d /opt/agent-pi/src/scripts
if [ -e /etc/alpine-release ]; then
    node "$probe_root/pi-runtime-package.mjs"
    node "$probe_root/pi-runtime-worker.mjs"
else
    # Debian's Node 20 uses the standalone Bun entrypoint for Pi.
    bun "$probe_root/pi-runtime-package.mjs"
    bun "$probe_root/pi-runtime-worker.mjs"
fi
sha256sum /opt/agent-tools/libexec/jj
node --version
cat /opt/agent-pi/REVISION
/opt/agent-pi/bin/pi --version
bun --version
bun test /opt/agent-pi/check-bun.test.ts >/dev/null
printf 'bun-test-ok\n'
exec /opt/agent-tools/libexec/bb --file "$probe_root/wrapped_command_probe.clj"
