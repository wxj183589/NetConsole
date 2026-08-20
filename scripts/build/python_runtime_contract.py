from __future__ import annotations

import argparse
import json
import platform
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPROVAL_RELATIVE_PATH = Path("config/pyinstaller-approved-distributions.json")
APPROVAL_SCHEMA = "netconsole.pyinstaller-approved-distributions.v1"
TARGET_PLATFORM = "windows-x64"
EXACT_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class PythonRuntimeContractError(RuntimeError):
    pass


def load_python_runtime_version(project_root: Path = PROJECT_ROOT) -> str:
    path = Path(project_root).resolve() / APPROVAL_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PythonRuntimeContractError(
            f"无法读取 Python runtime contract：{path}"
        ) from exc
    if not isinstance(payload, dict):
        raise PythonRuntimeContractError("Python runtime contract 必须是 JSON 对象")
    if payload.get("schema") != APPROVAL_SCHEMA:
        raise PythonRuntimeContractError("Python runtime contract schema 不受支持")
    if payload.get("platform") != TARGET_PLATFORM:
        raise PythonRuntimeContractError("Python runtime contract 必须面向 windows-x64")
    version = str(payload.get("python_version") or "").strip()
    if not EXACT_VERSION_PATTERN.fullmatch(version):
        raise PythonRuntimeContractError(
            "Python runtime contract 必须使用 major.minor.patch 精确版本"
        )
    return version


def assert_current_python_runtime(project_root: Path = PROJECT_ROOT) -> str:
    expected = load_python_runtime_version(project_root)
    actual = platform.python_version()
    if actual != expected:
        raise PythonRuntimeContractError(
            f"Python runtime 版本不一致：expected={expected}, actual={actual}"
        )
    if platform.python_implementation() != "CPython":
        raise PythonRuntimeContractError(
            "Python runtime implementation 必须是 CPython"
        )
    if platform.architecture()[0] != "64bit":
        raise PythonRuntimeContractError("Python runtime architecture 必须是 x64")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read or validate the authoritative CPython x64 runtime contract"
    )
    parser.add_argument(
        "--check-current",
        action="store_true",
        help="require the current interpreter to match the contract",
    )
    args = parser.parse_args()
    try:
        version = (
            assert_current_python_runtime()
            if args.check_current
            else load_python_runtime_version()
        )
    except PythonRuntimeContractError as exc:
        print(f"[ERROR] {exc}")
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
