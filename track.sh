#!/bin/sh
set -e

cd "$(dirname "$0")"
exec python3 lib/track_file.py "$@"
