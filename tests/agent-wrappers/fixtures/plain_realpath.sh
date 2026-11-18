#!/bin/sh
# Model providers such as BusyBox that accept filenames, not option markers.
if [ "$#" -ne 1 ]; then
	printf '%s\n' 'realpath fixture: expected one pathname' >&2
	exit 1
fi
case $1 in
	/*) exec "$REAL_REALPATH" "$1" ;;
	*) printf '%s\n' 'realpath fixture: expected an absolute pathname' >&2; exit 1 ;;
esac
