from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, Sequence


class CleanBuildLockError(Exception):
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_PROJECT_ROOT = PROJECT_ROOT
PYINSTALLER_BUILD_ROOT = PROJECT_ROOT / "release" / "_build" / "pyinstaller"
BUILD_ROOT = PYINSTALLER_BUILD_ROOT / "build"
DIST_ROOT = PYINSTALLER_BUILD_ROOT / "dist"
SPEC_ROOT = PYINSTALLER_BUILD_ROOT / "spec"
SPEC_FILE = SPEC_ROOT / "NetConsole.spec"
ENTRY_FILE = PROJECT_ROOT / "main.py"
RUNTIME_ROOT = BUILD_ROOT / "clean_runtime"
RUNTIME_MANIFEST = BUILD_ROOT / "clean_runtime_manifest.txt"

APP_NAME = "NetConsole"
EXE_NAME = "NetConsole.exe"
ICON_SOURCE = PROJECT_ROOT / "netconsole" / "ui" / "icons" / "love.ico"
INTERNAL_DIR = "_internal"

FORBIDDEN_PROJECT_SOURCES = ("docs", "tests", "project", ".git", "__pycache__")
FORBIDDEN_DATAS = ("", ".", "project", "docs", "tests")
FORBIDDEN_DIST_DIRS = ("docs", "tests", "project", "build", "spec")
FORBIDDEN_RUNTIME_NAMES = set(FORBIDDEN_PROJECT_SOURCES) | {"build", "dist", "spec"}
ALLOWED_RUNTIME = (
    "netconsole",
    "tools",
    "tools/fping_v5",
    "tools/fping_v5/fping.exe",
    "tools/fping_v5/cygwin1.dll",
    "tools/fping_v5/COPYING",
    "tools/fping_v5/CYGWIN_LICENSE",
    "tools/fping_v5/CYGWIN_LICENSE_NOTE.txt",
    "tools/fping_v5/README.txt",
    "tools/fping_v5/VERSION.txt",
    "tools/iperf",
    "tools/iperf/cygcrypto-3.dll",
    "tools/iperf/cygwin1.dll",
    "tools/iperf/cygz.dll",
    "tools/iperf/iperf3.exe",
    "netconsole/ui/icons",
    "netconsole/assets",
    "netconsole/assets/changelog.md",
)
ALLOWED_DIST_ROOT = (EXE_NAME, INTERNAL_DIR, "data", "runtime")
REQUIRED_PYINSTALLER_ARGS = (
    "--onedir",
    "--windowed",
    "--name",
    APP_NAME,
    "--icon",
    "netconsole/ui/icons/love.ico",
)


def validate_project_safety(
    datas: Iterable[Sequence[object]] | None = None,
    spec_text: str | None = None,
) -> None:
    if datas is not None:
        validate_datas(datas)
    if spec_text is not None:
        _validate_spec_text(spec_text)


def validate_datas(datas: Iterable[Sequence[object]]) -> None:
    for data in datas:
        if len(data) < 1:
            raise CleanBuildLockError("Illegal datasource detected: empty entry")
        source = _normalize_data_part(data[0])
        if _is_forbidden_source(source):
            raise CleanBuildLockError(f"Illegal datasource detected: {source or '<empty>'}")


def validate_allowed_runtime(datas: Iterable[Sequence[object]]) -> None:
    for data in datas:
        if len(data) < 2:
            raise CleanBuildLockError(f"Invalid data tuple: {data!r}")
        source = _normalize_data_part(data[0])
        destination = _normalize_data_part(data[1])
        if source not in ALLOWED_RUNTIME or destination not in ALLOWED_RUNTIME:
            raise CleanBuildLockError(f"Runtime data is not whitelisted: {data!r}")
    validate_datas(datas)


def validate_pyinstaller_command(args: Sequence[str]) -> None:
    normalized = [arg.replace("\\", "/") for arg in args]
    for item in ("--onedir", "--windowed"):
        if item not in normalized:
            raise CleanBuildLockError(f"Missing required PyInstaller option: {item}")
    _require_option_value(normalized, "--name", APP_NAME)
    _require_path_option(normalized, "--icon", ICON_SOURCE, "netconsole/ui/icons/love.ico")
    _require_option_value(normalized, "--distpath", str(DIST_ROOT).replace("\\", "/"))
    _require_option_value(normalized, "--workpath", str(BUILD_ROOT).replace("\\", "/"))


