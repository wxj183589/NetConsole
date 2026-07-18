from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from netconsole.utils.text_encoding import clean_h3c_device_text


_CONFIG_BODY_START_PATTERN = re.compile(
    r"^(#|version\b|sysname\b|vlan\b|interface\b)", re.IGNORECASE
)
_PROMPT_PATTERN = re.compile(r"^\s*(<[^<>]+>|\[[^\[\]]+\])\s*$")
_CONFIG_COMMAND_ECHOES = {
    "display current-configuration",
    "display saved-configuration",
}


@dataclass(frozen=True)
class SideBySideDiffRow:
    left_line: int | None
    left_text: str
    status: str
    right_line: int | None
    right_text: str


@dataclass(frozen=True)
class ConfigDiffResult:
    added: list[str]
    removed: list[str]
    modified: list[dict[str, str]]
    raw_diff: str


def compare_config_text(running_config_text: str, saved_config_text: str) -> ConfigDiffResult:
    return compare_named_config_text(saved_config_text, running_config_text, "saved", "running")


def compare_named_config_text(
    from_config_text: str,
    to_config_text: str,
    from_name: str,
    to_name: str,
) -> ConfigDiffResult:
    from_lines = clean_config_for_diff(from_config_text).splitlines()
    to_lines = clean_config_for_diff(to_config_text).splitlines()
    diff_lines = list(
        difflib.unified_diff(from_lines, to_lines, fromfile=from_name, tofile=to_name, lineterm="")
    )
    added = [line[1:] for line in diff_lines if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff_lines if line.startswith("-") and not line.startswith("---")]
    rows, _added_count, _removed_count, _modified_count = build_side_by_side_rows(from_lines, to_lines)
    modified = [
        {"from": row.left_text, "to": row.right_text}
        for row in rows
        if row.status == "~"
    ]
    return ConfigDiffResult(added=added, removed=removed, modified=modified, raw_diff="\n".join(diff_lines))


def build_side_by_side_rows(
    left_lines: list[str],
    right_lines: list[str],
) -> tuple[list[SideBySideDiffRow], int, int, int]:
    rows: list[SideBySideDiffRow] = []
    added = 0
    removed = 0
    modified_blocks = 0
    matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines)
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        left_block = left_lines[left_start:left_end]
        right_block = right_lines[right_start:right_end]
        if tag == "equal":
            for offset, (left, right) in enumerate(zip(left_block, right_block)):
                rows.append(SideBySideDiffRow(left_start + offset + 1, left, "=", right_start + offset + 1, right))
        elif tag == "delete":
            removed += len(left_block)
            for offset, left in enumerate(left_block):
                rows.append(SideBySideDiffRow(left_start + offset + 1, left, "-", None, ""))
        elif tag == "insert":
            added += len(right_block)
            for offset, right in enumerate(right_block):
                rows.append(SideBySideDiffRow(None, "", "+", right_start + offset + 1, right))
        elif tag == "replace":
            modified_blocks += 1
            max_len = max(len(left_block), len(right_block))
            for offset in range(max_len):
                left_exists = offset < len(left_block)
                right_exists = offset < len(right_block)
                if left_exists and right_exists:
                    rows.append(SideBySideDiffRow(
                        left_start + offset + 1,
                        left_block[offset],
                        "~",
                        right_start + offset + 1,
                        right_block[offset],
                    ))
                elif left_exists:
                    removed += 1
                    rows.append(SideBySideDiffRow(left_start + offset + 1, left_block[offset], "-", None, ""))
                else:
                    added += 1
                    rows.append(SideBySideDiffRow(None, "", "+", right_start + offset + 1, right_block[offset]))
    return rows, added, removed, modified_blocks


def extract_h3c_configuration_body(raw_text: str) -> str:
    lines = clean_h3c_device_text(raw_text).splitlines()
    start_index: int | None = None
    end_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == "#":
            start_index = index
            break
    if start_index is not None:
        for index in range(len(lines) - 1, start_index - 1, -1):
            if lines[index].strip().casefold() == "return":
                end_index = index
                break
    if start_index is not None and end_index is not None:
        return "\n".join(line.rstrip() for line in lines[start_index : end_index + 1])
    return _fallback_clean_config_output(lines)


def clean_config_for_diff(text: str) -> str:
    return extract_h3c_configuration_body(text)


def has_complete_config_body(raw_text: str) -> bool:
    lines = clean_h3c_device_text(raw_text).splitlines()
    has_start = False
    for line in lines:
        stripped = line.strip()
        if stripped == "#":
            has_start = True
        if has_start and stripped.casefold() == "return":
            return True
    return False


def structure_diff(config_a: str, config_b: str) -> dict[str, list[str]]:
    sections_a = set(config_structure_keys(config_a))
    sections_b = set(config_structure_keys(config_b))
    return {
        "only_in_a": sorted(sections_a - sections_b),
        "only_in_b": sorted(sections_b - sections_a),
    }


def config_structure_keys(text: str) -> list[str]:
    keys: list[str] = []
    for line in clean_config_for_diff(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            keys.append(stripped)
    return keys


def _fallback_clean_config_output(lines: list[str]) -> str:
    body_lines: list[str] = []
    fallback_lines: list[str] = []
    in_body = False
    for line in lines:
        stripped = line.strip()
        normalized = stripped.casefold()
        if not stripped or normalized in _CONFIG_COMMAND_ECHOES:
            continue
        if _PROMPT_PATTERN.match(stripped):
            if in_body:
                break
            continue
        fallback_lines.append(line.rstrip())
        if not in_body:
            if not _CONFIG_BODY_START_PATTERN.match(stripped):
                continue
            in_body = True
        body_lines.append(line.rstrip())
        if stripped.casefold() == "return":
            break
    return "\n".join(body_lines or fallback_lines)
