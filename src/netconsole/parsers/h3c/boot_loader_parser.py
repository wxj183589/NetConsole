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
    slots = parse_boot_loader_slot_sections(output)
    if slots:
        first_slot = next(iter(slots.values()))
        return {key: value for key, value in first_slot.items() if value}
    return _parse_sections(output)


def parse_boot_loader_slot_sections(output: str) -> dict[str, dict[str, list[str]]]:
    slots: dict[str, dict[str, list[str]]] = {}
    current_slot: str | None = None
    current_lines: list[str] = []
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        slot_match = re.match(r"(?i)^Software images on slot\s+(\d+):", line)
        if slot_match:
            if current_slot is not None:
                slots[f"slot{current_slot}"] = _parse_sections("\n".join(current_lines))
            current_slot = slot_match.group(1)
            current_lines = []
            continue
        if current_slot is not None:
            current_lines.append(raw_line)
    if current_slot is not None:
        slots[f"slot{current_slot}"] = _parse_sections("\n".join(current_lines))
    return {slot: sections for slot, sections in slots.items() if any(sections.values())}


def parse_boot_loader(output: str, language: str = "zh_CN") -> str | None:
    slots = parse_boot_loader_slot_sections(output)
    if slots:
        blocks: list[str] = []
        for slot, sections in slots.items():
            formatted = format_boot_loader_sections(sections, language)
            if formatted:
                blocks.append(f"{slot}\n{formatted}")
        return "\n\n".join(blocks) if blocks else None
    return format_boot_loader_sections(_parse_sections(output), language)


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


def _parse_sections(output: str) -> dict[str, list[str]]:
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


def _section_for_header(line: str) -> str | None:
    normalized = line.strip().lower()
    for key, header in SECTION_HEADERS.items():
        if normalized == header.lower():
            return key
    return None
