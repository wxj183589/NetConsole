from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATH = ROOT / "resources" / "command_reference.json"
SCAN_DIRS = ("src/netconsole",)
TEXT_SUFFIXES = {".py"}
SKIP_PATH_PARTS = {"build", "__pycache__"}

COMMAND_PATTERNS = (
    r"dis\s+counters\s+rate\s+(?:inbound|outbound)\s+interface",
    r"display\s+[a-z0-9][a-z0-9\s\-/|]+",
    r"screen-length\s+\w+",
    r"system-view",
    r"probe",
    r"return",
    r"quit",
    r"wlan\s+auto-ap\s+persistent\s+all",
    r"wlan\s+ap-execute\s+all\s+exec-console\s+enable",
    r"terminal\s+(?:monitor|logging\s+level\s+\d+)",
    r"user-interface\s+vty\s+\d+\s+\d+",
    r"idle-timeout\s+\d+\s+\d+",
    r"repeat\s+(?:\d+|<[^>]+>)\s+delay\s+(?:\d+|<[^>]+>)",
    r"save\s+force",
    r"dir\s+flash:/[^\s\"']*",
    r"ping\s+(?:-c\s+(?:<count>|\d+)\s+)?(?:<ip>|\d{1,3}(?:\.\d{1,3}){3})",
    r"ping\s+-n\s+(?:<count>|\d+)\s+-l\s+(?:<size>|\d+)\s+-w\s+(?:<timeout_ms>|\d+)\s+(?:<target>|[\w.\-]+)",
    r"ping\s+-c\s+\d+\s+\d{1,3}(?:\.\d{1,3}){3}",
    r"iperf3(?:\.exe)?(?:\s+[^\n\"']*)?",
    r"Fping_v3\.exe(?:\s+[^\n\"']*)?",
    r"netsh\s+wlan\s+show\s+(?:interfaces|networks\s+mode=bssid)",
    r"New-NetRoute\s+-DestinationPrefix\s+(?:<network>|'[^']+')",
    r"Remove-NetRoute\s+-DestinationPrefix\s+(?:<network>|'[^']+')",
    r"Get-Net(?:Adapter|IPConfiguration|Route)",
    r"route\s+print\s+-4",
    r"control\s+ncpa\.cpl",
    r"WinSCP\.exe",
    r"RESTful\s+API",
)


