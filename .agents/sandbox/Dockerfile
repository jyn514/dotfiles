FROM oven/bun:1.3.14 AS bun

FROM node:24-alpine3.22

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

RUN apk add --no-cache \
      cargo python3 py3-pip \
       bash \
       coreutils \
       diffutils \
       fish \
       perl \
       tmux \
       zsh
RUN python3 -m venv /opt/test-venv \
    && /opt/test-venv/bin/pip install --no-cache-dir \
       pytest==9.1.1 \
       pytest-xdist==3.8.0 \
       pytest-sugar==1.1.1 \
       pytest-instafail==0.5.0

ENV PATH="/opt/test-venv/bin:$PATH"
