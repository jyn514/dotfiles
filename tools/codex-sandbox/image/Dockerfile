# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE=node:24-alpine3.22

FROM ${BASE_IMAGE} AS agent-deps
COPY ./tools/codex-sandbox/image/install-deps.sh /usr/local/bin/install-agent-deps
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,target=/var/cache/apk,sharing=locked \
    --mount=type=cache,target=/var/cache/yum,sharing=locked \
    KEEP_PACKAGE_CACHE=1 install-agent-deps \
    && rm /usr/local/bin/install-agent-deps

FROM alpine:3.22 AS tools
COPY ./tools/codex-sandbox/image/install-tools.sh /usr/local/bin/install-agent-tools
ARG BB_VERSION=1.13.219
ARG GH_VERSION=2.76.1
ARG JJ_VERSION=0.42.0
ARG PODMAN_VERSION=6.0.1
ARG TYPST_VERSION=0.15.1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,target=/var/cache/apk,sharing=locked \
    --mount=type=cache,target=/var/cache/yum,sharing=locked \
    BB_VERSION=${BB_VERSION} \
    GH_VERSION=${GH_VERSION} \
    JJ_VERSION=${JJ_VERSION} \
    PODMAN_VERSION=${PODMAN_VERSION} \
    TYPST_VERSION=${TYPST_VERSION} \
    install-agent-tools \
    && mkdir -p /opt/agent-tools/bin \
    && cp -a \
        /usr/local/bin/bb \
        /usr/local/bin/gh \
        /usr/local/bin/jj \
        /usr/local/bin/podman \
        /usr/local/bin/typst \
        /opt/agent-tools/bin/ \
    && ln -s podman /opt/agent-tools/bin/docker

FROM node:24-alpine3.22 AS pi-extensions
COPY ./tools/pi-npm/package.json ./tools/pi-npm/package-lock.json /opt/pi-npm/
RUN npm ci --ignore-scripts --prefix /opt/pi-npm

FROM alpine:3.22 AS pi-source
RUN apk add --no-cache curl libarchive-tools
ARG PI_REVISION=9bf3cc9efb983887c6da07f6f9afecbbfcf85d83
RUN printf '%s\n' "${PI_REVISION}" > /REVISION
RUN curl -L --fail-with-body --show-error -o /pi.zip https://github.com/jyn514/pi/archive/${PI_REVISION}.zip
RUN mkdir /src && bsdtar -xf pi.zip --strip-components=1 -C /src

FROM oven/bun:1.3.14 AS bun

FROM node:24-bookworm-slim AS pi-build
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
COPY --from=pi-source /src /opt/agent-pi/src
COPY --from=pi-source /REVISION /opt/agent-pi/REVISION
WORKDIR /opt/agent-pi/src
RUN npm ci --ignore-scripts --prefix /opt/agent-pi/src \
    && npm run hydrate:pinned-model-data --prefix /opt/agent-pi/src \
    && chmod -R a+rX packages/ai/src/providers/data \
    && npm run build:offline --prefix /opt/agent-pi/src \
    && bun build --compile --no-compile-autoload-bunfig \
        ./packages/coding-agent/dist/bun/cli.js \
        ./packages/coding-agent/src/utils/image-resize-worker.ts \
        --outfile packages/coding-agent/dist/pi \
    && npm --prefix packages/coding-agent run copy-binary-assets \
    && mkdir -p /opt/agent-pi/standalone \
    && cp -a packages/coding-agent/dist/. /opt/agent-pi/standalone/

FROM pi-build AS pi-extension-cache
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates
ENV HOME=/home/codex
ENV PI_PACKAGE_DIR=/opt/agent-pi/src/packages/coding-agent
ENV npm_config_ignore_scripts=true npm_config_legacy_peer_deps=true
WORKDIR /workspace
COPY ./config/pi.json /home/codex/.pi/agent/settings.json
COPY ./tools/codex-sandbox/image/cache-pi-extensions.mjs /opt/cache-pi-extensions.mjs
RUN node /opt/cache-pi-extensions.mjs install
COPY ./config/pi-extensions /home/codex/.pi/agent/pi-extensions
COPY ./tools/codex-sandbox/auth-proxy/pi-extension /home/codex/.pi/agent/extensions/codex-sidecar
RUN --network=none PI_OFFLINE=1 node /opt/cache-pi-extensions.mjs warm

