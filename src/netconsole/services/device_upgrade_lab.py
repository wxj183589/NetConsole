"""Firmware transition model for an isolated, in-memory device."""

from dataclasses import dataclass
from hashlib import sha256


@dataclass
class SimulatedDevice:
    device_uuid: str
    version: str
    fail_boot: bool = False
    staged_version: str = ""


@dataclass(frozen=True)
class UpgradeResult:
    device_uuid: str
    previous_version: str
    current_version: str
    status: str


def simulate_upgrade(
    device: SimulatedDevice, *, target_version: str, image: bytes, expected_sha256: str,
) -> UpgradeResult:
    if not device.device_uuid or not target_version or not image:
        raise ValueError("device identity, target version and image are required")
    if sha256(image).hexdigest() != expected_sha256:
        raise ValueError("image digest mismatch")
    previous = device.version
    if previous == target_version:
        return UpgradeResult(device.device_uuid, previous, previous, "already_current")
    device.staged_version = target_version
    device.version = "" if device.fail_boot else device.staged_version
    if device.version != target_version:
        device.version = previous
        status = "rolled_back"
    else:
        status = "verified"
    device.staged_version = ""
    return UpgradeResult(device.device_uuid, previous, device.version, status)
