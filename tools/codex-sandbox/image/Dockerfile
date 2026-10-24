# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE=node:24-alpine3.22
ARG JJ_IMAGE

FROM ${JJ_IMAGE} AS jj

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
ARG DOCKER_VERSION=29.8.0
ARG BUILDX_VERSION=0.37.0
ARG TYPST_VERSION=0.15.1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,target=/var/cache/apk,sharing=locked \
    --mount=type=cache,target=/var/cache/yum,sharing=locked \
    BB_VERSION=${BB_VERSION} \
    GH_VERSION=${GH_VERSION} \
    DOCKER_VERSION=${DOCKER_VERSION} \
    BUILDX_VERSION=${BUILDX_VERSION} \
    TYPST_VERSION=${TYPST_VERSION} \
    install-agent-tools \
    && mkdir -p /opt/agent-tools/bin /opt/agent-tools/libexec \
    && cp -a \
        /usr/local/bin/gh \
        /usr/local/bin/typst \
        /opt/agent-tools/bin/ \
    && cp -a /usr/local/bin/bb /usr/local/bin/docker /opt/agent-tools/libexec/
# A JJ release update must not rerun downloads for unrelated tools.
COPY --from=jj /trusted/bin/jj /opt/agent-tools/libexec/jj
RUN /opt/agent-tools/libexec/jj --version

FROM node:24-alpine3.22 AS pi-extensions
COPY ./tools/pi-npm/package.json ./tools/pi-npm/package-lock.json /opt/pi-npm/
RUN npm ci --ignore-scripts --prefix /opt/pi-npm
COPY ./tools/pi-link/package.json ./tools/pi-link/package-lock.json /opt/pi-link/
RUN npm ci --ignore-scripts --omit=dev --prefix /opt/pi-link

FROM alpine:3.22 AS pi-source
RUN apk add --no-cache curl libarchive-tools
ARG PI_REVISION
RUN test -n "${PI_REVISION}" && printf '%s\n' "${PI_REVISION}" > /REVISION
RUN curl -L --fail-with-body --show-error -o /pi.zip https://github.com/jyn514/pi/archive/${PI_REVISION}.zip
RUN mkdir /src && bsdtar -xf pi.zip --strip-components=1 -C /src

FROM oven/bun:1.3.14 AS bun-build
FROM oven/bun:1.3.14-alpine AS bun-runtime

FROM node:24-bookworm-slim AS pi-build
# The Debian build stage requires Bun's glibc binary.
COPY --from=bun-build /usr/local/bin/bun /usr/local/bin/bun
COPY --from=pi-source /src /opt/agent-pi/src
COPY --from=pi-source /REVISION /opt/agent-pi/REVISION
WORKDIR /opt/agent-pi/src
RUN npm ci --ignore-scripts --prefix /opt/agent-pi/src \
    && if [ -d packages/ai/src/providers/data ]; then rm -r packages/ai/src/providers/data; fi \
    && npm run hydrate:pinned-model-data --prefix /opt/agent-pi/src \
    && chmod -R a+rX packages/ai/src/providers/data \
    && npm run build:offline --prefix /opt/agent-pi/src \
    &&  node scripts/build-coding-agent-binary.mjs --outfile packages/coding-agent/dist/pi \
    && npm --prefix packages/coding-agent run copy-binary-assets

FROM pi-build AS pi-runtime-files
COPY ./tools/codex-sandbox/image/stage-pi-runtime.mjs /opt/stage-pi-runtime.mjs
RUN node /opt/stage-pi-runtime.mjs /opt/agent-pi /opt/pi-runtime

