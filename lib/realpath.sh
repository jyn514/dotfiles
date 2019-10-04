#!/bin/sh

set -eu

startswith() {
	case "$1" in
		"$2"*) return 0;;
		*) return 1;;
	esac
}

realdir() {
	cd "$1" && pwd -P
}

realpath() {
	if [ -d "$1" ]; then
		realdir "$1"
		return
	fi
	dir="$(realdir "$(dirname "$1")")"
	if [ -L "$1" ]; then
		file="$(readlink "$1")"
	else
		file="$1"
	fi
	# absolute path, ignore directory
	if startswith "$file" /; then
		echo "$file"
		return
	fi
	echo "$dir/$file"
}
