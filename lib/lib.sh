#!/bin/sh
exists () {
	command -v "$1" >/dev/null 2>&1
	return $?
}

# takes two parameters:
# $1 - the URL to download. required.
# $2 - the file to save to. optional. defaults to $(mktemp). specify this for max compatibility.
download () {
	if [ -n "$2" ]; then
		OUTPUT="$2"
	else
		OUTPUT="$(mktemp)"
	fi
	if exists curl; then
		curl -L "$1" > "$OUTPUT"
	else
		wget -O "$OUTPUT" "$1"
	fi
	printf "%s" "$OUTPUT"
}

# get the link for the latest github release of "$1"
# $1 should have the format username/repo
latest_release() {
	curl --silent https://api.github.com/repos/"$1"/releases/latest | \
		jq --raw-output '.assets | .[].browser_download_url' | \
		grep .deb
}
