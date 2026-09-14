"""Zulip typed broker lifecycle identity and schema-3 proxy record rules."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from typing import Any
from trusted_services import ServiceFamily, ServicePlan, ServiceScope

STATE_SCHEMA = 1
NETWORK_SUFFIX = "zulip-public-only"
CREDENTIAL_DOMAIN = "zulip"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def adapter_bytes(root: Path, core: Path) -> bytes:
    paths = [p for p in root.rglob('*') if p.is_file() and 'tests' not in p.parts and '__pycache__' not in p.parts]
    paths.append(core)
    return b'\0'.join(p.name.encode()+b'\0'+p.read_bytes() for p in sorted(paths))


def resolved_plan(root: Path, core: Path, image: str, uid: int, gid: int, network: str):
    implementation = adapter_bytes(root, core)
    if '@sha256:' not in image:
        if not _DIGEST.fullmatch(image): raise ValueError('Zulip broker image is not immutable')
        image = 'zulip-broker@' + image
    plan = ServicePlan(role='zulip-broker', family=ServiceFamily.AUTHENTICATED_EGRESS,
        scope=ServiceScope.SHARED_SESSION, adapter='zulip-typed-broker',
        adapter_identity='sha256:'+hashlib.sha256(implementation).hexdigest(),
        state_schema=STATE_SCHEMA, image_role='broker', image_uid=uid, image_gid=gid,
        fixed_parameters={'credential-domain': CREDENTIAL_DOMAIN, 'network': network,
                          'protocol': 'typed-read-only-v1'})
    return plan.resolve(adapter_bytes=implementation, image=image)
