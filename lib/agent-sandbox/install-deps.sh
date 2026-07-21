#!/bin/sh

set -eux

JJ_VERSION="${JJ_VERSION:-0.42.0}"
GH_VERSION="${GH_VERSION:-2.76.1}"
PODMAN_VERSION="${PODMAN_VERSION:-6.0.1}"

case "$(uname -m)" in
    x86_64)
        podman_arch=amd64
        ;;
    aarch64|arm64)
        podman_arch=arm64
        ;;
    *)
        echo "Unsupported architecture: $(uname -m)" >&2
        exit 1
        ;;
esac

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
        binutils \
        ca-certificates \
        curl \
        file \
        gh \
        git \
        iproute2 \
        jq \
        lsof \
        procps \
        python3 \
        ripgrep \
        socat \
        sudo
    curl -fsSL \
        "https://github.com/jj-vcs/jj/releases/download/v${JJ_VERSION}/jj-v${JJ_VERSION}-${jj_arch}-unknown-linux-musl.tar.gz" \
        | tar -xz -C /usr/local/bin
    jj --version
    rm -rf /var/lib/apt/lists/*
elif command -v apk >/dev/null; then
    apk add --no-cache \
        bubblewrap \
        binutils \
        ca-certificates \
        file \
        git \
        github-cli \
        iproute2 \
        jujutsu \
        jq \
        lsof \
        procps \
        python3 \
        ripgrep \
        socat \
        sudo
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
        binutils \
        ca-certificates \
        curl \
        file \
        git \
        gzip \
        iproute \
        jq \
        lsof \
        procps-ng \
        python3 \
        ripgrep \
        socat \
        sudo \
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

podman_archive="podman-remote-static-linux_${podman_arch}.tar.gz"
podman_download_dir=$(mktemp -d)
trap 'rm -rf "$podman_download_dir"' EXIT HUP INT TERM
curl -fsSL -o "$podman_download_dir/$podman_archive" \
    "https://github.com/podman-container-tools/podman/releases/download/v${PODMAN_VERSION}/$podman_archive"
curl -fsSL -o "$podman_download_dir/shasums" \
    "https://github.com/podman-container-tools/podman/releases/download/v${PODMAN_VERSION}/shasums"
(
    cd "$podman_download_dir"
    grep "  $podman_archive\$" shasums > podman.sha256
    test -s podman.sha256
    sha256sum -c podman.sha256
)
tar -xzf "$podman_download_dir/$podman_archive" \
    --strip-components=1 \
    -C /usr/local/bin \
    "bin/podman-remote-static-linux_${podman_arch}"
mv "/usr/local/bin/podman-remote-static-linux_${podman_arch}" \
    /usr/local/bin/podman
rm -rf "$podman_download_dir"
trap - EXIT HUP INT TERM

jq --version
podman --version
ln -s /usr/local/bin/podman /usr/local/bin/docker
docker --version
socat -V
