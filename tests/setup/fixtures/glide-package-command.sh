#!/bin/sh
command_name=${0##*/}
printf '%s' "$command_name" >> "$GLIDE_TEST_LOG"
for argument do
	printf ' <%s>' "$argument" >> "$GLIDE_TEST_LOG"
done
printf '\n' >> "$GLIDE_TEST_LOG"
case "$command_name ${1:-}" in
	'pacman -Q') exit "${GLIDE_TEST_INSTALLED:-1}";;
	'pacman -Si') exit "${GLIDE_TEST_REPOSITORY:-1}";;
	*) exit "${GLIDE_TEST_INSTALL_STATUS:-0}";;
esac
