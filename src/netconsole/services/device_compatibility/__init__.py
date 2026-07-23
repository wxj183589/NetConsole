"""Device compatibility baseline registry and development-time scan helpers."""

from .service import (
    CompatibilityCandidate,
    CompatibilityResolver,
    DeviceCompatibilityProfile,
    DeviceFingerprint,
    DeviceCompatibilityService,
    load_device_compatibility_profiles,
)

__all__ = [
    "CompatibilityCandidate",
    "CompatibilityResolver",
    "DeviceCompatibilityProfile",
    "DeviceCompatibilityService",
    "DeviceFingerprint",
    "load_device_compatibility_profiles",
]
