FROM python:3.13.7-alpine3.22

RUN apk add --no-cache socat \
    && mkdir -p /trusted/bin
COPY --chmod=0555 tools/codex-sandbox/auth-proxy/server.py /trusted/bin/codex-auth-proxy
COPY --chmod=0555 tools/codex-sandbox/gateway.py /trusted/bin/sandbox-gateway

USER 65532:65532
ENTRYPOINT ["/trusted/bin/codex-auth-proxy"]
