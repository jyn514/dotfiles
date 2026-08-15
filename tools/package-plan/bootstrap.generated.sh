# Generated from install/bootstrap.edn by dev/update-package-bootstrap.
BABASHKA_VERSION=1.13.219

select_babashka_artifact() {
	case "$1" in
		linux-x64)
			BABASHKA_URL=https://github.com/babashka/babashka/releases/download/v1.13.219/babashka-1.13.219-linux-amd64-static.tar.gz
			BABASHKA_SHA256=9ac1fe988d7001625b30ef3e3307e67f8545505a7cb49a4aa179f578115a3e09
			;;
		linux-arm64)
			BABASHKA_URL=https://github.com/babashka/babashka/releases/download/v1.13.219/babashka-1.13.219-linux-aarch64-static.tar.gz
			BABASHKA_SHA256=e8d7a9c66c364b80627a43cb6ba5c14fb6ac7e4af114e8e5d80f97551ccdfe11
			;;
		macos-arm64)
			BABASHKA_URL=https://github.com/babashka/babashka/releases/download/v1.13.219/babashka-1.13.219-macos-aarch64.tar.gz
			BABASHKA_SHA256=57a45df1cee534081375f35d39a3cb5f334956e6d429e364adbf46e296d52cfb
			;;
		*) return 1;;
	esac
}
