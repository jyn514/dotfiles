#!/bin/bash
set -eu

ROOT=$HOME/.local/state/agent-podman/woodpecker-runs
RELABEL_IMAGE=docker.io/library/alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce

die() {
	printf 'woodpecker supervisor: %s\n' "$*" >&2
	exit 1
}

run_dir() {
	case ${1:-} in *[!a-f0-9]*|'') die "invalid run identifier" ;; esac
	[ "${#1}" -eq 32 ] || die "invalid run identifier"
	RUN_DIR=$ROOT/$1
}

[ "$#" -ge 2 ] || die "expected an operation and run identifier"
operation=$1
run_dir=$2
shift 2
run_dir "$run_dir"

case $operation in
prepare)
	[ "$#" -eq 0 ] || die "prepare takes no arguments"
	install -d -m 700 "$ROOT"
	[ ! -e "$RUN_DIR" ] || die "run already exists"
	mkdir -m 700 "$RUN_DIR"
	mkdir -m 700 "$RUN_DIR/repo"
	;;
receive-repository)
	[ "$#" -eq 0 ] || die "receive-repository takes no arguments"
	[ -d "$RUN_DIR/repo" ] || die "unknown run"
	tar -xf - -C "$RUN_DIR/repo"
	;;
receive-pipeline)
	[ "$#" -eq 0 ] || die "receive-pipeline takes no arguments"
	[ -d "$RUN_DIR/repo" ] || die "unknown run"
	umask 077
	set -C
	cat > "$RUN_DIR/pipeline"
	;;
run)
	[ "$#" -eq 0 ] || die "run accepts arguments only through standard input"
	[ -d "$RUN_DIR/repo" ] || die "unknown run"
	args=()
	while IFS= read -r -d '' argument; do
		args+=("$argument")
	done
	unset argument
	[ "${#args[@]}" -ge 2 ] && [ "${args[0]}" = exec ] || \
		die "run requires a Woodpecker exec command"
	podman run --rm --volume "$RUN_DIR/repo:/workspace:z" "$RELABEL_IMAGE" /bin/true
	(
		cd "$RUN_DIR"
		export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
		export WOODPECKER_BACKEND_DOCKER_HOST=unix://$XDG_RUNTIME_DIR/podman/podman.sock
		exec setsid "$HOME/.local/bin/woodpecker-cli" "${args[@]}"
	) &
	child=$!
	printf '%s\n' "$child" > "$RUN_DIR/pid"
	guard=
	termination_requested=false
	terminate() {
		[ "$termination_requested" = false ] || return
		termination_requested=true
		kill -TERM "-$child" 2>/dev/null || true
		(
			sleep 5
			kill -KILL "-$child" 2>/dev/null || true
		) &
		guard=$!
	}
	trap terminate HUP INT TERM
	set +e
	while true; do
		wait "$child"
		status=$?
		kill -0 "$child" 2>/dev/null || break
	done
	set -e
	if [ -n "$guard" ]; then
		kill "$guard" 2>/dev/null || true
		wait "$guard" 2>/dev/null || true
	fi
	rm -f "$RUN_DIR/pid"
	if ! rm -rf "$RUN_DIR"; then
		printf 'woodpecker supervisor: warning: cleanup failed for run %s\n' "$run_dir" >&2
	fi
	exit "$status"
	;;
terminate)
	[ "$#" -eq 0 ] || die "terminate takes no arguments"
	count=0
	while [ -d "$RUN_DIR" ] && [ ! -f "$RUN_DIR/pid" ] && [ "$count" -lt 20 ]; do
		sleep 0.1
		count=$((count + 1))
	done
	[ -f "$RUN_DIR/pid" ] || exit 0
	read -r child < "$RUN_DIR/pid"
	case $child in *[!0-9]*|'') die "invalid recorded process ID" ;; esac
	kill -TERM "-$child" 2>/dev/null || true
	count=0
	while kill -0 "$child" 2>/dev/null && [ "$count" -lt 50 ]; do
		sleep 0.1
		count=$((count + 1))
	done
	if kill -0 "$child" 2>/dev/null; then
		kill -KILL "-$child" 2>/dev/null || true
	fi
	;;
discard)
	[ "$#" -eq 0 ] || die "discard takes no arguments"
	[ ! -f "$RUN_DIR/pid" ] || die "refusing to discard a running workspace"
	[ ! -e "$RUN_DIR" ] || rm -rf "$RUN_DIR"
	;;
reap)
	[ "$run_dir" = 00000000000000000000000000000000 ] || die "reap uses the reserved run identifier"
	[ "$#" -eq 0 ] || die "reap takes no arguments"
	[ -d "$ROOT" ] || exit 0
	find "$ROOT" -mindepth 1 -maxdepth 1 -type d -mmin +1440 -print |
		while IFS= read -r candidate; do
			case $candidate in "$ROOT"/[a-f0-9][a-f0-9]*) ;; *) continue ;; esac
			if [ -f "$candidate/pid" ]; then
				read -r candidate_pid < "$candidate/pid" || continue
				case $candidate_pid in *[!0-9]*|'') continue ;; esac
				kill -0 "$candidate_pid" 2>/dev/null && continue
			fi
			rm -rf "$candidate"
		done
	;;
*) die "unknown operation: $operation" ;;
esac
