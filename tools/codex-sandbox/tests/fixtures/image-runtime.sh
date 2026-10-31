#!/bin/sh
set -eu
probe_root=$(mktemp -d)
tar -xf - -C "$probe_root"
test -L /opt/agent-pi/standalone
if [ -e /etc/alpine-release ]; then
    test ! -e /opt/agent-pi/standalone/pi
else
    test -f /opt/agent-pi/standalone/pi
fi
test -d /opt/agent-pi/src/packages/coding-agent/docs
test -d /opt/agent-pi/src/packages/coding-agent/examples
test ! -e /opt/agent-pi/src/node_modules/typescript/package.json
test ! -d /opt/agent-pi/src/scripts
if [ -e /etc/alpine-release ]; then
    node "$probe_root/pi-runtime-package.mjs"
else
    bun "$probe_root/pi-runtime-package.mjs"
fi
bun "$probe_root/pi-runtime-worker.mjs"
if denied=$(pi --offline --print forbidden 2>&1); then
    echo 'worker container allowed a Pi session' >&2
    exit 1
else
    test "$?" -eq 64
fi
test "$denied" = 'pi is unavailable in sandbox tool-worker containers'
sha256sum /opt/agent-tools/libexec/jj
node --version
cat /opt/agent-pi/REVISION
/opt/agent-pi/bin/pi --version
bun --version
bun test /opt/agent-pi/check-bun.test.ts >/dev/null
printf 'bun-test-ok\n'
exec /opt/agent-tools/libexec/bb --file "$probe_root/wrapped_command_probe.clj"
