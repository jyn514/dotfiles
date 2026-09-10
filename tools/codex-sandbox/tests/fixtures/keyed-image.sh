#!/bin/sh
set -eu

image=$1
if ! docker image inspect "$image" >/dev/null 2>&1; then
	printf 'BUILD-MISS\n' >&2
	docker build --tag "$image" --file Dockerfile . >&2
fi
docker image inspect --format '{{.Id}}' "$image"
