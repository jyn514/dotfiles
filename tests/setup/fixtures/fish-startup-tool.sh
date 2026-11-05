#!/bin/sh
# shellcheck disable=SC2016 # Emit Fish code for the caller to expand later.
case ${0##*/} in
	cargo) printf '%s\n' 'Installed Commands:';;
	bat) printf '%s\n' 'bat 0.25.0';;
	atuin) printf '%s\n' 'function _atuin_search; end';;
	zoxide) printf '%s\n' 'function __zoxide_z; builtin cd $argv; end; function z; builtin cd $argv; end';;
	direnv) ;;
	*) exit 2;;
esac
