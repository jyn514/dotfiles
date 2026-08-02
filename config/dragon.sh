#!/bin/sh

if [ "$#" -ne 1 ]; then
	printf 'usage: dragon.sh <path-or-URI>\n' >&2
	exit 2
fi

# Dragon treats every dash-prefixed argument as an option and does not support
# an option terminator. Make relative filenames unambiguously positional.
case $1 in
	-*) set -- "./$1";;
esac

exec dragon -x "$1"
