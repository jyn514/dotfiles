#!/bin/sh
set -e

if [ $# = 0 ] || [ $# -gt 2 ]; then
  echo "usage: $0 <existing file> [basename in config/]"
  exit 1
fi

local=${2:-$(basename "$1")}

set -x
mv "$1" "config/$local"
ln -s $(realpath "config/$local") "$1"
echo "$local=$(echo "$1" | sed "s#^$HOME/##")" >> config.txt
