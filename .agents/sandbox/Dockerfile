FROM oven/bun:1.3.14-alpine AS bun

FROM node:24-alpine3.22 AS sandbox

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
COPY --from=ghcr.io/jdx/mise:2026.10.14 /usr/local/bin/mise /usr/local/bin/mise

RUN apk add --no-cache \
      cargo rustfmt python3 py3-pip \
       bash \
       coreutils \
       diffutils \
       fish \
       perl \
       openjdk21-jdk \
       sqlite \
       tmux \
       xdg-utils \
       zsh
RUN python3 -m venv /opt/test-venv \
    && /opt/test-venv/bin/pip install --no-cache-dir \
       pytest==9.1.1 \
       pytest-xdist==3.8.0 \
       pytest-sugar==1.1.1 \
       docker==7.2.0

# Repositories mount beneath /src, so Bun resolves these shared Pi test
# dependencies from /src/node_modules without modifying each checkout.
RUN npm install --prefix /src --ignore-scripts --no-save \
       @earendil-works/pi-coding-agent@0.84.4 \
       @earendil-works/pi-ai@0.84.4 \
       typebox@1.3.7

# Keep the offline CLI off PATH so normal agent commands still use the broker wrapper.
ARG CODEX_VERSION=0.162.1
RUN npm install --prefix /opt/test-tools --ignore-scripts --no-save --no-audit --no-fund \
       "@openai/codex@${CODEX_VERSION}"

# The enclosing sandbox runtime installs its current Pi build at this path.
# Native integration tests need that build, not the older unit-test packages above.
ENV PATH="/opt/test-venv/bin:$PATH" \
    DOTFILES_TEST_JAVA_REAL=/usr/lib/jvm/java-21-openjdk/bin/java \
    DOTFILES_TEST_CODEX_REAL=/opt/test-tools/node_modules/.bin/codex \
    PI_PACKAGE_DIR=/opt/agent-pi/src/packages/coding-agent

RUN /opt/test-venv/bin/python -c 'from docker.utils.build import Pattern' \
    && mise --version \
    && sqlite3 --version \
    && xdg-mime --version \
    && "$DOTFILES_TEST_JAVA_REAL" -version \
    && "$DOTFILES_TEST_CODEX_REAL" --version
