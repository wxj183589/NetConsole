from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = ROOT / "config" / "architecture"
EXCEPTIONS_PATH = CONFIG_ROOT / "exceptions.yaml"

REQUIRED_EXCEPTION_FIELDS = {
    "rule_id",
    "path",
    "reason",
    "owner",
    "created_at",
    "expires_at",
    "test",
}


@dataclass(frozen=True, order=True)
class Finding:
    rule_id: str
    path: str
    line: int
    message: str

    def diagnostic(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.rule_id} {location} {self.message}"


@dataclass(frozen=True)
class ExceptionEntry:
    rule_id: str
    path: str
    reason: str
    owner: str
    created_at: date
    expires_at: date
    test: str


def relative_path(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def load_json_yaml(path: Path) -> Any:
    """Load the JSON subset of YAML without adding a runtime dependency."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{relative_path(path)} must be UTF-8 JSON-compatible YAML: {exc}") from exc


def load_exceptions(path: Path = EXCEPTIONS_PATH, *, today: date | None = None) -> tuple[ExceptionEntry, ...]:
    raw = load_json_yaml(path)
    if not isinstance(raw, list):
        raise ValueError("config/architecture/exceptions.yaml must contain a list")
    current = today or date.today()
    entries: list[ExceptionEntry] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != REQUIRED_EXCEPTION_FIELDS:
            raise ValueError(
                f"exceptions.yaml item {index} must contain exactly "
                f"{sorted(REQUIRED_EXCEPTION_FIELDS)}"
            )
        values = {key: str(value).strip() for key, value in item.items()}
        if any(not value for value in values.values()):
            raise ValueError(f"exceptions.yaml item {index} contains an empty field")
        rule_id = values["rule_id"]
        item_path = values["path"].replace("\\", "/")
        test_path = values["test"].replace("\\", "/")
        if Path(item_path).is_absolute() or any(char in item_path for char in "*?["):
            raise ValueError(f"exceptions.yaml item {index} path must be exact and repository-relative")
        if not (ROOT / test_path).is_file():
            raise ValueError(f"exceptions.yaml item {index} test does not exist: {test_path}")
        try:
            created_at = date.fromisoformat(values["created_at"])
            expires_at = date.fromisoformat(values["expires_at"])
        except ValueError as exc:
            raise ValueError(f"exceptions.yaml item {index} dates must use YYYY-MM-DD") from exc
        if created_at > expires_at:
            raise ValueError(f"exceptions.yaml item {index} expires before it was created")
        if expires_at < current:
            raise ValueError(
                f"exceptions.yaml item {index} expired on {expires_at.isoformat()}: {rule_id} {item_path}"
            )
        key = (rule_id, item_path)
        if key in seen:
            raise ValueError(f"duplicate architecture exception: {rule_id} {item_path}")
        seen.add(key)
        entries.append(
            ExceptionEntry(
                rule_id=rule_id,
                path=item_path,
                reason=values["reason"],
                owner=values["owner"],
                created_at=created_at,
                expires_at=expires_at,
                test=test_path,
            )
        )
    return tuple(entries)


def apply_exceptions(
    findings: Iterable[Finding], exceptions: Iterable[ExceptionEntry]
) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
    exception_keys = {(item.rule_id, item.path) for item in exceptions}
    active: list[Finding] = []
    waived: list[Finding] = []
    for finding in sorted(set(findings)):
        target = waived if (finding.rule_id, finding.path) in exception_keys else active
        target.append(finding)
    return tuple(active), tuple(waived)


def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def finish(check_name: str, findings: Iterable[Finding]) -> int:
    try:
        exceptions = load_exceptions()
    except ValueError as exc:
        print(f"ARCH_EXCEPTION_INVALID config/architecture/exceptions.yaml {exc}")
        return 2
    active, waived = apply_exceptions(findings, exceptions)
    if active:
        print(f"[FAIL] {check_name}: {len(active)} finding(s), {len(waived)} waived")
        for finding in active:
            print(finding.diagnostic())
        return 1
    print(f"[PASS] {check_name}: 0 finding(s), {len(waived)} waived")
    return 0