FROM agent-deps AS pi-runtime
COPY --from=pi-build /opt/agent-pi /opt/agent-pi
COPY --from=pi-extensions /opt/pi-npm/node_modules /opt/agent-pi/src/node_modules
COPY --chmod=755 ./tools/codex-sandbox/image/pi /opt/agent-pi/bin/pi
COPY ./tools/codex-sandbox/image/check-pi-runtime.mjs /opt/agent-pi/check-runtime.mjs
RUN if [ -e /etc/alpine-release ]; then node /opt/agent-pi/check-runtime.mjs; fi
COPY --chmod=755 ./tools/codex-sandbox/image/host-editor /opt/agent-tools/bin/host-editor
COPY --chmod=755 ./tools/codex-sandbox/image/with-github-token /opt/agent-tools/bin/with-github-token

FROM pi-runtime
COPY --from=tools /opt/agent-tools /opt/agent-tools

COPY ./tools/codex-sandbox/image/create-user.sh .
ARG AGENT_UID=1000
ARG AGENT_GID=1000
COPY --from=pi-extension-cache --chown=${AGENT_UID}:${AGENT_GID} /tmp/jiti /tmp/jiti
RUN ./create-user.sh "${AGENT_UID}" "${AGENT_GID}" codex /home/codex \
    && agent_name=$(awk -F: -v uid="${AGENT_UID}" '$3 == uid { print $1; exit }' /etc/passwd) \
    && test -n "${agent_name}" \
    && printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "${agent_name}" \
        > /etc/sudoers.d/codex \
    && chmod 0440 /etc/sudoers.d/codex \
    && rm ./create-user.sh

COPY ./tools/codex-sandbox/image/agent-wrappers-path.sh /etc/profile.d/agent-wrappers-path.sh
COPY ./tools/codex-sandbox/image/dotfiles-profile.sh /etc/profile.d/dotfiles-profile.sh

ENV HOME=/home/codex
ENV EDITOR=vi VISUAL=vi
RUN mkdir -p ${HOME}/.pi/agent ${HOME}/.codex /src /workspace \
    && chown -R ${AGENT_UID}:${AGENT_GID} \
        ${HOME} /src

# Reuse noninteractive dotfile semantics without personal shell hooks.
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/editorconfig ${HOME}/.editorconfig
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/inputrc ${HOME}/.config/readline/inputrc
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/codex-sandbox/image/gitconfig ${HOME}/.config/git/config
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/jj-proxy/client /tools/jj-proxy/client
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/zulip-proxy/client /tools/zulip-proxy/client
COPY --chown=${AGENT_UID}:${AGENT_GID} ./bin/zulip /opt/agent-tools/bin/zulip
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-podman/woodpecker-cli /tools/agent-podman/woodpecker-cli
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-podman/woodpecker-cli /opt/agent-tools/bin/woodpecker-cli
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-split/bb /tools/agent-split/bb
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-split/src /tools/agent-split/src
COPY --chown=${AGENT_UID}:${AGENT_GID} ./lib/shell/lib.sh /lib/shell/lib.sh
# Keep generated editor, language-server, and tool state out of jj snapshots.
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/gitignore ${HOME}/.config/git/ignore

# Package runtime entrypoints only; developer bytecode must not invalidate images.
COPY --chown=${AGENT_UID}:${AGENT_GID} ./libexec/agent-wrappers/diff-check ./libexec/agent-wrappers/java ./libexec/agent-wrappers/jj ./libexec/agent-wrappers/paste ./libexec/agent-wrappers/rg /libexec/agent-wrappers/
RUN ln -s ../../tools/agent-split/bb /libexec/agent-wrappers/bb \
    && ln -s ../../tools/jj-proxy/client /libexec/agent-wrappers/jj-proxy-client \
    && ln -s ../../tools/agent-podman/woodpecker-cli /libexec/agent-wrappers/woodpecker-cli
ENV PATH=/libexec/agent-wrappers:/opt/agent-tools/bin:/opt/agent-pi/bin:${PATH}

USER ${AGENT_UID}:${AGENT_GID}
WORKDIR /workspace

# Use the final Node version, paths, and UID: bytecode is not portable across
# Node versions, and every new container should start with a populated cache.
RUN --network=none if [ -e /etc/alpine-release ]; then pi --offline --help >/dev/null; fi

ENV COLORTERM=truecolor
ARG TERM=xterm-256color
ENV TERM=${TERM}
ENTRYPOINT ["pi", "--offline", "--approve"]