FROM pi-build AS pi-extension-cache
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates
ENV HOME=/home/codex
ENV PI_PACKAGE_DIR=/opt/agent-pi/src/packages/coding-agent
ENV npm_config_ignore_scripts=true npm_config_legacy_peer_deps=true
WORKDIR /workspace
COPY --from=pi-extensions /opt/pi-link /home/codex/.pi/agent/pi-link
COPY ./config/pi-agent/settings.json /home/codex/.pi/agent/settings.json
COPY ./tools/codex-sandbox/image/cache-pi-extensions.mjs /opt/cache-pi-extensions.mjs
RUN node /opt/cache-pi-extensions.mjs install
COPY ./config/pi-agent/pi-extensions /home/codex/.pi/agent/pi-extensions
COPY ./tools/pi-link/index.ts /home/codex/.pi/agent/pi-link/index.ts
COPY ./tools/pi-link/skills /home/codex/.pi/agent/pi-link/skills
COPY ./tools/codex-sandbox/auth-proxy/pi-extension /home/codex/.pi/agent/extensions/codex-sidecar
RUN --network=none PI_OFFLINE=1 node /opt/cache-pi-extensions.mjs warm

FROM agent-deps AS pi-runtime
COPY --from=pi-runtime-files /opt/pi-runtime /opt/agent-pi
COPY --from=pi-extensions /opt/pi-npm/node_modules /opt/agent-pi/src/node_modules
# Runtime libc follows BASE_IMAGE. Select the matching binary rather than using
# gcompat to approximate glibc behavior beyond startup on Alpine.
COPY --from=bun-build /usr/local/bin/bun /opt/bun/glibc
COPY --from=bun-runtime /usr/local/bin/bun /opt/bun/musl
RUN if [ -e /etc/alpine-release ]; then bun_variant=musl; else bun_variant=glibc; fi \
    && cp "/opt/bun/${bun_variant}" /usr/local/bin/bun \
    && rm -rf /opt/bun
COPY --chmod=755 ./tools/codex-sandbox/image/pi /opt/agent-pi/bin/pi
COPY --chmod=755 ./tools/codex-sandbox/image/agent-entrypoint /opt/agent-tools/bin/agent-entrypoint
COPY ./tools/codex-sandbox/image/tool-worker.mjs /opt/agent-tools/bin/tool-worker.mjs
COPY ./config/pi-agent/pi-extensions/commit-boundary/operations.mjs /opt/agent-tools/bin/commit-boundary-operations.mjs
COPY ./tools/codex-sandbox/image/tool-connect.mjs /opt/agent-tools/bin/tool-connect.mjs
COPY ./tools/codex-sandbox/image/check-pi-runtime.mjs /opt/agent-pi/check-runtime.mjs
COPY ./tools/codex-sandbox/image/check-bun.test.ts /opt/agent-pi/check-bun.test.ts
RUN if [ -e /etc/alpine-release ]; then \
        node /opt/agent-pi/check-runtime.mjs \
        && bun test /opt/agent-pi/check-bun.test.ts; \
    fi
COPY --chmod=755 ./tools/codex-sandbox/image/with-github-token /opt/agent-tools/bin/with-github-token

FROM pi-runtime AS sandbox-runtime
ARG PI_REVISION
LABEL dev.codex.pi-revision="${PI_REVISION}"
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
ENV DOTFILES_SANDBOX=1
ENV EDITOR=vi VISUAL=vi
RUN mkdir -p ${HOME}/.pi/agent ${HOME}/.codex /src /workspace

