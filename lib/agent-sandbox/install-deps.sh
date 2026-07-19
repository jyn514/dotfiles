#!/bin/sh

set -eux

JJ_VERSION="${JJ_VERSION:-0.42.0}"
GH_VERSION="${GH_VERSION:-2.76.1}"

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
        gh \
        podman \
        socat
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
        jujutsu \
        podman \
        socat
elif command -v microdnf >/dev/null; then
    case "$(uname -m)" in
        x86_64)
            gh_arch=amd64
            jj_arch=x86_64
            ;;
        aarch64|arm64)
            gh_arch=arm64
            jj_arch=aarch64
            ;;
        *)
            echo "Unsupported architecture: $(uname -m)" >&2
            exit 1
            ;;
    esac

    microdnf install -y --nobest \
        bubblewrap \
        ca-certificates \
        curl \
        gzip \
        podman \
        socat \
        tar
    curl -fsSL \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${gh_arch}.tar.gz" \
        | tar -xz --strip-components=2 -C /usr/local/bin \
            "gh_${GH_VERSION}_linux_${gh_arch}/bin/gh"
    curl -fsSL \
        "https://github.com/jj-vcs/jj/releases/download/v${JJ_VERSION}/jj-v${JJ_VERSION}-${jj_arch}-unknown-linux-musl.tar.gz" \
        | tar -xz -C /usr/local/bin
    gh --version
    jj --version
else
    echo "Unsupported package manager" >&2
    exit 1
fi

podman --version
ln -s "$(command -v podman)" /usr/local/bin/docker
docker --version
socat -V
