"""Shared identity rules for Lima-provided guest mounts."""

import hashlib


def lima_tag(share):
    value = f'{share["location"]}:{share["mountPoint"]}'.encode()
    return "lima-" + hashlib.sha256(value).digest()[:8].hex()


def source(share):
    """Return Lima's deterministic source name for a configured share."""
    return lima_tag(share)
