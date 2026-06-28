#!/bin/sh
exists () {
	command -v "$1" >/dev/null 2>&1
	return $?
}

fail() {
	echo "$@" >&2
	exit 1
}

tmp_root() {
	printf "%s" "${TMPDIR:-/tmp}"
}

tmp_file() {
	mktemp "$(tmp_root)/${1:-dotfiles.XXXXXX}"
}

tmp_dir() {
	mktemp -d "$(tmp_root)/${1:-dotfiles.XXXXXX}"
}

is_jj_repo() {
	# don't try to save the working copy, in case that hits an error
	exists jj && jj workspace root --ignore-working-copy >/dev/null 2>/dev/null
}

# takes two parameters:
# $1 - the URL to download. required.
# $2 - the file to save to. optional. defaults to $(mktemp). specify this for max compatibility.
download () {
	if [ -n "${2:-}" ]; then
		OUTPUT="$2"
	else
		OUTPUT="$(tmp_file download.XXXXXX)"
		PRINT=1
	fi
	echo "downloading $1" >&2
	if exists curl; then
		curl --location --silent "$1" > "$OUTPUT"
	else
		wget -O "$OUTPUT" "$1"
	fi
	if [ "${PRINT:-}" ]; then
		printf "%s" "$OUTPUT"
	fi
}

# get the link for the latest github release of "$1"
# $1 should have the format username/repo
latest_release() {
	curl --silent https://api.github.com/repos/"$1"/releases/latest | \
		jq --raw-output '.name'
}

is_wsl() {
	# https://superuser.com/questions/1749781/how-can-i-check-if-the-environment-is-wsl-from-a-shell-script
	[ -e /proc/sys/fs/binfmt_misc/WSLInterop ]
}

# imagine an = sign: alias python=python3
cmd_alias() {
	to=$1
	from=$2
	if ! [ -x ~/.local/bin/$to ] && exists $from; then
		ln -sf "$(command -v $from)" ~/.local/bin/$to
	fi
}

is_macos() {
  [ "$(uname -s)" = Darwin ]
}

# Resolve the real binary behind a PATH-shim wrapper.
# $1 - the wrapper's own $0; $2 - the real command name.
# Strips the wrapper's dir from PATH (so the name can't recurse), finds the
# real binary, then prepends that dir back so sibling shims win in children.
# Sets SHIM_DIR (the wrapper's dir) and REAL (the resolved binary); exports PATH.
# Can't just print the resolved binary or PATH wouldn't be preserved.
shim_resolve() {
	SHIM_DIR=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd -P)
	_clean=$(printf '%s' "$PATH" | tr : '\n' | grep -vxF "$SHIM_DIR" | tr '\n' :)
	_clean=${_clean%:}
	PATH="$_clean" command -v "$2" || fail "$2 wrapper: real $2 not found on PATH"
}

if ! exists realpath; then
	. lib/realpath.sh
	HAS_REALPATH=0
else
	HAS_REALPATH=1
fi
