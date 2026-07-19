ARG BASE_IMAGE=node:slim
FROM ${BASE_IMAGE}

COPY ./lib/agent-sandbox/install-deps.sh .
RUN ./install-deps.sh && rm ./install-deps.sh

COPY ./lib/agent-sandbox/install-user-deps.sh .
RUN ./install-user-deps.sh && rm ./install-user-deps.sh

COPY ./lib/agent-sandbox/create-user.sh .
ARG AGENT_UID=1000
ARG AGENT_GID=1000
RUN ./create-user.sh "${AGENT_UID}" "${AGENT_GID}" codex /home/codex \
    && rm ./create-user.sh

ARG CODEX_VERSION=0.144.4
RUN npm install --global "@openai/codex@${CODEX_VERSION}"

ENV HOME=/home/codex
ARG CODEX_HOME
ENV CODEX_HOME=${CODEX_HOME}
ENV CODEX_SQLITE_HOME=/codex-sqlite
RUN mkdir -p ${CODEX_HOME} ${CODEX_SQLITE_HOME} /work \
    && chown -R ${AGENT_UID}:${AGENT_GID} \
        ${HOME} ${CODEX_HOME} ${CODEX_SQLITE_HOME} /work
USER ${AGENT_UID}:${AGENT_GID}
WORKDIR /work

COPY --chown=${AGENT_UID}:${AGENT_GID} ./lib/agent-wrappers /lib/agent-wrappers
ENV PATH=/lib/agent-wrappers:${PATH}

# fallback for `metaedit` when not going through the wrapper
COPY --chown=${AGENT_UID}:${AGENT_GID} <<EOF ${HOME}/.config/jj/config.toml
[user]
name = "jyn"
email = "github@jyn.dev"
EOF

ENV COLORTERM=truecolor
ARG TERM=xterm-256color
ENV TERM=${TERM}
ENTRYPOINT ["codex", "--config=check_for_update_on_startup=false", \
  "--config=shell_environment_policy.set.PATH=\"/lib/agent-wrappers:/usr/local/bin:/usr/bin:/bin\""]
