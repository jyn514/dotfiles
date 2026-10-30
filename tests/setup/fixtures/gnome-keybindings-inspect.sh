#!/bin/sh
set -eu

# An optional snapshot selects fresh restoration before the common inspection.
if [ "$#" -gt 0 ]; then
	dconf load / < "$1"
fi
media_keys=/org/gnome/settings-daemon/plugins/media-keys

gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
dconf read "$media_keys/custom-keybindings"
for child in PopLaunch1 custom0 custom1 custom2 custom3 custom4; do
	dconf dump "$media_keys/custom-keybindings/$child/"
done
if [ "$#" -gt 0 ]; then
	# Source has this sentinel; a correct export leaves the restored value unset.
	dconf read "$media_keys/unrelated"
fi
