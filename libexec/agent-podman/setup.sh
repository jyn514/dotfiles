#!/bin/sh
set -eu

# Run on the macOS host, not inside the Docker sandbox.

SAFE_PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
PATH=$SAFE_PATH
export PATH
IFS=' 	
'
umask 077
unset CDPATH ENV BASH_ENV ZDOTDIR

ACCOUNT=_agentpodman
ACCOUNT_GROUP=_agentpodman
MACHINE=agent-podman
GUEST_ACCOUNT=agentbuilder
ACCOUNT_HOME=/Users/$ACCOUNT
MARKER_DIR=/var/db/agent-podman
MARKER=$MARKER_DIR/$ACCOUNT
GROUP_MARKER=$MARKER_DIR/group
PF_RULES=$MARKER_DIR/pf.rules
PF_ENABLE_LOG=$MARKER_DIR/pf-enable.log
PF_ANCHOR=com.apple/000.agent-podman
SCRIPT_PATH=$(/bin/realpath "$0")
SCRIPT_DIR=$(CDPATH='' cd -P -- "$(dirname -- "$SCRIPT_PATH")" && pwd -P)
SUPERVISOR_SOURCE=$SCRIPT_DIR/woodpecker-supervisor.sh
CPUS=${AGENT_PODMAN_CPUS:-6}
MEMORY=${AGENT_PODMAN_MEMORY:-12288}
DISK_SIZE=${AGENT_PODMAN_DISK_SIZE:-30}
WOODPECKER_VERSION=3.15.0
RELABEL_IMAGE=docker.io/library/alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

[ -f "$SUPERVISOR_SOURCE" ] && [ ! -L "$SUPERVISOR_SOURCE" ] && [ -s "$SUPERVISOR_SOURCE" ] || \
  die "missing safe Woodpecker supervisor: $SUPERVISOR_SOURCE"

find_role_uid() {
  used_uids=$(dscl . -list /Users UniqueID | awk 'NF >= 2 { print $NF }')
  candidate=450
  while [ "$candidate" -le 499 ]; do
    if ! printf '%s\n' "$used_uids" | grep -qxF "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
    candidate=$((candidate + 1))
  done
  die "no free macOS role-account UID remains in 450-499"
}

generate_account_password() {
  # Alternating disjoint character classes cannot contain adjacent duplicates
  # or three-character sequences, satisfying the host's managed password policy.
  openssl rand -hex 20 | awk '
    BEGIN {
      hex = "0123456789abcdef"
      upper = "ABCDEFGHIJKLMNOP"
      digits = "0123456789012345"
      lower = "abcdefghijklmnop"
      symbols = "!@#$%^&*_-+=:;,."
    }
    {
      password = ""
      for (i = 1; i <= length($0); i++) {
        index_in_alphabet = index(hex, substr($0, i, 1))
        slot = (i - 1) % 4
        if (slot == 0) alphabet = upper
        else if (slot == 1) alphabet = digits
        else if (slot == 2) alphabet = lower
        else alphabet = symbols
        password = password substr(alphabet, index_in_alphabet, 1)
      }
      print password
    }
  '
}

