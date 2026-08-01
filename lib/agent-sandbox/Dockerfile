# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE=node:slim

FROM ${BASE_IMAGE} AS tools
COPY ./lib/agent-sandbox/install-tools.sh /usr/local/bin/install-agent-tools
ARG GH_VERSION=2.76.1
ARG JJ_VERSION=0.42.0
ARG PODMAN_VERSION=6.0.1
ARG TYPST_VERSION=0.15.1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,target=/var/cache/apk,sharing=locked \
    --mount=type=cache,target=/var/cache/yum,sharing=locked \
    GH_VERSION=${GH_VERSION} \
    JJ_VERSION=${JJ_VERSION} \
    PODMAN_VERSION=${PODMAN_VERSION} \
    TYPST_VERSION=${TYPST_VERSION} \
    install-agent-tools

FROM ${BASE_IMAGE}
COPY ./lib/agent-sandbox/install-deps.sh /usr/local/bin/install-agent-deps
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,target=/var/cache/apk,sharing=locked \
    --mount=type=cache,target=/var/cache/yum,sharing=locked \
    KEEP_PACKAGE_CACHE=1 install-agent-deps \
    && rm /usr/local/bin/install-agent-deps

COPY --from=tools /usr/local/bin/gh /usr/local/bin/gh
COPY --from=tools /usr/local/bin/jj /usr/local/bin/jj
COPY --from=tools /usr/local/bin/podman /usr/local/bin/podman
COPY --from=tools /usr/local/bin/typst /usr/local/bin/typst
RUN ln -s /usr/local/bin/podman /usr/local/bin/docker \
    && docker --version \
    && gh --version \
    && jj --version \
    && podman --version \
    && typst --version

COPY ./lib/agent-sandbox/create-user.sh .
ARG AGENT_UID=1000
ARG AGENT_GID=1000
RUN ./create-user.sh "${AGENT_UID}" "${AGENT_GID}" codex /home/codex \
    && agent_name=$(awk -F: -v uid="${AGENT_UID}" '$3 == uid { print $1; exit }' /etc/passwd) \
    && test -n "${agent_name}" \
    && printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "${agent_name}" \
        > /etc/sudoers.d/codex \
    && chmod 0440 /etc/sudoers.d/codex \
    && rm ./create-user.sh

COPY ./lib/agent-sandbox/agent-wrappers-path.sh /etc/profile.d/agent-wrappers-path.sh

ENV HOME=/home/codex
ARG CODEX_HOME
ENV CODEX_HOME=${CODEX_HOME}
ENV CODEX_SQLITE_HOME=/codex-sqlite
RUN mkdir -p ${CODEX_HOME} ${CODEX_SQLITE_HOME} /src/work \
    && chown -R ${AGENT_UID}:${AGENT_GID} \
        ${HOME} ${CODEX_HOME} ${CODEX_SQLITE_HOME} /src

ARG CODEX_VERSION=0.144.4
RUN npm install --global "@openai/codex@${CODEX_VERSION}"

# Keep generated editor, language-server, and tool state out of jj snapshots.
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/gitignore ${HOME}/.config/git/ignore

COPY --chown=${AGENT_UID}:${AGENT_GID} ./lib/agent-wrappers /lib/agent-wrappers
ENV PATH=/lib/agent-wrappers:${PATH}

USER ${AGENT_UID}:${AGENT_GID}
WORKDIR /src/work

ENV COLORTERM=truecolor
ARG TERM=xterm-256color
ENV TERM=${TERM}
ENTRYPOINT ["codex", "--config=check_for_update_on_startup=false", \
  "--config=shell_environment_policy.set.PATH=\"/lib/agent-wrappers:/usr/local/bin:/usr/bin:/bin\""]