@dataclass(frozen=True)
class Candidate:
    command: str
    path: Path
    line_no: int


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit command strings against resources/command_reference.json")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    reference = load_reference()
    candidates = scan_candidates()
    reference_templates = build_reference_templates(reference)
    missing = [
        item
        for item in candidates
        if not matches_reference(item.command, reference_templates)
        and not is_expected_noise(item.command, item.path)
    ]
    duplicate_ids = duplicate_values([str(item.get("id") or "") for item in reference])
    duplicate_templates = duplicate_values([normalize(str(item.get("command_template") or "")) for item in reference])

    summary = {
        "reference_count": len(reference),
        "candidate_count": len(candidates),
        "missing_candidate_count": len(missing),
        "duplicate_ids": duplicate_ids,
        "duplicate_templates": duplicate_templates,
        "missing_candidates": [
            {"command": item.command, "path": str(item.path.relative_to(ROOT)), "line": item.line_no}
            for item in missing[:200]
        ],
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1 if missing or duplicate_ids else 0

    print(f"命令清单条目：{summary['reference_count']}")
    print(f"源码候选命令：{summary['candidate_count']}")
    print(f"疑似未归档候选：{summary['missing_candidate_count']}")
    if duplicate_ids:
        print("重复 ID：")
        for value in duplicate_ids:
            print(f"  - {value}")
    if duplicate_templates:
        print("重复命令模板：")
        for value in duplicate_templates:
            print(f"  - {value}")
    if missing:
        print("疑似未归档候选（前 200 条）：")
        for item in missing[:200]:
            print(f"  - {item.path.relative_to(ROOT)}:{item.line_no} {item.command}")
    else:
        print("未发现明显遗漏候选。")
    return 1 if missing or duplicate_ids else 0


def load_reference() -> list[dict[str, object]]:
    payload = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    items = payload.get("items", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("resources/command_reference.json must contain a list or an items list")
    return [item for item in items if isinstance(item, dict)]


def scan_candidates() -> list[Candidate]:
    results: dict[tuple[str, str, int], Candidate] = {}
    combined = re.compile("|".join(f"(?:{pattern})" for pattern in COMMAND_PATTERNS), re.IGNORECASE)
    for directory in SCAN_DIRS:
        root = ROOT / directory
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if path == REFERENCE_PATH:
                continue
            if any(part in SKIP_PATH_PARTS for part in path.relative_to(ROOT).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, literal in iter_python_string_literals(text, path):
                for line in literal.splitlines():
                    for match in combined.finditer(line):
                        command = normalize_candidate(match.group(0))
                        key = (command.casefold(), str(path), line_no)
                        results[key] = Candidate(command, path, line_no)
    return sorted(results.values(), key=lambda item: (str(item.path), item.line_no, item.command))


def iter_python_string_literals(text: str, path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    values: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        value = string_node_value(node)
        if value is not None:
            values.append((getattr(node, "lineno", 1), value))
    return values


def string_node_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parts.append(item.value)
            elif isinstance(item, ast.FormattedValue):
                parts.append("<value>")
        return "".join(parts)
    return None


def build_reference_templates(reference: list[dict[str, object]]) -> set[str]:
    templates: set[str] = set()
    for item in reference:
        template = str(item.get("command_template") or "")
        for part in split_reference_template(template):
            templates.add(normalize(part))
    return templates


def split_reference_template(template: str) -> list[str]:
    parts = [template]
    for separator in (" / ", "; "):
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(separator))
        parts = next_parts
    return [part.strip() for part in parts if part.strip()]


def matches_reference(command: str, reference_templates: set[str]) -> bool:
    normalized = normalize(command)
    if normalized in reference_templates:
        return True
    command_core = normalize(strip_optional_segments(command))
    for template in reference_templates:
        template_core = normalize(strip_optional_segments(template))
        if command_core == template_core:
            return True
        if placeholder_prefix_match(command_core, template_core):
            return True
    return False


def placeholder_prefix_match(command: str, template: str) -> bool:
    template_prefix = re.split(r"\s+<[^>]+>", template, maxsplit=1)[0].strip()
    if template_prefix and command.startswith(template_prefix):
        return True
    command_prefix = re.split(r"\s+<[^>]+>", command, maxsplit=1)[0].strip()
    return bool(command_prefix and template.startswith(command_prefix))


def strip_optional_segments(value: str) -> str:
    return re.sub(r"\s*\[[^\]]+\]", "", value).strip()


def normalize_candidate(value: str) -> str:
    text = value.strip().strip("`'\",)")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+ normally exposes.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"ping -c \d+ \d{1,3}(?:\.\d{1,3}){3}", "ping -c <count> <ip>", text)
    text = re.sub(r"ping -c <[^>]+> <[^>]+>", "ping -c <count> <ip>", text, flags=re.IGNORECASE)
    text = re.sub(r"ping -n <[^>]+> -l <[^>]+> -w <[^>]+> <[^>]+>", "ping -n <count> -l <size> -w <timeout_ms> <target>", text, flags=re.IGNORECASE)
    text = re.sub(r"repeat (?:\d+|<[^>]+>) delay (?:\d+|<[^>]+>)", "repeat <count> delay <seconds>", text, flags=re.IGNORECASE)
    text = re.sub(r"display ar5drv (?:\d+|<[^>]+>) channelbusy", "display ar5drv <radio_id> channelbusy", text, flags=re.IGNORECASE)
    text = re.sub(r"display ar5drv (?:\d+|<[^>]+>) statistics", "display ar5drv <radio_id> statistics", text, flags=re.IGNORECASE)
    text = re.sub(r"display ar5drv (?:\d+|<[^>]+>) client all rssi", "display ar5drv <radio_id> client all rssi", text, flags=re.IGNORECASE)
    text = re.sub(r"display ar5drv (?:\d+|<[^>]+>) client all status", "display ar5drv <radio_id> client all status", text, flags=re.IGNORECASE)
    text = re.sub(r"New-NetRoute -DestinationPrefix '[^']+'", "New-NetRoute -DestinationPrefix <network>", text, flags=re.IGNORECASE)
    text = re.sub(r"Remove-NetRoute -DestinationPrefix '[^']+'", "Remove-NetRoute -DestinationPrefix <network>", text, flags=re.IGNORECASE)
    return text


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def is_expected_noise(command: str, path: Path) -> bool:
    text = normalize(command)
    relative = path.relative_to(ROOT)
    if relative.parts[:2] == ("netconsole", "core") and relative.name == "i18n.py":
        return True
    if text in {"display ", "iperf3", "iperf3.exe", "fping_v3.exe", "restful api"}:
        return True
    if text in {"get-netadapter", "get-netipconfiguration", "get-netroute"}:
        return True
    if text.startswith("display fields") or text.startswith("display message"):
        return True
    if text.startswith("display colour") or text.startswith("display import"):
        return True
    if text in {"display like", "display from ap", "display helpers"}:
        return True
    if text.startswith("iperf3 not found"):
        return True
    if text.startswith("display ar5drv statistics |"):
        return True
    if text.startswith("display ar5drv <radio_id> channelbusy |"):
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
