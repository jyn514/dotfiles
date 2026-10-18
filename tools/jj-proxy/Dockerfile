FROM lukemathwalker/cargo-chef:0.1.78-rust-1.98.1-alpine3.24 AS chef
RUN apk add --no-cache musl-dev
WORKDIR /build

FROM chef AS planner
COPY tools/jj-proxy/Cargo.toml ./
COPY tools/jj-proxy/Cargo.lock ./
COPY tools/jj-proxy/src ./src
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS build
COPY --from=planner /build/recipe.json recipe.json
RUN --mount=type=cache,target=/build/target \
    cargo chef cook --release --all-targets --locked --recipe-path recipe.json
COPY tools/jj-proxy/Cargo.toml ./
COPY tools/jj-proxy/Cargo.lock ./
COPY tools/jj-proxy/src ./src
COPY tools/jj-proxy/tests/fixtures ./tests/fixtures
RUN --mount=type=cache,target=/build/target \
    cargo build --release --locked \
    && cp target/release/jj-proxy /jj-proxy

# Release acquisition has no dependency on Rust or local proxy sources.
FROM alpine:3.22 AS jj
RUN apk add --no-cache curl ca-certificates
ARG TARGETARCH
ARG JJ_AMD64_URL
ARG JJ_AMD64_SHA256
ARG JJ_ARM64_URL
ARG JJ_ARM64_SHA256
RUN case "${TARGETARCH}" in \
        amd64) url="${JJ_AMD64_URL}"; checksum="${JJ_AMD64_SHA256}" ;; \
        arm64) url="${JJ_ARM64_URL}"; checksum="${JJ_ARM64_SHA256}" ;; \
        *) echo "Unsupported JJ architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && test -n "$url" && test -n "$checksum" \
    && curl --fail --location --show-error --output /jj.tar.gz "$url" \
    && printf '%s  /jj.tar.gz\n' "$checksum" | sha256sum -c - \
    && mkdir /jj \
    && tar -xzf /jj.tar.gz -C /jj \
    && cp /jj/jj /jj-bin \
    && /jj-bin --version \
    && rm -rf /jj /jj.tar.gz
RUN mkdir -p /image-root/src/work/.agents/sandbox /image-root/run/sandbox-proxy /image-root/etc/ssl \
    && ln -s certs/ca-certificates.crt /image-root/etc/ssl/cert.pem

FROM build AS verified
# The pinned JJ binary uses external Git during secure-config test setup.
RUN apk add --no-cache git
COPY --from=jj /jj-bin /jj-bin
COPY tools/jj-proxy/jj.toml ./
COPY tools/jj-proxy/policy.toml ./policy.toml
RUN --mount=type=cache,target=/build/target \
    JJ_PROXY_TEST_JJ=/jj-bin cargo test --release --locked

FROM alpine:3.22 AS editor
# Git also searches PATH for transport helpers; keep them under the existing
# trusted executable directory rather than widening Landlock execution access.
RUN apk add --no-cache git \
    && mkdir -p /trusted/bin \
    && cp /bin/busybox /trusted/bin/busybox \
    && cp /bin/busybox /trusted/bin/sh \
    && ln -s busybox /trusted/bin/cp \
    && ln -s busybox /trusted/bin/rm \
    && cp /usr/bin/git /trusted/bin/git \
    && cp /usr/libexec/git-core/git-remote-http /trusted/bin/git-remote-http \
    && ln -s git-remote-http /trusted/bin/git-remote-https

FROM scratch AS proxy-runtime
ENV PATH=/trusted/bin
ENV RUST_BACKTRACE=1
COPY --from=editor /trusted/bin /trusted/bin
COPY --from=editor /lib /lib
COPY --from=editor /usr/lib /usr/lib
COPY --from=verified /jj-proxy /trusted/bin/jj-proxy
COPY --from=verified /jj-proxy /trusted/bin/sandbox-proxy-forward
COPY --from=jj /jj-bin /trusted/bin/jj
COPY --from=jj /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=jj /image-root/ /
COPY config/gitignore /trusted/gitignore
COPY tools/jj-proxy/jj.toml /trusted/jj.toml
COPY tools/jj-proxy/policy.toml /trusted/policy.toml
COPY --chmod=0555 tools/jj-proxy/agent-split-editor /trusted/bin/agent-split-editor
USER 65532:65532
ENTRYPOINT ["/trusted/bin/jj-proxy", "serve"]
