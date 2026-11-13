#!/bin/sh
set -eu
child=$SANDBOX_WORK/consumer-child
test ! -e "$child/out.tmp"
test ! -e "$child/cache/large"
test -d "$child/.jj"
test "$(cat "$child/acceptance.txt")" = 'pending tracked edit'
recorded=$("$JJ_REAL" -R "$child" --ignore-working-copy file show root:acceptance.txt)
test "$recorded" = 'pending tracked edit'
test "$(cat "$child/cache/mounted/keep.tmp")" = 'nested bind canary'
test "$(cat /home/codex/src/project/work/host-canary)" = 'host-owned'
