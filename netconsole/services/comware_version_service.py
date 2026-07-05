from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ComwareVersionInfo:
    vendor: str = ""
    os_family: str = ""
    os_major: str = ""
    software_version: str = ""
    release: str = ""
    release_number: str = ""
    release_patch: str = ""
    release_series: str = ""


def parse_comware_version(text: str) -> ComwareVersionInfo:
    if not text or "comware" not in text.lower():
        return ComwareVersionInfo()
    version_match = re.search(r"Version\s+([0-9]+(?:\.[0-9A-Za-z]+)+)", text, re.IGNORECASE)
    release_match = re.search(r"Release\s+([A-Za-z]?\d{2,4}(?:xx)?(?:[A-Za-z]\d+)?)", text, re.IGNORECASE)
    software_version = version_match.group(1) if version_match else ""
    release = release_match.group(1).upper() if release_match else ""
    number_match = re.search(r"(\d{2,4})", release)
    patch_match = re.search(r"([A-Z]\d+)$", release)
    release_number = number_match.group(1) if number_match else ""
    release_patch = patch_match.group(1) if patch_match else ""
    return ComwareVersionInfo(
        vendor="H3C" if "h3c" in text.lower() else "",
        os_family="Comware",
        os_major=_major_from_version(software_version),
        software_version=software_version,
        release=release,
        release_number=release_number,
        release_patch=release_patch,
        release_series=_release_series(release),
    )


def _major_from_version(version: str) -> str:
    if not version:
        return ""
    major = version.split(".", 1)[0]
    return f"V{major}" if major.isdigit() else ""


def _release_series(release: str) -> str:
    release = release.upper()
    match = re.search(r"([A-Z]?)(\d{2})\d{0,2}", release)
    if not match:
        return ""
    prefix, first_two = match.groups()
    return f"{prefix}{first_two}xx" if prefix else f"R{first_two}xx"
