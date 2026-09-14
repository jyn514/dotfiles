"""Pinned Caddy image identity and immutable authenticated-egress JSON."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any

IMAGE = "caddy:2.11.4-alpine"
INDEX = "sha256:13ba145cba2f3e28fa801994876e4c086d1b95d5aa2a520a734765ffb6b12017"
PLATFORMS = {
    "linux/amd64": ("sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a", "sha256:af555904a0961945f16bb323a501457b13a4f7e9bde969b145b97da80b38ecbe"),
    "linux/arm64/v8": ("sha256:1172d4213087d3fc30bafc7ff2c2896180eb0c41ff7f75f315568fb36cabdcba", "sha256:6b08c1b9858ca9a7d99c1da13c3695081e0e604c6cf214ca26a7ce0e2c4fd9b4"),
}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")

class CaddyIdentityError(ValueError): pass

@dataclass(frozen=True)
class CaddyImageIdentity:
    provenance: str
    index_digest: str
    platform: str
    manifest_digest: str
    configuration_digest: str
    runtime_image_id: str
    @property
    def runtime_reference(self): return "caddy@" + self.manifest_digest
    def implementation_identity(self, mounted_configuration_digest: str) -> str:
        _digest(mounted_configuration_digest)
        material = {"image": asdict(self), "mounted_configuration_digest": mounted_configuration_digest}
        return "sha256:" + hashlib.sha256(_json(material)).hexdigest()

def _digest(value: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value): raise CaddyIdentityError("invalid Caddy digest")
    return value

def resolve_caddy_image(runtime: Any) -> CaddyImageIdentity:
    platform = runtime.build_platform()
    platform = "linux/arm64/v8" if platform == "linux/arm64" else platform
    try: manifest, configuration = PLATFORMS[platform]
    except KeyError as error: raise CaddyIdentityError(f"unsupported Caddy platform: {platform}") from error
    # Runtime implementations own pull and native inspection. The tag and index
    # are recorded provenance, never a pull/run reference.
    image = runtime.verify_external_image("caddy", manifest, configuration, platform.removesuffix("/v8"))
    if image.content != manifest or image.config != configuration:
        raise CaddyIdentityError("inspected Caddy manifest/configuration chain differs from installed policy")
    runtime_id = runtime.inspect_runtime_image_id(image.reference)
    if runtime_id != configuration: raise CaddyIdentityError("Caddy runtime image ID differs from configuration digest")
    return CaddyImageIdentity(IMAGE, INDEX, platform, manifest, configuration, runtime_id)

def _json(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
def configuration_digest(configuration: bytes) -> str:
    if not isinstance(configuration, bytes): raise TypeError("Caddy configuration must be bytes")
    return "sha256:" + hashlib.sha256(configuration).hexdigest()

def _static(status: int) -> dict[str, Any]:
    return {"handler": "static_response", "status_code": status, "headers": {"Content-Length": ["0"]}}

def _nonempty_headers(names: list[str]) -> dict[str, Any]:
    # This is the stock matcher emitted by `caddy adapt` for forward_auth
    # copy_headers, combined so every required response header must be nonempty.
    return {"not": [{"vars": {f"{{http.reverse_proxy.header.{name}}}": [""]}} for name in names]}

def _gate(profile: str, helper_socket: str, operation: str) -> dict[str, Any]:
    names = ["Authorization"] + (["Chatgpt-Account-Id"] if profile == "codex" else [])
    mutations = []
    for name in names:
        mutations.append({"handler": "headers", "request": {"delete": [name]}})
        mutations.append({"handler": "headers", "request": {"set": {name: [f"{{http.reverse_proxy.header.{name}}}"]}}})
    success = {"group": "admission", "match": [_nonempty_headers(names)], "handle": mutations}
    malformed = {"group": "admission", "handle": [_static(503)]}
    return {
        "handler": "reverse_proxy", "rewrite": {"method": "GET", "uri": operation},
        "headers": {"request": {"set": {"Content-Length": ["0"], "Host": ["profile-helper"],
            "X-Original-Method": ["{http.request.method}"], "X-Original-Uri": ["{http.request.uri}"]},
            "delete": ["Transfer-Encoding", "Forwarded", "Via", "X-Forwarded-For",
                       "X-Forwarded-Host", "X-Forwarded-Proto", "Proxy-Authorization",
                       "Chatgpt-Account-Id", "X-Codex-*", "X-Zulip-*"]}},
        "upstreams": [{"dial": "unix/" + helper_socket}],
        "transport": {"protocol": "http", "dial_timeout": 10_000_000_000, "response_header_timeout": 30_000_000_000},
        "handle_response": [
            {"match": {"status_code": [2]}, "routes": [success, malformed]},
            {"match": {"status_code": [401]}, "routes": [{"handle": [_static(401)]}]},
            {"routes": [{"handle": [_static(503)]}]},
        ],
    }

def _application_proxy(profile: str, upstream: str) -> dict[str, Any]:
    delete = ["Forwarded", "Via", "X-Forwarded-For", "X-Forwarded-Host",
              "X-Forwarded-Proto", "Proxy-Authorization", "X-Codex-*", "X-Zulip-*", "Originator"]
    # Auth fields were installed on the original request by the gate. Preserve
    # those exact values while suppressing Caddy's automatic forwarding fields.
    set_headers = {"Host": [upstream]}
    return {"handler": "reverse_proxy", "upstreams": [{"dial": upstream + ":443"}],
            "headers": {"request": {"delete": delete, "set": set_headers}},
            "transport": {"protocol": "http", "tls": {}, "dial_timeout": 10_000_000_000,
                          "response_header_timeout": 60_000_000_000}}

def generate_caddy_config(profile: str, upstream: str, helper_socket: str = "/run/profile-helper/socket") -> bytes:
    if profile not in {"codex", "zulip"} or not upstream or any(c in upstream for c in "/\r\n"):
        raise ValueError("invalid Caddy profile or upstream")
    proxy = _application_proxy(profile, upstream)
    if profile == "codex":
        matcher = {"expression": "method('POST') && path('/codex/responses') && {http.request.uri.query} == ''"}
        handlers = [{"handler": "request_body", "max_size": 32 * 1024 * 1024}, _gate(profile, helper_socket, "/admit"),
                    {"handler": "rewrite", "uri": "/backend-api/codex/responses"}, proxy]
    else:
        matcher = {"expression": "method('GET') && (path('/api/v1/messages') || path_regexp('^/api/v1/users/me/[0-9]+/topics$'))"}
        handlers = [_gate(profile, helper_socket, "/admit"), proxy]
    ready_match = {"expression": "method('GET') && path('/ready') && {http.request.uri.query} == ''"}
    routes = [{"match": [ready_match], "handle": [_gate(profile, helper_socket, "/ready"), _static(204)]},
              {"match": [matcher], "handle": handlers}, {"handle": [_static(404)]}]
    config = {"logging": {"logs": {"default": {"level": "INFO", "writer": {"output": "stderr"}}}},
              "apps": {"http": {"servers": {"egress": {"listen": [":8787"],
                  "max_header_bytes": 65536, "read_header_timeout": 10_000_000_000,
                  "idle_timeout": 300_000_000_000, "routes": routes,
                  "errors": {"routes": [{"handle": [_static(503)]}]}}}}}}
    return _json(config) + b"\n"
