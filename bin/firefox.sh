#!/bin/sh
firefox=${FIREFOX:-'/mnt/c/Program Files/Mozilla Firefox/firefox.exe'}
exec "$firefox" "$(wslpath -w "$1")"
