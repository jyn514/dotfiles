#!/bin/sh
PODMAN="$(command -v podman)";
sudo -u _agentpodman env -i \
  HOME=/Users/_agentpodman \
  USER=_agentpodman \
  LOGNAME=_agentpodman \
  CONTAINERS_CONF=/Users/_agentpodman/.config/containers/containers.conf \
  PATH="$(dirname "$PODMAN"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  "$PODMAN" machine start agent-podman
