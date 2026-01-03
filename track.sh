#!/bin/sh
set -e

dir=config
if [ "$1" = --global ]; then
	dir=global
	shift
fi

if [ $# = 0 ] || [ $# -gt 2 ]; then
  echo "usage: $0 <existing file> [basename in config/]"
  exit 1
fi

local=${2:-$(basename "$1")}
cd "$(dirname "$0")"

set -x
echo "$local=$(echo "$1" | sed "s#^$HOME/##")" >> install/$dir.txt
if [ $dir = global ]; then
	# we have to be careful here, we don't want to break the system.
	cp "$1" "$dir/$local"
	sudo lib/setup_sudo.sh copy_globals --force
else
	mv "$1" "$dir/$local"
	ln -s "$(realpath "$dir/$local")" "$1"
fi
