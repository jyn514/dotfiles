#!/bin/sh

dump() {
	# dconf only shows modified keys, although this appears to be undocumented
	dpath=$1
	dconf dump /"$dpath"/ | rg -v EVOLUTION-CALDAV | sed "s#^\[\([^]]*\)\]#[$dpath/\1]#;"' s#/\+\]$#]#'
	echo
}

# from dconf dump / | rg Super -B2 | rg '^\['
dump org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
dump org/gnome/desktop/wm/keybindings
dump org/gnome/shell/keybindings
dump org/gnome/shell/extensions/pop-shell
dump desktop/ibus/panel/emoji
