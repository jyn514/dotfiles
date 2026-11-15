#!/bin/sh

set -eux

tool=${1:?Pass a tool name}
version=${2:?Pass its version}

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

download_dir=$(mktemp -d)
trap 'rm -rf "$download_dir"' EXIT HUP INT TERM

case "$tool" in
	bb)
		archive="babashka-${version}-linux-${bb_arch}-static.tar.gz"
		curl -fsSL -o "$download_dir/$archive" \
			"https://github.com/babashka/babashka/releases/download/v${version}/$archive"
		printf '%s  %s\n' "$bb_sha256" "$download_dir/$archive" | sha256sum -c -
		tar -xzf "$download_dir/$archive" -C /usr/local/bin bb
		bb --version
		;;
	gh)
		archive="gh_${version}_linux_${gh_arch}.tar.gz"
		curl -fsSL -o "$download_dir/$archive" \
			"https://github.com/cli/cli/releases/download/v${version}/$archive"
		tar -xzf "$download_dir/$archive" --strip-components=2 -C /usr/local/bin \
			"gh_${version}_linux_${gh_arch}/bin/gh"
		gh --version
		;;
	typst)
		target="${typst_arch}-unknown-linux-musl"
		archive="typst-${target}.tar.xz"
		curl -fsSL -o "$download_dir/$archive" \
			"https://github.com/typst/typst/releases/download/v${version}/$archive"
		tar -xJf "$download_dir/$archive" --strip-components=1 -C /usr/local/bin \
			"typst-${target}/typst"
		typst --version
		;;
	docker)
		curl -fsSL -o "$download_dir/docker.tgz" \
			"https://download.docker.com/linux/static/stable/${docker_arch}/docker-${version}.tgz"
		printf '%s  %s\n' "$docker_sha256" "$download_dir/docker.tgz" | sha256sum -c -
		tar -xzf "$download_dir/docker.tgz" --strip-components=1 -C /usr/local/bin docker/docker
		docker --version
		;;
	buildx)
		curl -fsSL -o "$download_dir/docker-buildx" \
			"https://github.com/docker/buildx/releases/download/v${version}/buildx-v${version}.linux-${buildx_arch}"
		printf '%s  %s\n' "$buildx_sha256" "$download_dir/docker-buildx" | sha256sum -c -
		mkdir -p /usr/local/lib/docker/cli-plugins
		install -m 755 "$download_dir/docker-buildx" /usr/local/lib/docker/cli-plugins/docker-buildx
		/usr/local/lib/docker/cli-plugins/docker-buildx version
		;;
	*)
		echo "Unsupported tool: $tool" >&2
		exit 1
		;;
esac
