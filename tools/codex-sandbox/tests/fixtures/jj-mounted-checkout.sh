#!/bin/sh
set -eu
: "${JJ_PROXY_REPO:?launcher workspace root is required}"
: "${JJ_PROXY_WORKSPACES:?launcher workspace authority is required}"
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