def validate_dist_output(app_dist: Path | None = None) -> None:
    app_dist = Path(app_dist or DIST_ROOT / APP_NAME)
    if not app_dist.exists():
        raise CleanBuildLockError(f"missing dist directory: {app_dist}")
    if not app_dist.is_dir():
        raise CleanBuildLockError(f"dist output is not a directory: {app_dist}")

    root_items = {path.name for path in app_dist.iterdir()}
    unexpected = sorted(root_items - set(ALLOWED_DIST_ROOT))
    if unexpected:
        raise CleanBuildLockError(f"CleanBuildLock violation: unexpected dist root items: {unexpected}")

    for required in (EXE_NAME, INTERNAL_DIR):
        if not (app_dist / required).exists():
            raise CleanBuildLockError(f"CleanBuildLock violation: missing required dist item: {required}")
    if (app_dist / "netconsole").exists():
        raise CleanBuildLockError("CleanBuildLock violation: netconsole must not exist outside _internal")
    if not (app_dist / INTERNAL_DIR / "netconsole").exists():
        raise CleanBuildLockError("CleanBuildLock violation: netconsole must exist inside _internal")

    for forbidden in FORBIDDEN_DIST_DIRS:
        if (app_dist / forbidden).exists():
            raise CleanBuildLockError(f"CleanBuildLock violation: forbidden folder exists: {forbidden}")

    for path in app_dist.rglob("*"):
        relative_parts = path.relative_to(app_dist).parts
        if _is_forbidden_dist_path(relative_parts):
            relative = path.relative_to(app_dist).as_posix()
            raise CleanBuildLockError(f"CleanBuildLock violation: forbidden runtime item exists: {relative}")


def clean_failed_outputs() -> None:
    for path in (DIST_ROOT, BUILD_ROOT, SPEC_ROOT):
        if path.exists():
            shutil.rmtree(path)


def _validate_spec_text(spec_text: str) -> None:
    forbidden_fragments = (
        "('.', '.')",
        '(".", ".")',
        "('', '.')",
        '("", ".")',
        "('project', 'project')",
        "('docs', 'docs')",
        "('tests', 'tests')",
        "datas=[('.', '.')]",
        'datas=[(".", ".")]',
    )
    for fragment in forbidden_fragments:
        if fragment in spec_text:
            raise CleanBuildLockError(f"Illegal PyInstaller spec datasource detected: {fragment}")


def _is_forbidden_dist_path(parts: tuple[str, ...]) -> bool:
    if not parts:
        return False
    lowered = tuple(part.lower() for part in parts)
    if lowered[0] in FORBIDDEN_DIST_DIRS:
        return True
    if len(lowered) >= 2 and lowered[:2] == (INTERNAL_DIR, "assets"):
        return True
    if any(part in {"tests", "project", "build", "spec", "__pycache__"} for part in lowered):
        return True
    if "docs" in lowered:
        return True
    return False


def _normalize_data_part(value: object) -> str:
    text = os.fspath(value) if isinstance(value, os.PathLike) else str(value)
    return text.replace("\\", "/").strip().strip("/").lower()


def _is_forbidden_source(source: str) -> bool:
    if source in FORBIDDEN_DATAS:
        return True
    parts = Path(source).parts
    return bool(parts and parts[0].lower() in FORBIDDEN_DATAS)


def _require_option_value(args: Sequence[str], option: str, expected: str) -> None:
    if option not in args:
        raise CleanBuildLockError(f"Missing required PyInstaller option: {option}")
    index = args.index(option)
    if index + 1 >= len(args):
        raise CleanBuildLockError(f"Missing value for PyInstaller option: {option}")
    actual = args[index + 1].replace("\\", "/")
    if actual != expected:
        raise CleanBuildLockError(f"Invalid PyInstaller {option}: {actual}")


def _require_path_option(args: Sequence[str], option: str, expected_path: Path, expected_relative: str) -> None:
    if option not in args:
        raise CleanBuildLockError(f"Missing required PyInstaller option: {option}")
    index = args.index(option)
    if index + 1 >= len(args):
        raise CleanBuildLockError(f"Missing value for PyInstaller option: {option}")
    actual = args[index + 1].replace("\\", "/")
    if actual == expected_relative:
        return
    try:
        resolved = Path(actual).resolve()
    except OSError:
        resolved = Path(actual)
    if resolved != expected_path.resolve():
        raise CleanBuildLockError(f"Invalid PyInstaller {option}: {actual}")
