FROM lukemathwalker/cargo-chef:latest-rust-1.89.0-alpine3.22 AS chef
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
RUN --mount=type=cache,target=/build/target \
    cargo test --release --locked \
    && cargo build --release --locked \
    && cp target/release/jj-proxy /jj-proxy

FROM chef AS jj
ARG JJ_REVISION=a0e7ebe7b037e822c506fcf6308055f8eecfb48a
RUN apk add --no-cache git musl-dev openssl-dev openssl-libs-static perl make
RUN git init /jj \
    && git -C /jj fetch --depth=1 https://github.com/jj-vcs/jj.git "${JJ_REVISION}" \
    && git -C /jj checkout --detach FETCH_HEAD
WORKDIR /jj
RUN --mount=type=cache,target=/jj/target \
    cargo build --release --locked --bin jj \
    && cp target/release/jj /jj-bin
RUN mkdir -p /image-root/src/work/.agents/sandbox /image-root/run/sandbox-proxy

FROM alpine:3.22 AS editor
RUN apk add --no-cache git \
    && mkdir -p /trusted/bin \
    && cp /bin/busybox /trusted/bin/busybox \
    && ln -s busybox /trusted/bin/sh \
    && ln -s busybox /trusted/bin/cp \
    && ln -s busybox /trusted/bin/rm \
    && cp /usr/bin/git /trusted/bin/git

FROM scratch
ENV PATH=/trusted/bin
ENV RUST_BACKTRACE=1
COPY --from=editor /trusted/bin /trusted/bin
COPY --from=editor /lib /lib
COPY --from=editor /usr/lib /usr/lib
COPY --from=build /jj-proxy /trusted/bin/jj-proxy
COPY --from=build /jj-proxy /trusted/bin/sandbox-proxy-forward
COPY --from=jj /jj-bin /trusted/bin/jj
COPY --from=jj /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=jj /image-root/ /
COPY config/gitignore /trusted/gitignore
COPY tools/jj-proxy/jj.toml /trusted/jj.toml
COPY --chmod=0555 tools/jj-proxy/agent-split-editor /trusted/bin/agent-split-editor
USER 65532:65532
ENTRYPOINT ["/trusted/bin/jj-proxy", "serve"]
