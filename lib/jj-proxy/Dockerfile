FROM lukemathwalker/cargo-chef:latest-rust-1.88.0-alpine3.22 AS chef
RUN apk add --no-cache musl-dev
WORKDIR /build

FROM chef AS planner
COPY lib/jj-proxy/Cargo.toml ./
COPY lib/jj-proxy/Cargo.lock ./
COPY lib/jj-proxy/src ./src
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS build
COPY --from=planner /build/recipe.json recipe.json
RUN cargo chef cook --release --all-targets --locked --recipe-path recipe.json
COPY lib/jj-proxy/Cargo.toml ./
COPY lib/jj-proxy/Cargo.lock ./
COPY lib/jj-proxy/src ./src
RUN cargo test --release --locked && cargo build --release --locked

FROM alpine:3.22 AS jj
ARG JJ_VERSION=0.42.0
ARG TARGETARCH
RUN apk add --no-cache ca-certificates curl tar \
    && case "$TARGETARCH" in amd64) arch=x86_64 ;; arm64) arch=aarch64 ;; *) exit 1 ;; esac \
    && curl -fsSL "https://github.com/jj-vcs/jj/releases/download/v${JJ_VERSION}/jj-v${JJ_VERSION}-${arch}-unknown-linux-musl.tar.gz" \
       | tar -xz -C /usr/local/bin

FROM scratch
ENV RUST_BACKTRACE=1
COPY --from=build /build/target/release/jj-proxy /trusted/bin/jj-proxy
COPY --from=jj /usr/local/bin/jj /trusted/bin/jj
COPY --from=jj /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY config/gitignore /trusted/gitignore
COPY lib/jj-proxy/jj.toml /trusted/jj.toml
USER 65532:65532
ENTRYPOINT ["/trusted/bin/jj-proxy", "serve"]
