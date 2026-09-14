FROM python:3.13.7-alpine3.22

RUN apk add --no-cache socat \
    && mkdir -p /trusted/bin /run/profile-helper \
    && chown 65532:65532 /run/profile-helper
COPY --chmod=0555 tools/codex-sandbox/auth-proxy/profile_helper.py /trusted/bin/profile-helper
COPY --chmod=0444 tools/codex-sandbox/auth-proxy/broker.py /trusted/bin/broker.py
COPY --chmod=0444 tools/codex-sandbox/auth-proxy/codex_profile.py /trusted/bin/codex_profile.py
COPY --chmod=0555 tools/codex-sandbox/gateway.py /trusted/bin/sandbox-gateway

USER 65532:65532
ENTRYPOINT ["/trusted/bin/profile-helper"]
