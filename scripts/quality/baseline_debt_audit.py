from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.architecture.cli import CHECKS
from scripts.architecture.guard_core import Finding, ROOT, apply_exceptions, load_exceptions


MANIFEST_PATH = ROOT / "config" / "ci" / "baseline_failures.yaml"
WILDCARD_CHARS = frozenset("*?[")
CHECK_NAMES = ("architecture", "ruff", "python")


class BaselineAuditError(ValueError):
    pass


def _repo_path(value: str, *, field: str, require_file: bool = True) -> str:
    normalized = value.replace("\\", "/").strip()
    candidate = Path(normalized)
    if not normalized or candidate.is_absolute() or any(char in normalized for char in WILDCARD_CHARS):
        raise BaselineAuditError(f"{field} must be an exact repository-relative path")
    if require_file and not (ROOT / normalized).is_file():
        raise BaselineAuditError(f"{field} does not exist: {normalized}")
    return normalized


def _load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineAuditError(f"{path} must be UTF-8 JSON-compatible YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise BaselineAuditError("baseline manifest must be an object")
    required = {"schema_version", "policy", "python", "architecture", "ruff"}
    if set(payload) != required or payload.get("schema_version") != 1:
        raise BaselineAuditError(f"baseline manifest must contain exactly {sorted(required)} with schema_version=1")
    policy = payload.get("policy")
    expected_policy = {
        "allow_wildcards",
        "allow_directory_ignores",
        "allow_global_continue_on_error",
        "new_finding",
        "resolved_finding",
        "same_product_version_decision",
    }
    if not isinstance(policy, dict) or set(policy) != expected_policy:
        raise BaselineAuditError("baseline policy fields are incomplete or unexpected")
    if any(policy[field] is not False for field in ("allow_wildcards", "allow_directory_ignores", "allow_global_continue_on_error")):
        raise BaselineAuditError("baseline policy cannot allow wildcards, directory ignores, or global continue-on-error")
    for section in CHECK_NAMES:
        if not isinstance(payload.get(section), list):
            raise BaselineAuditError(f"baseline section must be a list: {section}")

    python_entries: list[dict[str, str]] = []
    for index, item in enumerate(payload["python"], start=1):
        if not isinstance(item, dict) or set(item) != {"nodeid", "reason"}:
            raise BaselineAuditError(f"python baseline item {index} must contain nodeid and reason only")
        nodeid = str(item["nodeid"]).strip()
        if not nodeid or any(char in nodeid for char in WILDCARD_CHARS):
            raise BaselineAuditError(f"python baseline item {index} must use an exact nodeid")
        test_path = _repo_path(nodeid.split("::", 1)[0], field=f"python baseline item {index} nodeid")
        if "::" not in nodeid or not nodeid.removeprefix(test_path).startswith("::"):
            raise BaselineAuditError(f"python baseline item {index} nodeid must include an exact test selector")
        reason = str(item["reason"]).strip()
        if not reason:
            raise BaselineAuditError(f"python baseline item {index} reason is empty")
        python_entries.append({"nodeid": nodeid, "reason": reason})

    architecture_entries: list[dict[str, Any]] = []
    for index, item in enumerate(payload["architecture"], start=1):
        fields = {"rule_id", "path", "line", "message", "reason"}
        if not isinstance(item, dict) or set(item) != fields:
            raise BaselineAuditError(f"architecture baseline item {index} fields are invalid")
        path_value = _repo_path(str(item["path"]), field=f"architecture baseline item {index} path")
        line = item["line"]
        if not isinstance(line, int) or line < 0:
            raise BaselineAuditError(f"architecture baseline item {index} line must be a non-negative integer")
        values = {
            "rule_id": str(item["rule_id"]).strip(),
            "path": path_value,
            "line": line,
            "message": str(item["message"]).strip(),
            "reason": str(item["reason"]).strip(),
        }
        if not values["rule_id"] or not values["message"] or not values["reason"]:
            raise BaselineAuditError(f"architecture baseline item {index} contains an empty field")
        architecture_entries.append(values)

    ruff_entries: list[dict[str, Any]] = []
    for index, item in enumerate(payload["ruff"], start=1):
        fields = {"code", "path", "line", "message", "reason"}
        if not isinstance(item, dict) or set(item) != fields:
            raise BaselineAuditError(f"ruff baseline item {index} fields are invalid")
        path_value = _repo_path(str(item["path"]), field=f"ruff baseline item {index} path")
        line = item["line"]
        if not isinstance(line, int) or line < 1:
            raise BaselineAuditError(f"ruff baseline item {index} line must be a positive integer")
        values = {
            "code": str(item["code"]).strip(),
            "path": path_value,
            "line": line,
            "message": str(item["message"]).strip(),
            "reason": str(item["reason"]).strip(),
        }
        if not all(values[field] for field in ("code", "message", "reason")):
            raise BaselineAuditError(f"ruff baseline item {index} contains an empty field")
        ruff_entries.append(values)

    python_keys = [item["nodeid"] for item in python_entries]
    if len(set(python_keys)) != len(python_keys):
        raise BaselineAuditError("python baseline contains duplicate nodeids")
    architecture_keys = [_architecture_key(item) for item in architecture_entries]
    if len(set(architecture_keys)) != len(architecture_keys):
        raise BaselineAuditError("architecture baseline contains duplicate findings")
    ruff_keys = [_ruff_key(item) for item in ruff_entries]
    if len(set(ruff_keys)) != len(ruff_keys):
        raise BaselineAuditError("ruff baseline contains duplicate findings")
    return {
        "policy": policy,
        "python": python_entries,
        "architecture": architecture_entries,
        "ruff": ruff_entries,
    }


def _architecture_key(item: dict[str, Any]) -> tuple[str, str, int, str]:
    return (str(item["rule_id"]), str(item["path"]), int(item["line"]), str(item["message"]))


def _ruff_key(item: dict[str, Any]) -> tuple[str, str, int, str]:
    return (str(item["code"]), str(item["path"]), int(item["line"]), str(item["message"]))


def _finding_key(finding: Finding) -> tuple[str, str, int, str]:
    return (finding.rule_id, finding.path.replace("\\", "/"), finding.line, finding.message)


def _architecture_actual() -> list[dict[str, Any]]:
    try:
        exceptions = load_exceptions()
    except ValueError as exc:
        raise BaselineAuditError(str(exc)) from exc
    raw_findings: list[Finding] = []
    for check in CHECKS.values():
        raw_findings.extend(check())
    active, _ = apply_exceptions(raw_findings, exceptions)
    raw_keys = {(finding.rule_id, finding.path.replace("\\", "/")) for finding in raw_findings}
    entries = [
        {
            "rule_id": finding.rule_id,
            "path": finding.path.replace("\\", "/"),
            "line": finding.line,
            "message": finding.message,
        }
        for finding in active
    ]
    for exception in exceptions:
        if (exception.rule_id, exception.path) not in raw_keys:
            entries.append(
                {
                    "rule_id": "ARCH_EXCEPTION_UNUSED",
                    "path": exception.path,
                    "line": 0,
                    "message": "unused architecture exception",
                }
            )
    return sorted(entries, key=_architecture_key)


def _ruff_actual() -> list[dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format=json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise BaselineAuditError(f"ruff audit could not run: {result.stderr.strip() or result.stdout.strip()}")
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise BaselineAuditError(f"ruff JSON output is invalid: {exc}") from exc
    if not isinstance(payload, list):
        raise BaselineAuditError("ruff JSON output must be a list")
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise BaselineAuditError(f"ruff output item {index} is not an object")
        filename = str(item.get("filename") or "")
        path = Path(filename)
        if path.is_absolute():
            try:
                filename = path.resolve().relative_to(ROOT).as_posix()
            except ValueError as exc:
                raise BaselineAuditError(f"ruff finding is outside the repository: {filename}") from exc
        else:
            filename = filename.replace("\\", "/")
        location = item.get("location")
        if not isinstance(location, dict) or not isinstance(location.get("row"), int):
            raise BaselineAuditError(f"ruff output item {index} has no exact row")
        entries.append(
            {
                "code": str(item.get("code") or ""),
                "path": filename,
                "line": int(location["row"]),
                "message": str(item.get("message") or ""),
            }
        )
    return sorted(entries, key=_ruff_key)


def _compare(
    label: str,
    expected: Iterable[dict[str, Any]],
    actual: Iterable[dict[str, Any]],
    key: Callable[[dict[str, Any]], tuple[str, str, int, str]],
) -> int:
    expected_map = {key(item): item for item in expected}
    actual_map = {key(item): item for item in actual}
    new_keys = sorted(set(actual_map) - set(expected_map))
    resolved_keys = sorted(set(expected_map) - set(actual_map))
    print(f"{label}_EXPECTED={len(expected_map)}")
    print(f"{label}_ACTUAL={len(actual_map)}")
    print(f"{label}_NEW={len(new_keys)}")
    print(f"{label}_RESOLVED={len(resolved_keys)}")
    for item_key in new_keys:
        print(f"BASELINE_NEW {label} {item_key}")
    for item_key in resolved_keys:
        print(f"BASELINE_SHRINK {label} {item_key}")
    return len(new_keys)


def _test_root() -> Path:
    test_base = (ROOT.parents[1] / "test-data" / "NetConsole").resolve()
    configured = os.environ.get("NETCONSOLE_DATA_ROOT", "").strip()
    root = Path(configured).resolve() if configured else test_base / f"baseline-debt-{uuid.uuid4().hex}"
    production = Path(r"D:\NetConsoleData").resolve()
    if root == production or not root.is_relative_to(test_base):
        raise BaselineAuditError(
            "NETCONSOLE_DATA_ROOT must be an isolated child of D:\\study\\NetConsole-Workspace\\test-data\\NetConsole"
        )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run_python_baseline(entries: list[dict[str, str]]) -> tuple[int, int]:
    base = _test_root() / f"baseline-nodes-{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    retained = 0
    resolved = 0
    for index, item in enumerate(entries, start=1):
        nodeid = item["nodeid"]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                nodeid,
                "-q",
                "--tb=short",
                "--basetemp",
                str(base / f"node-{index}"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode == 0:
            resolved += 1
            print(f"BASELINE_NODE_RESOLVED {nodeid}")
        elif result.returncode == 1:
            retained += 1
            print(f"BASELINE_NODE_RETAINED {nodeid}")
        elif result.returncode == 4 and ("not found" in output.lower() or "no tests ran" in output.lower()):
            resolved += 1
            print(f"BASELINE_NODE_MISSING {nodeid}")
        else:
            print(f"BASELINE_NODE_AUDIT_ERROR {nodeid} exit={result.returncode}")
            print(output[-4000:])
            raise BaselineAuditError(f"could not audit baseline node: {nodeid}")
    print(f"PYTHON_BASELINE_RETAINED={retained}")
    print(f"PYTHON_BASELINE_RESOLVED={resolved}")
    return retained, resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare current quality findings with exact NetConsole baseline debt.")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--checks", nargs="+", choices=(*CHECK_NAMES, "all"), default=["all"])
    args = parser.parse_args()
    try:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = ROOT / manifest_path
        manifest = _load_manifest(manifest_path.resolve())
        print(f"BASELINE_MANIFEST=PASS path={manifest_path.resolve().relative_to(ROOT).as_posix()}")
        selected = set(args.checks)
        if "all" in selected:
            selected = set(CHECK_NAMES)
        new_failures = 0
        if "architecture" in selected:
            new_failures += _compare(
                "ARCHITECTURE_BASELINE",
                manifest["architecture"],
                _architecture_actual(),
                _architecture_key,
            )
        if "ruff" in selected:
            new_failures += _compare("RUFF_BASELINE", manifest["ruff"], _ruff_actual(), _ruff_key)
        if "python" in selected:
            _run_python_baseline(manifest["python"])
        print(f"BASELINE_DEBT_COUNT={sum(len(manifest[name]) for name in CHECK_NAMES)}")
        print(f"NEW_FAILURES={new_failures}")
        print(f"BASELINE_DEBT_MATCH={'PASS' if new_failures == 0 else 'FAIL'}")
        return 0 if new_failures == 0 else 1
    except (BaselineAuditError, OSError, ValueError) as exc:
        print(f"BASELINE_AUDIT=FAIL {exc}")
        print("BASELINE_DEBT_MATCH=FAIL")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
