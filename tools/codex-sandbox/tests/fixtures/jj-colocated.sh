#!/bin/sh
set -eu
/trusted/bin/busybox sha256sum /trusted/bin/jj
export HOME=/tmp/home
busybox mkdir -p "$HOME"
cd /tmp
jj git init --colocate main
cd main
jj workspace add --colocate ../linked
cd /tmp
test -f linked/.git
test "$(git -C linked rev-parse --show-toplevel)" = /tmp/linked
jj -R linked status

# Alpine libcurl uses this alias for the bundled TLS certificate store.
test -s /etc/ssl/cert.pem

# Exercise packaged Git transport helpers through the proxy's Landlock policy.
jj git init --colocate /src/transport
cd /src/transport
export JJ_PROXY_REPO=/src/transport
busybox touch /run/jj-locks/abcdef.lock
export JJ_PROXY_WORKSPACES='[{"root":"/src/transport","git_dir":"/src/transport/.git","common_dir":"/src/transport/.git","jj_repo":"/src/transport/.jj/repo","lock":"/run/jj-locks/abcdef.lock"}]'
export SANDBOX_PROXY_DIR=/run/sandbox-proxy
git remote add origin http://127.0.0.1:1/missing
jj-proxy serve >/tmp/jj-proxy.log 2>&1 &
server=$!
trap 'kill "$server"; wait "$server" 2>/dev/null || :' EXIT
attempt=0
until jj-proxy :ready >/dev/null 2>&1; do
	attempt=$((attempt + 1))
	if [ "$attempt" -ge 50 ]; then
		busybox cat /tmp/jj-proxy.log >&2
		exit 1
	fi
	busybox sleep 0.1
done
for transport in http https; do
	git remote set-url origin "$transport://127.0.0.1:1/missing"
	if jj-proxy git fetch --remote origin >/tmp/fetch.log 2>&1; then
		printf 'fetch unexpectedly succeeded without a server\n' >&2
		exit 1
	fi
	# A connection failure proves the helper starts; missing helpers or denied
	# execution must not count as the expected failure.
	if ! busybox grep -F 'Could not connect to server' /tmp/fetch.log >/dev/null; then
		busybox cat /tmp/fetch.log >&2
		exit 1
	fi
done
printf 'jj-colocated-ok\n'
