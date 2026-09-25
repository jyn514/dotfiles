"""Shared identity rules for Lima-provided guest mounts."""

import hashlib


def lima_tag(share):
    value = f'{share["location"]}:{share["mountPoint"]}'.encode()
    return "lima-" + hashlib.sha256(value).digest()[:8].hex()


def source(share, index, mount_type):
    return lima_tag(share) if mount_type == "9p" else f"mount{index}"
