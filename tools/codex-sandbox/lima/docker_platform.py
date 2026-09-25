"""Platform-specific policy for the isolated Lima-Docker host."""

from dataclasses import dataclass
import os
import platform
from pathlib import Path
import stat


@dataclass(frozen=True)
class PlatformConfig:
    vm_type: str
    guest_arch: str
    mount_type: str
    image: str
    image_digest: str
    default_client: str | None


def kvm_available(path=Path("/dev/kvm")):
    try:
        metadata = path.stat()
    except OSError:
        return False
    return stat.S_ISCHR(metadata.st_mode) and os.access(path, os.R_OK | os.W_OK)


def current() -> PlatformConfig:
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin":
        if machine != "arm64":
            raise ValueError("Lima-Docker requires Apple Silicon macOS")
        return PlatformConfig(
            "vz", "aarch64", "virtiofs",
            "https://cloud-images-archive.ubuntu.com/releases/noble/release-20250704/ubuntu-24.04-server-cloudimg-arm64.img",
            "sha256:bbecbb88100ee65497927ed0da247ba15af576a8855004182cf3c87265e25d35",
            "/opt/homebrew/bin/docker",
        )
    if system == "Linux":
        if machine != "x86_64":
            raise ValueError("Linux Lima-Docker currently requires x86_64")
        if not kvm_available():
            raise ValueError("Linux Lima-Docker requires readable and writable /dev/kvm")
        return PlatformConfig(
            "qemu", "x86_64", "virtiofs",
            "https://cloud-images.ubuntu.com/releases/noble/release-20260911/ubuntu-24.04-server-cloudimg-amd64.img",
            "sha256:612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354",
            None,
        )
    raise ValueError(f"Lima-Docker does not support host platform {system}/{machine}")
