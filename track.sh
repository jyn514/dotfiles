#!/bin/sh
set -e

cd "$(dirname "$0")"
exec python3 libexec/track_file.py "$@"
