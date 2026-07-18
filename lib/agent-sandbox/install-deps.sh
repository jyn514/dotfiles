#!/bin/sh

set -eux

JJ_VERSION="${JJ_VERSION:-0.42.0}"

if command -v apt-get >/dev/null; then
    case "$(uname -m)" in
        x86_64) jj_arch=x86_64 ;;
        aarch64|arm64) jj_arch=aarch64 ;;
        *)
            echo "Unsupported architecture: $(uname -m)" >&2
            exit 1
            ;;
    esac

    apt-get update
    apt-get install -y --no-install-recommends \
        bubblewrap \
        ca-certificates \
        curl \
        gh
    curl -fsSL \
        "https://github.com/jj-vcs/jj/releases/download/v${JJ_VERSION}/jj-v${JJ_VERSION}-${jj_arch}-unknown-linux-musl.tar.gz" \
        | tar -xz -C /usr/local/bin
    jj --version
    rm -rf /var/lib/apt/lists/*
elif command -v apk >/dev/null; then
    apk add --no-cache \
        bubblewrap \
        ca-certificates \
        github-cli \
        jujutsu
else
    echo "Unsupported package manager" >&2
    exit 1
fi
