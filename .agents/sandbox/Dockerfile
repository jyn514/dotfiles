FROM oven/bun:1.3.14-alpine AS bun

FROM node:24-alpine3.22

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

RUN apk add --no-cache \
      cargo rustfmt python3 py3-pip \
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

# Repositories mount beneath /src, so Bun resolves these shared Pi test
# dependencies from /src/node_modules without modifying each checkout.
RUN npm install --prefix /src --ignore-scripts --no-save \
       @earendil-works/pi-coding-agent@0.84.4 \
       @earendil-works/pi-ai@0.84.4 \
       typebox@1.3.7

ENV PATH="/opt/test-venv/bin:$PATH"
