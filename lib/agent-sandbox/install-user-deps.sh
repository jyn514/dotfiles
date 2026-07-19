#!/bin/sh

set -eux

if command -v apt-get >/dev/null; then
    apt-get update
    apt-get install -y --no-install-recommends passwd
    rm -rf /var/lib/apt/lists/*
elif command -v apk >/dev/null; then
    apk add --no-cache shadow
elif command -v microdnf >/dev/null; then
    microdnf install -y --nobest shadow-utils
else
    echo "Unsupported package manager" >&2
    exit 1
fi
