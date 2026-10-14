#!/bin/sh
set -eu
/trusted/bin/busybox sha256sum /trusted/bin/jj
export HOME=/tmp/home
busybox mkdir -p "$HOME"
cd /tmp
jj git init --colocate main
cd main
jj workspace add --colocate ../linked
cd /tmp
test -f linked/.git
test "$(git -C linked rev-parse --show-toplevel)" = /tmp/linked
jj -R linked status
printf 'jj-colocated-ok\n'
