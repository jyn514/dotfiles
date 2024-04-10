#!/bin/sh

version=${fx_version:-'34.0.0'}
dst=${dst:-$HOME/.local/bin}

os=$(uname -s | tr '[:upper:]' '[:lower:]')
machine=$(uname -m)

case $os in
linux | darwin)
  ext=''
  ;;
windows)
  os=windows
  ext='.exe'
  ;;
*)
  echo "Unsupported OS: $os" >&2
  exit 1
  ;;
esac

case $machine in
x86_64 | amd64)
  arch=amd64
  ;;
arm64 | aarch64)
  arch=arm64
  ;;
*)
  echo "Unsupported architecture: $machine" >&2
  exit 1
  ;;
esac

asset="fx_${os}_${arch}${ext}"
echo "Installing fx ${version} (${asset}) to $dst"
curl -Lfs "https://github.com/antonmedv/fx/releases/download/${version}/${asset}" -o fx

chmod +x fx
mv -v fx "$dst"
