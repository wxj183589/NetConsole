from __future__ import annotations

import re
from dataclasses import dataclass


RELEASE_HEADER = re.compile(r"^##\s+(v\d+\.\d+\.\d+)\b(?P<tail>.*)$")
DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
RUNTIME_HEADER = re.compile(
    r"^(?:##\s+)?(v\d+\.\d+\.\d+)(?:\s+-\s+(\d{4}-\d{2}-\d{2}))?\s*$"
)


@dataclass(frozen=True)
class ChangelogSection:
    version: str
    date: str | None
    body: str


class ChangelogSyncError(ValueError):
    """Raised when a changelog cannot produce a safe runtime asset."""


def parse_released_sections(
    text: str, *, source_name: str = "changelog"
) -> tuple[ChangelogSection, ...]:
    lines = text.splitlines()
    headers = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := RELEASE_HEADER.match(line)) is not None
    ]
    sections: list[ChangelogSection] = []
    seen: set[str] = set()
    for position, (start, match) in enumerate(headers):
        version = match.group(1)
        if version in seen:
            raise ChangelogSyncError(
                f"{source_name} contains duplicate released version: {version}"
            )
        seen.add(version)
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        date_match = DATE_PATTERN.search(match.group("tail"))
        sections.append(
            ChangelogSection(
                version=version,
                date=date_match.group(1) if date_match else None,
                body=_normalize_body("\n".join(lines[start + 1 : end])),
            )
        )
    if not sections:
        raise ChangelogSyncError(f"{source_name} contains no released changelog sections")
    _validate_version_order(sections, source_name=source_name)
    return tuple(sections)


def parse_runtime_sections(text: str) -> tuple[ChangelogSection, ...]:
    lines = text.splitlines()
    headers = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := RUNTIME_HEADER.match(line)) is not None
    ]
    sections: list[ChangelogSection] = []
    seen: set[str] = set()
    for position, (start, match) in enumerate(headers):
        version = match.group(1)
        if version in seen:
            raise ChangelogSyncError(f"runtime changelog contains duplicate version: {version}")
        seen.add(version)
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        sections.append(
            ChangelogSection(
                version=version,
                date=match.group(2),
                body=_normalize_body("\n".join(lines[start + 1 : end])),
            )
        )
    if not sections:
        raise ChangelogSyncError("runtime changelog contains no released sections")
    _validate_version_order(sections, source_name="runtime changelog")
    return tuple(sections)


def render_runtime_changelog(sections: tuple[ChangelogSection, ...]) -> str:
    chunks: list[str] = []
    for section in sections:
        title = section.version
        if section.date:
            title += f" - {section.date}"
        chunks.append(f"{title}\n{section.body}" if section.body else title)
    return "\n\n".join(chunks) + "\n"


def _normalize_body(value: str) -> str:
    return value.replace("\r\n", "\n").strip()


def _version_key(version: str) -> tuple[int, int, int]:
    parts = version.removeprefix("v").split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _validate_version_order(
    sections: list[ChangelogSection], *, source_name: str
) -> None:
    keys = [_version_key(section.version) for section in sections]
    if keys != sorted(keys, reverse=True):
        raise ChangelogSyncError(
            f"{source_name} released versions are not in descending order"
        )
