#!/bin/sh
# Match limactl shell's work directory and login environment; leave stdin alone.
cd /tmp || exit 1
exec "$SHELL" --login -c "$1"
