FROM python:3.13.7-alpine3.22

RUN apk add --no-cache ca-certificates \
    && mkdir -p /run/sandbox-proxy /run/secrets /trusted/bin \
    && chown -R 65532:65532 /run/sandbox-proxy

COPY tools/zulip-proxy/server.py /trusted/bin/zulip-proxy
COPY tools/zulip-proxy/forward.py /trusted/bin/sandbox-proxy-forward

ENV PATH="/trusted/bin:${PATH}"

USER 65532:65532
ENTRYPOINT ["/trusted/bin/zulip-proxy"]
