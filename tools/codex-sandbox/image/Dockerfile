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

FROM node:24-slim AS pi-node
COPY ./tools/pi-npm/package.json ./tools/pi-npm/package-lock.json /opt/pi-npm/
RUN npm ci --ignore-scripts --prefix /opt/pi-npm \
    && mkdir -p /opt/agent-pi/lib \
    && cp -a /opt/pi-npm/node_modules /opt/agent-pi/lib/node_modules

FROM alpine:3.22 AS pi-bun
ARG PI_VERSION=0.84.2
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
        amd64) pi_arch=x64 ;; \
        arm64) pi_arch=arm64 ;; \
        *) echo "Unsupported Pi architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && pi_archive="pi-linux-${pi_arch}.tar.gz" \
    && wget -q "https://github.com/earendil-works/pi/releases/download/v${PI_VERSION}/${pi_archive}" \
    && wget -q "https://github.com/earendil-works/pi/releases/download/v${PI_VERSION}/SHA256SUMS" \
    && grep "  ${pi_archive}$" SHA256SUMS > pi.sha256 \
    && test -s pi.sha256 \
    && sha256sum -c pi.sha256 \
    && mkdir -p /opt/agent-pi/standalone \
    && tar -xzf "${pi_archive}" --strip-components=1 -C /opt/agent-pi/standalone

FROM ${BASE_IMAGE} AS pi-runtime
COPY --link --from=pi-node /opt/agent-pi /opt/agent-pi
COPY --link --from=pi-bun /opt/agent-pi/standalone /opt/agent-pi/standalone
RUN if [ -e /etc/alpine-release ]; then \
        rm -rf /opt/agent-pi/standalone; \
    else \
        rm -rf /opt/agent-pi/lib; \
    fi
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
COPY --link --from=pi /opt/agent-pi /opt/agent-pi

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
