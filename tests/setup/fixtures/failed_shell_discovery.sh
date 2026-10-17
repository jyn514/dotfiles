#!/bin/sh
# Emit a plausible partial listing before the producer fails.
printf '%s\000' 'bin/unsafe.sh'
printf '%s\n' 'fixture discovery failed' >&2
exit 2
