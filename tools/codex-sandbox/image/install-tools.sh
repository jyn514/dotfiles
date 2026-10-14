#!/bin/sh

set -eux

BB_VERSION=${BB_VERSION:-1.13.219}
GH_VERSION=${GH_VERSION:-2.76.1}
DOCKER_VERSION=${DOCKER_VERSION:-29.8.0}
BUILDX_VERSION=${BUILDX_VERSION:-0.37.0}
TYPST_VERSION=${TYPST_VERSION:-0.15.1}

if command -v apt-get >/dev/null; then
    rm -f /etc/apt/apt.conf.d/docker-clean
    apt-get update
    apt-get install -y --no-install-recommends ca-certificates curl tar xz-utils
elif command -v apk >/dev/null; then
    apk add ca-certificates curl gcompat tar xz
elif command -v microdnf >/dev/null; then
    microdnf install -y --nobest ca-certificates curl gzip tar xz
else
    echo "Unsupported package manager" >&2
    exit 1
fi

case "$(uname -m)" in
    x86_64)
        bb_arch=amd64
        bb_sha256=9ac1fe988d7001625b30ef3e3307e67f8545505a7cb49a4aa179f578115a3e09
        gh_arch=amd64
        docker_arch=x86_64
        docker_sha256=cc21815cf1e2efed867dc9c8b96b46ffed8ea176ffab32b0aacb54726ded8f25
        buildx_arch=amd64
        buildx_sha256=ae43fa08c796b44efc86d7a63c55f73f7c35f3101188dea7bf93bcd6f99577ba
        typst_arch=x86_64
        ;;
    aarch64|arm64)
        bb_arch=aarch64
        bb_sha256=e8d7a9c66c364b80627a43cb6ba5c14fb6ac7e4af114e8e5d80f97551ccdfe11
        gh_arch=arm64
        docker_arch=aarch64
        docker_sha256=1462a696be6029bd478d7d60d7f3c31cdd15affd1178a4a278aaf4a1d1b7f8b5
        buildx_arch=arm64
        buildx_sha256=d263ce31bd2c9e9210aaa2c7537c67802bccabcd342e4c9fe4907085ddb41aa5
        typst_arch=aarch64
        ;;
    *)
        echo "Unsupported architecture: $(uname -m)" >&2
        exit 1
        ;;
esac

bb_archive="babashka-${BB_VERSION}-linux-${bb_arch}-static.tar.gz"
bb_download_dir=$(mktemp -d)
trap 'rm -rf "$bb_download_dir"' EXIT HUP INT TERM
curl -fsSL -o "$bb_download_dir/$bb_archive" \
    "https://github.com/babashka/babashka/releases/download/v${BB_VERSION}/$bb_archive"
printf '%s  %s\n' "$bb_sha256" "$bb_download_dir/$bb_archive" | sha256sum -c -
tar -xzf "$bb_download_dir/$bb_archive" -C /usr/local/bin bb
rm -rf "$bb_download_dir"
trap - EXIT HUP INT TERM

curl -fsSL \
    "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${gh_arch}.tar.gz" \
    | tar -xz --strip-components=2 -C /usr/local/bin \
        "gh_${GH_VERSION}_linux_${gh_arch}/bin/gh"
typst_target="${typst_arch}-unknown-linux-musl"
curl -fsSL \
    "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${typst_target}.tar.xz" \
    | tar -xJ --strip-components=1 -C /usr/local/bin \
        "typst-${typst_target}/typst"

docker_download_dir=$(mktemp -d)
trap 'rm -rf "$docker_download_dir"' EXIT HUP INT TERM
curl -fsSL -o "$docker_download_dir/docker.tgz" \
    "https://download.docker.com/linux/static/stable/${docker_arch}/docker-${DOCKER_VERSION}.tgz"
printf '%s  %s\n' "$docker_sha256" "$docker_download_dir/docker.tgz" | sha256sum -c -
tar -xzf "$docker_download_dir/docker.tgz" --strip-components=1 -C /usr/local/bin docker/docker
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL -o "$docker_download_dir/docker-buildx" \
    "https://github.com/docker/buildx/releases/download/v${BUILDX_VERSION}/buildx-v${BUILDX_VERSION}.linux-${buildx_arch}"
printf '%s  %s\n' "$buildx_sha256" "$docker_download_dir/docker-buildx" | sha256sum -c -
install -m 755 "$docker_download_dir/docker-buildx" /usr/local/lib/docker/cli-plugins/docker-buildx
rm -rf "$docker_download_dir"
trap - EXIT HUP INT TERM

docker --version
docker buildx version
bb --version
gh --version
typst --version
