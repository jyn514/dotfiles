ARG BASE_IMAGE=node:slim
FROM codex-jj-proxy:local AS jj_proxy

FROM ${BASE_IMAGE}

ARG CODEX_VERSION=0.144.4
RUN npm install --global "@openai/codex@${CODEX_VERSION}"

COPY ./lib/agent-sandbox/install-user-deps.sh .
RUN ./install-user-deps.sh && rm ./install-user-deps.sh

COPY ./lib/agent-sandbox/install-deps.sh .
RUN ./install-deps.sh && rm ./install-deps.sh

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

ENV HOME=/home/codex
ARG CODEX_HOME
ENV CODEX_HOME=${CODEX_HOME}
ENV CODEX_SQLITE_HOME=/codex-sqlite
RUN mkdir -p ${CODEX_HOME} ${CODEX_SQLITE_HOME} /src/work \
    && chown -R ${AGENT_UID}:${AGENT_GID} \
        ${HOME} ${CODEX_HOME} ${CODEX_SQLITE_HOME} /src
USER ${AGENT_UID}:${AGENT_GID}
WORKDIR /src/work

# Keep generated editor, language-server, and tool state out of jj snapshots.
COPY --chown=${AGENT_UID}:${AGENT_GID} ./config/gitignore ${HOME}/.config/git/ignore

COPY --chown=${AGENT_UID}:${AGENT_GID} ./lib/agent-wrappers /lib/agent-wrappers
COPY --from=jj_proxy /trusted/bin/jj-proxy /usr/local/bin/jj-proxy
ENV PATH=/lib/agent-wrappers:${PATH}

ENV COLORTERM=truecolor
ARG TERM=xterm-256color
ENV TERM=${TERM}
ENTRYPOINT ["codex", "--config=check_for_update_on_startup=false", \
  "--config=shell_environment_policy.set.PATH=\"/lib/agent-wrappers:/usr/local/bin:/usr/bin:/bin\""]
