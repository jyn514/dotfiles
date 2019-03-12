exists () {
	which "$1" >/dev/null 2>&1
	return $?;
}

# takes two parameters:
# $1 - the URL to download. required.
# $2 - the file to save to. optional. defaults to $(mktemp). specify this for max compatiblity.
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
