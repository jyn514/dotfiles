ARG BASE_IMAGE=node:slim
FROM ${BASE_IMAGE}

COPY ./install-deps.sh .
RUN ./install-deps.sh && rm ./install-deps.sh

ARG CODEX_VERSION=0.144.4
RUN npm install --global "@openai/codex@${CODEX_VERSION}"

ARG CODEX_HOME
RUN mkdir -p ${CODEX_HOME} /work && chown -R 1000:1000 ${CODEX_HOME} /work
USER 1000:1000
ENV CODEX_HOME=${CODEX_HOME}
WORKDIR /work

ENV CODEX_SQLITE_HOME /tmp/codex-sqlite
RUN mkdir -p $CODEX_SQLITE_HOME

ENV COLORTERM=truecolor
ARG TERM=xterm-256color
ENTRYPOINT ["codex", "--config=check_for_update_on_startup=false"]