# Reuse noninteractive dotfile semantics without personal shell hooks.
ENV JJ_CONFIG=${HOME}/.config/jj/config.toml
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/editorconfig ${HOME}/.editorconfig
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/inputrc ${HOME}/.config/readline/inputrc
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/codex-sandbox/image/gitconfig ${HOME}/.config/git/config
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/jj.toml ${JJ_CONFIG}
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/jj-proxy/client ./tools/jj-proxy/route.py /tools/jj-proxy/
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/zulip-proxy/client ./tools/zulip-proxy/protocol.json /tools/zulip-proxy/
COPY --chown=${AGENT_UID}:${AGENT_GID} ./bin/zulip /opt/agent-tools/bin/zulip
# Preserve the source layout without relying on /bin (a symlink on Debian).
COPY --chmod=755 --chown=${AGENT_UID}:${AGENT_GID} ./tools/extract-chat/extract-chat /tools/chat-export/tools/extract-chat/extract-chat
COPY --chown=${AGENT_UID}:${AGENT_GID} ./libexec/chat-history.clj /tools/chat-export/libexec/chat-history.clj
COPY --chmod=755 --chown=${AGENT_UID}:${AGENT_GID} ./bin/codex-to-pi /tools/chat-export/bin/codex-to-pi
RUN ln -s /tools/chat-export/tools/extract-chat/extract-chat /opt/agent-tools/bin/extract-chat
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-docker/woodpecker-cli /tools/agent-docker/woodpecker-cli
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-docker/woodpecker-cli /opt/agent-tools/bin/woodpecker-cli
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-split/bb /tools/agent-split/bb
COPY --chown=${AGENT_UID}:${AGENT_GID} ./tools/agent-split/src /tools/agent-split/src
COPY --chown=${AGENT_UID}:${AGENT_GID} ./lib/shell/lib.sh /lib/shell/lib.sh
# Keep generated editor, language-server, and tool state out of jj snapshots.
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/gitignore ${HOME}/.config/git/ignore

# Package runtime entrypoints only; developer bytecode must not invalidate images.
COPY --chmod=755 --chown=${AGENT_UID}:${AGENT_GID} ./tools/codex-sandbox/image/codex ./libexec/agent-wrappers/diff-check ./libexec/agent-wrappers/java ./libexec/agent-wrappers/jj ./libexec/agent-wrappers/jj-conflict ./libexec/agent-wrappers/paste ./libexec/agent-wrappers/rg /libexec/agent-wrappers/
COPY --chmod=755 --chown=${AGENT_UID}:${AGENT_GID} ./libexec/sandbox-wrappers/docker ./libexec/sandbox-wrappers/gateway-transport ./libexec/sandbox-wrappers/docker-ssh /libexec/sandbox-wrappers/
COPY --from=tools /usr/local/lib/docker/cli-plugins/docker-buildx /usr/local/lib/docker/cli-plugins/docker-buildx
RUN ln -s ../../tools/agent-split/bb /libexec/agent-wrappers/bb \
    && ln -s ../../tools/jj-proxy/client /libexec/agent-wrappers/jj-proxy-client \
    && ln -s ../../tools/agent-docker/woodpecker-cli /libexec/agent-wrappers/woodpecker-cli \
    && if real_java=$(command -v java); then \
        ln -s "$real_java" /opt/agent-tools/libexec/java; \
    fi \
    && if real_rg=$(command -v rg); then \
        ln -s "$real_rg" /opt/agent-tools/libexec/rg; \
    fi \
    && for command in bb java jj rg; do \
        ln -sf "../../../libexec/agent-wrappers/$command" "/opt/agent-tools/bin/$command"; \
    done \
    && for command in docker; do \
        ln -sf "../../../libexec/sandbox-wrappers/$command" "/opt/agent-tools/bin/$command"; \
    done
ENV BB_REAL=/opt/agent-tools/libexec/bb
ENV BB_SOURCE_ROOT=/
ENV CONTAINER_CLI_REAL_DIR=/opt/agent-tools/libexec
ENV JAVA_REAL=/opt/agent-tools/libexec/java
ENV JJ_REAL=/opt/agent-tools/libexec/jj
ENV JJ_ROUTE_HELPER=/tools/jj-proxy/route.py
ENV RG_REAL=/opt/agent-tools/libexec/rg
ENV PATH=/libexec/sandbox-wrappers:/libexec/agent-wrappers:/opt/agent-tools/bin:/opt/agent-pi/bin:${PATH}

USER ${AGENT_UID}:${AGENT_GID}
WORKDIR /workspace

# Use the final Node version, paths, and UID: bytecode is not portable across
# Node versions, and every new container should start with a populated cache.
RUN --network=none if [ -e /etc/alpine-release ]; then pi --offline --help >/dev/null; fi

ENV COLORTERM=truecolor
ENV TERM=xterm-256color
ENTRYPOINT ["/opt/agent-tools/bin/agent-entrypoint"]