verify_host_account() {
  [ "$(dscl . -read "/Users/$ACCOUNT" IsHidden | awk '{print $2}')" = 1 ] || \
    die "worker account is not hidden"
  [ "$(dscl . -read "/Users/$ACCOUNT" UserShell | awk '{print $2}')" = /usr/bin/false ] || \
    die "worker account has an interactive shell"
  [ "$(dscl . -read "/Users/$ACCOUNT" NFSHomeDirectory | awk '{print $2}')" = "$ACCOUNT_HOME" ] || \
    die "worker account home changed"
  [ "$(dscl . -read "/Users/$ACCOUNT" PrimaryGroupID | awk '{print $2}')" = "$ACCOUNT_GID" ] || \
    die "worker primary group changed"
  [ "$(id -g "$ACCOUNT")" = "$ACCOUNT_GID" ] || die "worker effective primary group changed"
  [ "$ACCOUNT_UID" -ge 450 ] && [ "$ACCOUNT_UID" -le 499 ] || \
    die "worker account is not in the macOS role-account UID range"
  # Current macOS records pwpolicy -disableuser through this system group;
  # role accounts need not have an AuthenticationAuthority attribute.
  dseditgroup -o checkmember -m "$ACCOUNT" com.apple.access_disabled 2>/dev/null | \
    grep -q '^yes ' || die "worker password authentication is not disabled"
  for forbidden_group in admin staff wheel _developer; do
    if dseditgroup -o checkmember -m "$ACCOUNT" "$forbidden_group" 2>/dev/null | grep -q 'yes'; then
      die "worker account is a member of $forbidden_group"
    fi
  done
  for private_dir in "$ACCOUNT_HOME" "$ACCOUNT_HOME/.config" "$ACCOUNT_HOME/.config/containers"; do
    [ "$(stat -f %u "$private_dir")" = "$ACCOUNT_UID" ] || die "worker directory owner changed: $private_dir"
    [ "$(stat -f %g "$private_dir")" = "$ACCOUNT_GID" ] || die "worker directory group changed: $private_dir"
    [ "$(stat -f %Lp "$private_dir")" = 700 ] || die "worker directory mode changed: $private_dir"
  done
  if find "$ACCOUNT_HOME" -prune -exec /bin/ls -lde {} \; | \
      awk 'NR > 1 { has_acl=1 } END { exit !has_acl }'; then
    die "worker home has an ACL"
  fi
}

