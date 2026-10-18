set -eu
for repo in /src/project /src/dotfiles; do
	/trusted/bin/busybox touch "$repo/guest-write"
	for metadata in .git .jj; do
		if /trusted/bin/busybox touch "$repo/$metadata/guest-probe" 2>/dev/null; then
			echo "writable metadata: $repo/$metadata" >&2
			exit 1
		fi
	done
done
if /trusted/bin/busybox touch /src/dotfiles/.agents/sandbox/guest-policy 2>/dev/null; then
	echo 'writable dotfiles sandbox policy' >&2
	exit 1
fi
if /trusted/bin/busybox touch /src/sibling/guest-probe 2>/dev/null; then
	echo 'writable unrelated source tree' >&2
	exit 1
fi
printf '%s\n' shared-workspace-guest-ok
