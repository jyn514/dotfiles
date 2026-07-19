ARG BASE_IMAGE=node:slim
FROM ${BASE_IMAGE}

COPY ./install-deps.sh .
RUN ./install-deps.sh && rm ./install-deps.sh

COPY ./install-user-deps.sh .
RUN ./install-user-deps.sh && rm ./install-user-deps.sh

COPY ./create-user.sh .
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

ENV COLORTERM=truecolor
ARG TERM=xterm-256color
ENV TERM=${TERM}
ENTRYPOINT ["codex", "--config=check_for_update_on_startup=false"]
