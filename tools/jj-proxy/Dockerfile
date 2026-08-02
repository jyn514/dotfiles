FROM lukemathwalker/cargo-chef:latest-rust-1.88.0-alpine3.22 AS chef
RUN apk add --no-cache musl-dev
WORKDIR /build

FROM chef AS planner
COPY tools/jj-proxy/Cargo.toml ./
COPY tools/jj-proxy/Cargo.lock ./
COPY tools/jj-proxy/src ./src
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS build
COPY --from=planner /build/recipe.json recipe.json
RUN cargo chef cook --release --all-targets --locked --recipe-path recipe.json
COPY tools/jj-proxy/Cargo.toml ./
COPY tools/jj-proxy/Cargo.lock ./
COPY tools/jj-proxy/src ./src
RUN cargo test --release --locked && cargo build --release --locked

FROM alpine:3.22 AS jj
ARG JJ_VERSION=0.42.0
ARG TARGETARCH
RUN apk add --no-cache ca-certificates curl tar \
    && case "$TARGETARCH" in amd64) arch=x86_64 ;; arm64) arch=aarch64 ;; *) exit 1 ;; esac \
    && curl -fsSL "https://github.com/jj-vcs/jj/releases/download/v${JJ_VERSION}/jj-v${JJ_VERSION}-${arch}-unknown-linux-musl.tar.gz" \
       | tar -xz -C /usr/local/bin
RUN mkdir -p /image-root/src/work/.agents/sandbox /image-root/run/sandbox-proxy

FROM scratch
ENV PATH=/trusted/bin
ENV RUST_BACKTRACE=1
COPY --from=build /build/target/release/jj-proxy /trusted/bin/jj-proxy
COPY --from=build /build/target/release/jj-proxy /trusted/bin/sandbox-proxy-forward
COPY --from=jj /usr/local/bin/jj /trusted/bin/jj
COPY --from=jj /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=jj /image-root/ /
COPY config/gitignore /trusted/gitignore
COPY tools/jj-proxy/jj.toml /trusted/jj.toml
USER 65532:65532
ENTRYPOINT ["/trusted/bin/jj-proxy", "serve"]