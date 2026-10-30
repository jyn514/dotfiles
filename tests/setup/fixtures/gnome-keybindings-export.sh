#!/bin/sh
set -eu

root=$1
selection=$2
media_keys=/org/gnome/settings-daemon/plugins/media-keys

dconf load / < "$root/lib/gnome-keybindings.ini"
dconf reset "$media_keys/custom-keybindings"
dconf write "$media_keys/unrelated" "'not-exported'"
if [ -n "$selection" ]; then
	gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$selection"
fi
"$root/dev/dump-gnome-keybindings"
