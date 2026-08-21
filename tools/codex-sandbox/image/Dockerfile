# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE=node:24-alpine3.22

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
ARG PI_REVISION=b71f69a5dc996fd1d781f69a44add1485a83079e
RUN apk add --no-cache git \
    && git clone --filter=blob:none https://github.com/jyn514/pi.git /src \
    && git -C /src checkout --detach "${PI_REVISION}" \
    && test "$(git -C /src rev-parse HEAD)" = "${PI_REVISION}" \
    && rm -rf /src/.git \
    && printf '%s\n' "${PI_REVISION}" > /REVISION

FROM node:24-alpine3.22 AS pi-build
COPY --link --from=pi-source /src /opt/agent-pi/src
COPY --link --from=pi-source /REVISION /opt/agent-pi/REVISION
RUN npm ci --ignore-scripts --prefix /opt/agent-pi/src \
    && npm run hydrate:model-data --prefix /opt/agent-pi/src \
    && npm run build:offline --prefix /opt/agent-pi/src

FROM oven/bun:1.3.14 AS bun

FROM node:24-bookworm-slim AS pi-binary
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
COPY --link --from=pi-source /src /opt/agent-pi/src
COPY --link --from=pi-build /opt/agent-pi/src/packages/ai/src/providers/data \
    /opt/agent-pi/src/packages/ai/src/providers/data
WORKDIR /opt/agent-pi/src
RUN npm ci --ignore-scripts \
    && npm run build:offline \
    && bun build --compile --no-compile-autoload-bunfig \
        ./packages/coding-agent/dist/bun/cli.js \
        ./packages/coding-agent/src/utils/image-resize-worker.ts \
        --outfile packages/coding-agent/dist/pi \
    && npm --prefix packages/coding-agent run copy-binary-assets \
    && mv packages/coding-agent/dist /opt/agent-pi/standalone

FROM ${BASE_IMAGE} AS pi-runtime
COPY --link --from=pi-build /opt/agent-pi /opt/agent-pi
COPY --link --from=pi-binary /opt/agent-pi/standalone /opt/agent-pi/standalone
COPY --link --from=pi-extensions /opt/pi-npm/node_modules /opt/agent-pi/src/node_modules
COPY --chmod=755 ./tools/codex-sandbox/image/pi /opt/agent-pi/bin/pi

FROM pi-runtime
COPY ./tools/codex-sandbox/image/install-deps.sh /usr/local/bin/install-agent-deps
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,target=/var/cache/apk,sharing=locked \
    --mount=type=cache,target=/var/cache/yum,sharing=locked \
    KEEP_PACKAGE_CACHE=1 install-agent-deps \
    && rm /usr/local/bin/install-agent-deps

COPY --link --from=tools /opt/agent-tools /opt/agent-tools

COPY ./tools/codex-sandbox/image/create-user.sh .
ARG AGENT_UID=1000
ARG AGENT_GID=1000
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
RUN mkdir -p ${HOME}/.pi/agent ${HOME}/.codex /src/work \
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
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-split /tools/agent-split
COPY --chown=${AGENT_UID}:${AGENT_GID} ./lib/shell/lib.sh /lib/shell/lib.sh
# Keep generated editor, language-server, and tool state out of jj snapshots.
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/gitignore ${HOME}/.config/git/ignore

COPY --chown=${AGENT_UID}:${AGENT_GID} ./libexec/agent-wrappers /libexec/agent-wrappers
ENV PATH=/libexec/agent-wrappers:/opt/agent-tools/bin:/opt/agent-pi/bin:${PATH}

USER ${AGENT_UID}:${AGENT_GID}
WORKDIR /src/work

ENV COLORTERM=truecolor
ARG TERM=xterm-256color
ENV TERM=${TERM}
ENTRYPOINT ["pi", "--offline", "--approve"]