[ "$(uname -s)" = Darwin ] || die "this script must run on macOS"
[ "$(id -u)" -eq 0 ] || die "run with sudo: sudo $0"
CALLER_USER=${SUDO_USER:-}
[ -n "$CALLER_USER" ] || die "invoke this script through sudo from the owning user"
CALLER_UID=$(id -u "$CALLER_USER")
CALLER_HOME=$(dscl . -read "/Users/$CALLER_USER" NFSHomeDirectory | awk '{print $2}')
case "$CALLER_HOME" in /Users/*) ;; *) die "unexpected caller home: $CALLER_HOME" ;; esac
OUTPUT_DIR=$CALLER_HOME/.agent-podman-access
[ "$(stat -f %u "$CALLER_HOME")" = "$CALLER_UID" ] || die "$CALLER_USER must own $CALLER_HOME"
[ ! -e "$OUTPUT_DIR" ] && [ ! -L "$OUTPUT_DIR" ] || die "refusing to reuse $OUTPUT_DIR"
[ ! -e "$MARKER" ] && [ ! -L "$MARKER" ] || die "ownership marker already exists: $MARKER"
[ ! -e "$GROUP_MARKER" ] && [ ! -L "$GROUP_MARKER" ] || \
  die "worker group marker already exists; run teardown before setup"
[ ! -e "$ACCOUNT_HOME" ] && [ ! -L "$ACCOUNT_HOME" ] || die "refusing preexisting worker home: $ACCOUNT_HOME"
if dscl . -read "/Users/$ACCOUNT" >/dev/null 2>&1; then
  die "account $ACCOUNT already exists; run teardown or inspect it manually"
fi
if dscl . -read "/Groups/$ACCOUNT_GROUP" >/dev/null 2>&1; then
  die "group $ACCOUNT_GROUP already exists; run teardown or inspect it manually"
fi

for value in "$CPUS" "$MEMORY" "$DISK_SIZE"; do
  case "$value" in
    *[!0-9]*|'') die "resource values must be positive integers" ;;
  esac
  [ "$value" -gt 0 ] || die "resource values must be positive integers"
done

PODMAN_BIN=${AGENT_PODMAN_BIN:-}
if [ -z "$PODMAN_BIN" ]; then
  PODMAN_BIN=$(command -v podman) || die "podman is not installed or not on PATH"
fi
case "$PODMAN_BIN" in /*) ;; *) die "AGENT_PODMAN_BIN must be an absolute path" ;; esac
[ -x "$PODMAN_BIN" ] || die "Podman executable is not executable: $PODMAN_BIN"
PODMAN_DIR=$(dirname "$PODMAN_BIN")

TMP_CONFIG=

run_worker() {
  /usr/bin/sudo -u "$ACCOUNT" \
    /usr/bin/env -i HOME="$ACCOUNT_HOME" USER="$ACCOUNT" LOGNAME="$ACCOUNT" \
    CONTAINERS_CONF="$ACCOUNT_HOME/.config/containers/containers.conf" \
    PATH="$PODMAN_DIR:$SAFE_PATH" \
    "$PODMAN_BIN" "$@"
}

run_guest() {
  /usr/bin/sudo -u "$CALLER_USER" \
    /usr/bin/env -i HOME="$CALLER_HOME" USER="$CALLER_USER" LOGNAME="$CALLER_USER" \
    PATH="$SAFE_PATH" \
    /usr/bin/ssh -F /dev/null \
      -o BatchMode=yes \
      -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=accept-new \
      -o UserKnownHostsFile="$OUTPUT_DIR/known_hosts" \
      -i "$KEY" \
      -p "$SSH_PORT" \
      "$GUEST_ACCOUNT@127.0.0.1" \
      "$@"
}

install_network_guard() {
  main_rules=$(/sbin/pfctl -sr)
  if ! printf '%s\n' "$main_rules" | awk '
    /anchor "com\.apple\/\*"/ { found=1; exit }
    NF { earlier_rule=1 }
    END { exit !(found && !earlier_rule) }
  '; then
    die "PF must evaluate com.apple/* before any other active filter rule"
  fi
  existing_rules=$(/sbin/pfctl -a "$PF_ANCHOR" -sr)
  [ -z "$existing_rules" ] || die "PF anchor $PF_ANCHOR already contains rules"

  # A `set skip on lo0` option is invisible to `pfctl -sr` but disables all
  # filtering on loopback, defeating the 127/8 and ::1 block rules below and
  # exposing host loopback services to the guest via the worker-owned NAT.
  if /sbin/pfctl -s Interfaces 2>/dev/null | grep -Eq '(^|[[:space:]])lo0[[:space:]]*\(skip\)'; then
    die "PF skips filtering on lo0; loopback block rules would not apply"
  fi

  # Rule order matters: PF `quick` rules are first-match-wins. The private and
  # reserved block rules must precede the DNS pass so that port-53 traffic to
  # those ranges is blocked; only DNS to public addresses reaches the pass rule.
  {
    # Match the initial inbound SYN against the worker-owned listening socket.
    # Its state permits only replies for accepted SSH connections; an outbound
    # source-port rule does not reliably create state after Docker translation.
    printf 'pass in quick inet proto tcp from any to any port %s user %s flags S/SA keep state\n' "$SSH_PORT" "$ACCOUNT_UID"
    printf 'pass in quick inet6 proto tcp from any to any port %s user %s flags S/SA keep state\n' "$SSH_PORT" "$ACCOUNT_UID"
    printf '%s\n' \
      "block return out quick inet proto { tcp udp } from any to { 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.168.0.0/16 198.18.0.0/15 224.0.0.0/4 240.0.0.0/4 } user $ACCOUNT_UID"
    printf '%s\n' \
      "block return out quick inet6 proto { tcp udp } from any to { ::/128 ::1/128 ::ffff:0:0/96 fc00::/7 fe80::/10 ff00::/8 } user $ACCOUNT_UID"
    printf 'pass out quick proto { tcp udp } from any to any port 53 user %s\n' "$ACCOUNT_UID"
  } > "$PF_RULES"
  chmod 600 "$PF_RULES"
  chown root:wheel "$PF_RULES"

  /sbin/pfctl -n -a "$PF_ANCHOR" -f "$PF_RULES"
  /sbin/pfctl -a "$PF_ANCHOR" -f "$PF_RULES"
  first_child=$(/sbin/pfctl -a com.apple -s Anchors | awk 'NF { print $1; exit }')
  [ "$first_child" = "$PF_ANCHOR" ] || \
    die "PF anchor $PF_ANCHOR is not evaluated first under com.apple/*"
  : > "$PF_ENABLE_LOG"
  chmod 600 "$PF_ENABLE_LOG"
  chown root:wheel "$PF_ENABLE_LOG"
  if ! /sbin/pfctl -E > "$PF_ENABLE_LOG" 2>&1; then
    rm -f "$PF_ENABLE_LOG"
    die "could not enable PF; anchor rules remain recorded for teardown"
  fi
  PF_TOKEN=$(awk '$1 == "Token" && $2 == ":" { print $3 }' "$PF_ENABLE_LOG")
  case "$PF_TOKEN" in *[!0-9]*|'')
    printf 'unexpected pfctl enable output:\n' >&2
    cat "$PF_ENABLE_LOG" >&2
    die "could not record the PF enable-reference token"
    ;;
  esac
}

retain_on_error() {
  status=$?
  trap - EXIT HUP INT TERM
  rm -f "${TMP_CONFIG:-}"
  if [ "$status" -ne 0 ]; then
    printf 'setup failed; state and provenance were retained for inspection\n' >&2
    printf 'after inspection, retry cleanup with: sudo %s/teardown.sh\n' "$SCRIPT_DIR" >&2
  fi
  exit "$status"
}
trap retain_on_error EXIT HUP INT TERM

if [ -e "$MARKER_DIR" ] || [ -L "$MARKER_DIR" ]; then
  [ -d "$MARKER_DIR" ] && [ ! -L "$MARKER_DIR" ] || die "unsafe marker directory: $MARKER_DIR"
  [ "$(stat -f %u "$MARKER_DIR")" = 0 ] || die "root must own $MARKER_DIR"
  [ "$(stat -f %Lp "$MARKER_DIR")" = 700 ] || die "$MARKER_DIR must have mode 700"
else
  install -d -m 700 -o root -g wheel "$MARKER_DIR"
fi
printf '%s\n%s\n' "$ACCOUNT_HOME" "$OUTPUT_DIR" > "$MARKER"
chmod 600 "$MARKER"
chown root:wheel "$MARKER"
printf '%s\n' "$ACCOUNT_GROUP" > "$GROUP_MARKER"
chmod 600 "$GROUP_MARKER"
chown root:wheel "$GROUP_MARKER"

if ! dscl . -read "/Groups/$ACCOUNT_GROUP" >/dev/null 2>&1; then
  /usr/sbin/dseditgroup -o create -q -n . -r "Disposable Podman Worker" "$ACCOUNT_GROUP"
fi
ACCOUNT_GID=$(dscl . -read "/Groups/$ACCOUNT_GROUP" PrimaryGroupID | awk '{print $2}')
case "$ACCOUNT_GID" in *[!0-9]*|'') die "invalid worker group ID: $ACCOUNT_GID" ;; esac
ROLE_UID=$(find_role_uid)

ACCOUNT_PASSWORD=$(generate_account_password)
sysadminctl -addUser "$ACCOUNT" \
  -fullName "Disposable Podman Worker" \
  -UID "$ROLE_UID" \
  -GID "$ACCOUNT_GID" \
  -roleAccount \
  -password "$ACCOUNT_PASSWORD"
unset ACCOUNT_PASSWORD

ACCOUNT_UID=$(id -u "$ACCOUNT")
[ "$ACCOUNT_UID" = "$ROLE_UID" ] || die "worker role-account UID changed during creation"
# sysadminctl assigns role accounts to /var/empty; Podman needs a private,
# writable home for its machine state.
dscl . -create "/Users/$ACCOUNT" NFSHomeDirectory "$ACCOUNT_HOME"
dscl . -create "/Users/$ACCOUNT" UserShell /usr/bin/false
dscl . -create "/Users/$ACCOUNT" IsHidden 1
/usr/bin/pwpolicy -u "$ACCOUNT" -disableuser
for forbidden_group in admin staff wheel _developer; do
  if dseditgroup -o checkmember -m "$ACCOUNT" "$forbidden_group" 2>/dev/null | grep -q 'yes'; then
    dseditgroup -o edit -d "$ACCOUNT" -t user "$forbidden_group"
  fi
  if dseditgroup -o checkmember -m "$ACCOUNT" "$forbidden_group" 2>/dev/null | grep -q 'yes'; then
    die "worker account is still a member of $forbidden_group"
  fi
done

if [ -e "$ACCOUNT_HOME" ] || [ -L "$ACCOUNT_HOME" ]; then
  [ -d "$ACCOUNT_HOME" ] && [ ! -L "$ACCOUNT_HOME" ] || die "unsafe worker home: $ACCOUNT_HOME"
  [ "$(stat -f %u "$ACCOUNT_HOME")" = "$ACCOUNT_UID" ] || die "worker does not own $ACCOUNT_HOME"
else
  install -d -m 700 -o "$ACCOUNT_UID" -g "$ACCOUNT_GID" "$ACCOUNT_HOME"
fi
chgrp -R "$ACCOUNT_GID" "$ACCOUNT_HOME"
chmod -N "$ACCOUNT_HOME"
chmod 700 "$ACCOUNT_HOME"
install -d -m 700 -o "$ACCOUNT_UID" -g "$ACCOUNT_GID" "$ACCOUNT_HOME/.config"
install -d -m 700 -o "$ACCOUNT_UID" -g "$ACCOUNT_GID" "$ACCOUNT_HOME/.config/containers"

CONFIG_FILE=$ACCOUNT_HOME/.config/containers/containers.conf
TMP_CONFIG=$(mktemp "$MARKER_DIR/config.XXXXXX")
printf '%s\n' \
  '[machine]' \
  'provider = "applehv"' \
  'rosetta = false' \
  'volumes = []' > "$TMP_CONFIG"
install -m 600 -o "$ACCOUNT_UID" -g "$ACCOUNT_GID" "$TMP_CONFIG" "$CONFIG_FILE"

run_worker machine init \
  --provider applehv \
  --cpus "$CPUS" \
  --memory "$MEMORY" \
  --disk-size "$DISK_SIZE" \
  --rootful=false \
  --update-connection=false \
  --now \
  "$MACHINE"

MOUNTS=$(run_worker machine ssh "$MACHINE" 'findmnt -rn -o TARGET,SOURCE,FSTYPE')
if printf '%s\n' "$MOUNTS" | awk '
  $1 == "/Users" || $1 ~ "^/Users/" || $1 == "/Volumes" || $1 ~ "^/Volumes/" { bad=1 }
  tolower($3) == "9p" || tolower($3) == "virtiofs" { bad=1 }
  END { exit !bad }
'; then
  printf '%s\n' "$MOUNTS" >&2
  die "the VM has a host-sharing mount; refusing to continue"
fi

SSH_PORT=$(run_worker machine inspect --format '{{.SSHConfig.Port}}' "$MACHINE")
case "$SSH_PORT" in *[!0-9]*|'') die "invalid forwarded SSH port: $SSH_PORT" ;; esac
[ "$SSH_PORT" -gt 0 ] && [ "$SSH_PORT" -le 65535 ] || die "invalid forwarded SSH port: $SSH_PORT"

/usr/bin/sudo -u "$CALLER_USER" \
  /usr/bin/env -i HOME="$CALLER_HOME" USER="$CALLER_USER" LOGNAME="$CALLER_USER" PATH="$SAFE_PATH" \
  /bin/mkdir -m 700 "$OUTPUT_DIR"
KEY=$OUTPUT_DIR/id_ed25519
/usr/bin/sudo -u "$CALLER_USER" \
  /usr/bin/env -i HOME="$CALLER_HOME" USER="$CALLER_USER" LOGNAME="$CALLER_USER" PATH="$SAFE_PATH" \
  /usr/bin/ssh-keygen -q -t ed25519 -N '' -C "$MACHINE-disposable" -f "$KEY"

PUBKEY=$(/usr/bin/sudo -u "$CALLER_USER" \
  /usr/bin/env -i HOME="$CALLER_HOME" USER="$CALLER_USER" LOGNAME="$CALLER_USER" PATH="$SAFE_PATH" \
  /bin/cat "$KEY.pub")
if ! printf '%s\n' "$PUBKEY" | awk -v comment="$MACHINE-disposable" '
  NF == 3 && $1 == "ssh-ed25519" && $2 ~ /^[A-Za-z0-9+\/=]+$/ && $3 == comment { valid=1 }
  END { exit !valid }
'; then
  die "generated SSH public key has an unexpected format"
fi

run_worker machine ssh "$MACHINE" sudo /usr/sbin/useradd --create-home --user-group --shell /bin/bash "$GUEST_ACCOUNT"
run_worker machine ssh "$MACHINE" sudo /usr/bin/loginctl enable-linger "$GUEST_ACCOUNT"
run_worker machine ssh "$MACHINE" sudo /usr/bin/install -d -m 700 -o "$GUEST_ACCOUNT" -g "$GUEST_ACCOUNT" "/home/$GUEST_ACCOUNT/.ssh"
AUTHORIZED_KEY="no-agent-forwarding,no-X11-forwarding,no-pty,no-user-rc $PUBKEY"
printf '%s\n' "$AUTHORIZED_KEY" | run_worker machine ssh "$MACHINE" \
  "sudo /usr/bin/tee /home/$GUEST_ACCOUNT/.ssh/authorized_keys >/dev/null"
run_worker machine ssh "$MACHINE" sudo /usr/bin/chown "$GUEST_ACCOUNT:$GUEST_ACCOUNT" "/home/$GUEST_ACCOUNT/.ssh/authorized_keys"
run_worker machine ssh "$MACHINE" sudo /usr/bin/chmod 600 "/home/$GUEST_ACCOUNT/.ssh/authorized_keys"
run_worker machine ssh "$MACHINE" \
  "grep -Eq '^$GUEST_ACCOUNT:[0-9]+:[1-9][0-9]*$' /etc/subuid && grep -Eq '^$GUEST_ACCOUNT:[0-9]+:[1-9][0-9]*$' /etc/subgid" || \
  die "guest account lacks subordinate UID or GID ranges"

install_network_guard

run_guest /usr/bin/systemctl --user enable --now podman.socket
GUEST_UID=$(run_guest /usr/bin/id -u)
case "$GUEST_UID" in *[!0-9]*|'') die "invalid guest UID: $GUEST_UID" ;; esac
[ "$GUEST_UID" -ne 0 ] || die "agent guest account must not be root"
GUEST_GROUPS=$(run_guest /usr/bin/id -Gn)
case " $GUEST_GROUPS " in *' wheel '*) die "agent guest account must not be in wheel" ;; esac
if run_guest /usr/bin/sudo -n /usr/bin/true >/dev/null 2>&1; then
  die "agent guest account has passwordless sudo"
fi
ROOTLESS=$(run_guest /usr/bin/podman info --format '{{.Host.Security.Rootless}}')
[ "$ROOTLESS" = true ] || die "agent guest Podman service is not rootless"
run_guest /usr/bin/test -S "/run/user/$GUEST_UID/podman/podman.sock"

case $(run_guest /usr/bin/uname -m) in
  x86_64)
    WOODPECKER_ARCH=amd64
    WOODPECKER_SHA256=35adf958d616588162d1329fc805f4c2f6e3ef610653175978a0180859ea0c12
    ;;
  aarch64)
    WOODPECKER_ARCH=arm64
    WOODPECKER_SHA256=52d807e274fa4de3d48411371216f3074f241a5fb5a1aaddd84553bef969d5ee
    ;;
  *) die "unsupported Podman-machine architecture" ;;
esac
WOODPECKER_ARCHIVE=woodpecker-cli_linux_$WOODPECKER_ARCH.tar.gz
WOODPECKER_URL=https://github.com/woodpecker-ci/woodpecker/releases/download/v$WOODPECKER_VERSION
run_guest /usr/bin/install -d -m 700 \
  "/home/$GUEST_ACCOUNT/.local/bin" \
  "/home/$GUEST_ACCOUNT/.local/libexec/agent-podman" \
  "/home/$GUEST_ACCOUNT/.config/systemd/user"
run_guest /usr/bin/curl -fsSLo "/tmp/$WOODPECKER_ARCHIVE" "$WOODPECKER_URL/$WOODPECKER_ARCHIVE"
WOODPECKER_ACTUAL_SHA256=$(run_guest /usr/bin/sha256sum "/tmp/$WOODPECKER_ARCHIVE" | \
  /usr/bin/awk 'NF >= 1 { print $1; exit }')
[ "$WOODPECKER_ACTUAL_SHA256" = "$WOODPECKER_SHA256" ] || \
  die "Woodpecker archive checksum mismatch"
run_guest /usr/bin/tar -xzf "/tmp/$WOODPECKER_ARCHIVE" -C "/home/$GUEST_ACCOUNT/.local/bin" woodpecker-cli
run_guest /usr/bin/rm -f "/tmp/$WOODPECKER_ARCHIVE"
SUPERVISOR_TARGET=/home/$GUEST_ACCOUNT/.local/libexec/agent-podman/woodpecker-supervisor
run_guest /usr/bin/tee "$SUPERVISOR_TARGET" < "$SUPERVISOR_SOURCE" >/dev/null
run_guest /usr/bin/chmod 700 "$SUPERVISOR_TARGET"
SUPERVISOR_SOURCE_SHA256=$(/usr/bin/shasum -a 256 "$SUPERVISOR_SOURCE" | \
  /usr/bin/awk 'NF >= 1 { print $1; exit }')
SUPERVISOR_TARGET_SHA256=$(run_guest /usr/bin/sha256sum "$SUPERVISOR_TARGET" | \
  /usr/bin/awk 'NF >= 1 { print $1; exit }')
[ "$SUPERVISOR_TARGET_SHA256" = "$SUPERVISOR_SOURCE_SHA256" ] || \
  die "installed Woodpecker supervisor checksum mismatch"
run_guest /usr/bin/podman pull "$RELABEL_IMAGE"

printf '%s\n' \
  '[Unit]' \
  'Description=Reap abandoned agent Podman Woodpecker workspaces' \
  '[Service]' \
  'Type=oneshot' \
  "ExecStart=/home/$GUEST_ACCOUNT/.local/libexec/agent-podman/woodpecker-supervisor reap 00000000000000000000000000000000" | \
  run_guest /usr/bin/tee "/home/$GUEST_ACCOUNT/.config/systemd/user/agent-podman-reaper.service" >/dev/null
printf '%s\n' \
  '[Unit]' \
  'Description=Periodically reap abandoned agent Podman workspaces' \
  '[Timer]' \
  'OnBootSec=15min' \
  'OnUnitActiveSec=1h' \
  '[Install]' \
  'WantedBy=timers.target' | \
  run_guest /usr/bin/tee "/home/$GUEST_ACCOUNT/.config/systemd/user/agent-podman-reaper.timer" >/dev/null
run_guest /usr/bin/systemctl --user daemon-reload
run_guest /usr/bin/systemctl --user enable --now agent-podman-reaper.timer

SANDBOX_KNOWN_HOSTS=$OUTPUT_DIR/known_hosts.sandbox
HOST_KEY_LINES=$(/usr/bin/sudo -u "$CALLER_USER" \
  /usr/bin/env -i HOME="$CALLER_HOME" USER="$CALLER_USER" LOGNAME="$CALLER_USER" PATH="$SAFE_PATH" \
  /usr/bin/ssh-keygen -F "[127.0.0.1]:$SSH_PORT" -f "$OUTPUT_DIR/known_hosts" | \
  /usr/bin/awk '$2 ~ /^ssh-/ { print "agent-podman " $2 " " $3 }')
[ -n "$HOST_KEY_LINES" ] || die "could not derive the sandbox SSH host key"
printf '%s\n' "$HOST_KEY_LINES" | \
  /usr/bin/sudo -u "$CALLER_USER" \
    /usr/bin/env -i HOME="$CALLER_HOME" USER="$CALLER_USER" LOGNAME="$CALLER_USER" PATH="$SAFE_PATH" \
    /bin/sh -c 'umask 077; set -C; /bin/cat > "$1"' sh "$SANDBOX_KNOWN_HOSTS"

printf '%s\n' \
  "AGENT_PODMAN_SSH_USER=$GUEST_ACCOUNT" \
  "AGENT_PODMAN_SSH_PORT=$SSH_PORT" \
  "CONTAINER_HOST=ssh://$GUEST_ACCOUNT@host.docker.internal:$SSH_PORT/run/user/$GUEST_UID/podman/podman.sock" \
  'CONTAINER_SSHKEY=/run/secrets/agent-podman-key' | \
  /usr/bin/sudo -u "$CALLER_USER" \
    /usr/bin/env -i HOME="$CALLER_HOME" USER="$CALLER_USER" LOGNAME="$CALLER_USER" PATH="$SAFE_PATH" \
    /bin/sh -c 'umask 077; set -C; /bin/cat > "$1"' sh "$OUTPUT_DIR/connection.env"

verify_host_account

trap - EXIT HUP INT TERM
rm -f "$TMP_CONFIG"
printf '\nCreated no-mount machine %s under locked host account %s.\n' "$MACHINE" "$ACCOUNT"
printf 'Agent access is rootless and non-sudo as guest user %s.\n' "$GUEST_ACCOUNT"
printf 'PF blocks the worker from local, private, link-local, multicast, and reserved networks.\n'
printf 'Access directory: %s\n' "$OUTPUT_DIR"
printf 'Verified guest mount inventory:\n%s\n' "$MOUNTS"
