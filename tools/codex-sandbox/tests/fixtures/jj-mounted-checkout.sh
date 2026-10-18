#!/bin/sh
set -eu
export JJ_PROXY_REPO="$PWD"
export JJ_PROXY_GIT_DIR="$PWD/.git"
export JJ_PROXY_COMMON_DIR="$PWD/.git"
export JJ_PROXY_JJ_REPO="$PWD/.jj/repo"
export SANDBOX_PROXY_DIR=/run/sandbox-proxy
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
jj-proxy commit -m 'Sandbox configuration'
configuration=$(jj-proxy log -r @- --no-graph -T commit_id)
jj-proxy new 'root()'
test ! -e .agents/sandbox
jj-proxy new "$configuration"
test -f .agents/sandbox/Dockerfile
jj-proxy status >/dev/null
printf 'jj-mounted-checkout-ok\n'
