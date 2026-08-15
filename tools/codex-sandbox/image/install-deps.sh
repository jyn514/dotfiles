#!/bin/sh

set -eux

if command -v apt-get >/dev/null; then
    if [ -n "${KEEP_PACKAGE_CACHE:-}" ]; then
        rm -f /etc/apt/apt.conf.d/docker-clean
    fi
    apt-get update
    apt-get install -y --no-install-recommends \
        bubblewrap \
        binutils \
        ca-certificates \
        curl \
        fd-find \
        file \
        git \
        iproute2 \
        jq \
        lsof \
        openssh-client \
        passwd \
        procps \
        python3 \
        ripgrep \
        shellcheck \
        socat \
        sudo \
        tar \
        xz-utils
    if [ -z "${KEEP_PACKAGE_CACHE:-}" ]; then
        rm -rf /var/lib/apt/lists/*
    fi
elif command -v apk >/dev/null; then
    if [ -n "${KEEP_PACKAGE_CACHE:-}" ]; then
        set --
    else
        set -- --no-cache
    fi
    apk add "$@" \
        bubblewrap \
        binutils \
        ca-certificates \
        curl \
        fd \
        file \
        gcompat \
        git \
        iproute2 \
        jq \
        lsof \
        openssh-client-default \
        procps \
        python3 \
        ripgrep \
        shadow \
        shellcheck \
        socat \
        sudo \
        xz
elif command -v microdnf >/dev/null; then
    microdnf install -y --nobest \
        bubblewrap \
        binutils \
        ca-certificates \
        curl \
        fd-find \
        file \
        git \
        gzip \
        iproute \
        jq \
        lsof \
        openssh-clients \
        procps-ng \
        python3 \
        ripgrep \
        shadow-utils \
        ShellCheck \
        socat \
        sudo \
        tar \
        xz
else
    echo "Unsupported package manager" >&2
    exit 1
fi

if ! command -v fd >/dev/null && command -v fdfind >/dev/null; then
    ln -s "$(command -v fdfind)" /usr/local/bin/fd
fi

fd --version
jq --version
shellcheck --version
socat -V
