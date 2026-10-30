#!/bin/sh
set -eu
printf 'convert\n' >> "$EXTRACT_CHAT_CONVERTER_CALLS"
exec "$EXTRACT_CHAT_PYTHON" "$@"
