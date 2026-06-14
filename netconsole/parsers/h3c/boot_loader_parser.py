from __future__ import annotations

import re


SECTION_HEADERS = {
    "current": "Current software images:",
    "main": "Main startup software images:",
    "backup": "Backup startup software images:",
}

SECTION_LABELS = {
    "zh_CN": {"current": "当前", "main": "主用", "backup": "备用"},
    "en_US": {"current": "Current", "main": "Main", "backup": "Backup"},
}


def parse_boot_loader_sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"current": [], "main": [], "backup": []}
    current_section: str | None = None
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        matched_section = _section_for_header(line)
        if matched_section:
            current_section = matched_section
            continue
        if current_section is None or not line.lower().startswith("flash:/"):
            continue
        parts = re.split(r"\s{2,}", line, maxsplit=1)
        sections[current_section].append(" ".join(part.strip() for part in parts if part.strip()))
    return {key: value for key, value in sections.items() if value}


def parse_boot_loader(output: str, language: str = "zh_CN") -> str | None:
    sections = parse_boot_loader_sections(output)
    return format_boot_loader_sections(sections, language)


def format_boot_loader_sections(sections: dict[str, list[str]], language: str = "zh_CN") -> str | None:
    labels = SECTION_LABELS.get(language, SECTION_LABELS["zh_CN"])
    blocks: list[str] = []
    for key in ("current", "main", "backup"):
        images = sections.get(key) or []
        if not images:
            continue
        lines = [f"{labels[key]}:"]
        lines.extend(f"  {image}" for image in images)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else None


def _section_for_header(line: str) -> str | None:
    normalized = line.strip().lower()
    for key, header in SECTION_HEADERS.items():
        if normalized == header.lower():
            return key
    return None
