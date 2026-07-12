from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from netconsole.build.clean_build_lock import (
    BUILD_PROJECT_ROOT as PROJECT_ROOT,
    BUILD_ROOT,
    CleanBuildLockError,
    DIST_ROOT,
    ENTRY_FILE,
    FORBIDDEN_DATAS,
    FORBIDDEN_PROJECT_SOURCES,
    ICON_SOURCE,
    SPEC_FILE,
    SPEC_ROOT,
    validate_allowed_runtime,
    validate_dist_output,
    validate_project_safety,
)
from scripts.check_runtime_deps import check_runtime_deps

CLEAN_BUILD = True
ROOT = Path(__file__).resolve().parent

ALLOWED_DATA = [
    ("netconsole", "netconsole"),
    ("tools/windows-x64/fping", "tools/windows-x64/fping"),
    ("tools/windows-x64/iperf3", "tools/windows-x64/iperf3"),
    ("netconsole/ui/icons", "netconsole/ui/icons"),
    ("netconsole/assets/open_source_notices.json", "netconsole/assets"),
    ("netconsole/assets/THIRD_PARTY_COMPONENTS.md", "netconsole/assets"),
    ("netconsole/assets/IPOP_v4.1_notice.md", "netconsole/assets"),
]
FORBIDDEN_DATA = [
    (item, item) for item in FORBIDDEN_DATAS
]
EXCLUDE_DIRS = [
    *FORBIDDEN_PROJECT_SOURCES,
    "build",
    "spec",
    "release",
]
EXCLUDE_FILES = {"*.pyc", "*.pyo"}
REQUIRED_TOOL_FILES = (
    Path("tools") / "windows-x64" / "fping" / "fping.exe",
    Path("tools") / "windows-x64" / "fping" / "cygwin1.dll",
    Path("tools") / "windows-x64" / "iperf3" / "iperf3.exe",
    Path("tools") / "windows-x64" / "iperf3" / "cygcrypto-3.dll",
    Path("tools") / "windows-x64" / "iperf3" / "cygwin1.dll",
    Path("tools") / "windows-x64" / "iperf3" / "cygz.dll",
)
REQUIRED_TOOL_EXECUTABLES = (
    Path("tools") / "windows-x64" / "fping" / "fping.exe",
    Path("tools") / "windows-x64" / "iperf3" / "iperf3.exe",
)
REQUIRED_VC_RUNTIME_DLLS = (
    "VCRUNTIME140.dll",
    "VCRUNTIME140_1.dll",
    "MSVCP140.dll",
    "CONCRT140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
)
TOOL_VERSION_MARKERS = {
    Path("tools") / "windows-x64" / "fping" / "fping.exe": ("Version 5.5", "fping"),
    Path("tools") / "windows-x64" / "iperf3" / "iperf3.exe": ("iperf 3.",),
}
VERSION_INFO_FILE = BUILD_ROOT / "version_info.txt"


def scan_import_graph() -> list[str]:
    return sorted(build_runtime_module_map().keys())


def build_runtime_module_map() -> dict[str, Path]:
    module_files: dict[str, Path] = {}
    seen_sources: set[Path] = set()
    pending_sources = [ENTRY_FILE]
    while pending_sources:
        source = pending_sources.pop()
        source = source.resolve()
        if source in seen_sources or not source.exists():
            continue
        seen_sources.add(source)
        for module in _imports_from_source(source):
            for resolved_module, module_file in _resolve_module_with_packages(module).items():
                if resolved_module not in module_files:
                    module_files[resolved_module] = module_file
                    pending_sources.append(module_file)
    return dict(sorted(module_files.items()))


def build_runtime_subset_from_import_graph() -> list[Path]:
    return list(build_runtime_module_map().values())


def build_runtime_datas_from_import_graph() -> list[tuple[str, str]]:
    datas: list[tuple[str, str]] = []
    for module_file in build_runtime_subset_from_import_graph():
        relative = module_file.relative_to(ROOT)
        datas.append((str(module_file), relative.parent.as_posix()))
    for icon in sorted((ROOT / "netconsole" / "ui" / "icons").glob("*")):
        if icon.is_file():
            datas.append((str(icon), "netconsole/ui/icons"))
    changelog = ROOT / "netconsole" / "docs" / "changelog.md"
    if changelog.is_file():
        datas.append((str(changelog), "netconsole/assets"))
    for source, destination in ALLOWED_DATA:
        source_path = ROOT / source
        if (source.startswith("tools/") and source_path.is_dir()) or source_path.is_file():
            if (str(source_path), destination) in datas:
                continue
            datas.append((str(source_path), destination))
    return datas


def _imports_from_source(source: Path) -> set[str]:
    runtime_modules: set[str] = set()
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return runtime_modules
    current_module = _source_to_module(source)
    current_package = current_module if source.name == "__init__.py" else current_module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_runtime_module(alias.name):
                    runtime_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base_module = _resolve_import_from_module(node, current_package)
            if base_module and _is_runtime_module(base_module):
                runtime_modules.add(base_module)
                for alias in node.names:
                    candidate = f"{base_module}.{alias.name}"
                    if _module_file(candidate):
                        runtime_modules.add(candidate)
    return runtime_modules


def _resolve_import_from_module(node: ast.ImportFrom, current_package: str) -> str | None:
    if node.level:
        relative = "." * node.level + (node.module or "")
        try:
            return importlib.util.resolve_name(relative, current_package)
        except ImportError:
            return None
    return node.module


def _is_runtime_module(module: str) -> bool:
    return module == "netconsole" or module.startswith("netconsole.")


def _resolve_module_with_packages(module: str) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    parts = module.split(".")
    for index in range(1, len(parts) + 1):
        package_module = ".".join(parts[:index])
        module_file = _module_file(package_module)
        if module_file:
            resolved[package_module] = module_file
    return resolved


def _module_file(module: str) -> Path | None:
    if not _is_runtime_module(module):
        return None
    relative_parts = module.split(".")
    module_path = ROOT.joinpath(*relative_parts)
    package_init = module_path / "__init__.py"
    if package_init.exists():
        return package_init
    file_path = module_path.with_suffix(".py")
    if file_path.exists():
        return file_path
    return None


def _source_to_module(source: Path) -> str:
    relative = source.resolve().relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def prepare_runtime() -> None:
    if not CLEAN_BUILD:
        raise CleanBuildLockError("Clean Build Mode is required for release packaging")
    clean_tool_cache_artifacts()
    validate_project_safety(ALLOWED_DATA)
    validate_allowed_runtime(ALLOWED_DATA)
    validate_tool_sources()


def clean_tool_cache_artifacts() -> None:
    tools_root = ROOT / "tools"
    if not tools_root.exists():
        return
    for cache_dir in tools_root.glob("**/__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir)
    for pattern in EXCLUDE_FILES:
        for artifact in tools_root.glob(f"**/{pattern}"):
            if artifact.is_file():
                artifact.unlink()


def write_spec() -> Path:
    validate_project_safety(ALLOWED_DATA)
    validate_allowed_runtime(ALLOWED_DATA)
    validate_tool_sources()
    SPEC_ROOT.mkdir(parents=True, exist_ok=True)
    write_version_info_file()
    runtime_imports = scan_import_graph()
    runtime_datas = build_runtime_datas_from_import_graph()
    vc_runtime_binaries = collect_vc_runtime_dlls()
    spec_text = f'''# -*- mode: python ; coding: utf-8 -*-
# Generated by clean_build_spec.py. Do not add project/docs/tests or "." to datas.

CLEAN_BUILD = {CLEAN_BUILD!r}
ALLOWED_DATA = {ALLOWED_DATA!r}
EXCLUDE_DIRS = {EXCLUDE_DIRS!r}
RUNTIME_IMPORTS = {runtime_imports!r}
RUNTIME_DATAS = {runtime_datas!r}
VC_RUNTIME_BINARIES = {vc_runtime_binaries!r}

from PyInstaller.utils.hooks import collect_all

pyside_datas, pyside_binaries, pyside_hiddenimports = collect_all("PySide6")

a = Analysis(
    [{str(ENTRY_FILE)!r}],
    pathex=[{str(ROOT)!r}],
    binaries=pyside_binaries + VC_RUNTIME_BINARIES,
    datas=RUNTIME_DATAS + pyside_datas,
    hiddenimports=pyside_hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=['tests', 'docs', 'project', '__pycache__'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NetConsole',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version={str(VERSION_INFO_FILE)!r},
    icon=[{str(ICON_SOURCE)!r}],
    contents_directory='_internal',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NetConsole',
)
'''
    validate_project_safety(ALLOWED_DATA, spec_text)
    SPEC_FILE.write_text(spec_text, encoding="utf-8")
    return SPEC_FILE


def write_version_info_file() -> Path:
    from netconsole.core.version import APP_VERSION
    from project.release import render_version_info

    VERSION_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_INFO_FILE.write_text(render_version_info(APP_VERSION), encoding="utf-8")
    return VERSION_INFO_FILE


def validate_dist() -> None:
    app_dist = DIST_ROOT / "NetConsole"
    validate_dist_output(app_dist)
    icon = app_dist / "_internal" / "netconsole" / "ui" / "icons" / "love.ico"
    if not icon.exists():
        raise CleanBuildLockError("runtime icon is missing")
    check_packaged_tools(app_dist)
    runtime_result = check_runtime_deps(app_dist)
    for message in runtime_result.messages:
        print(message)
    if not runtime_result.ok:
        raise CleanBuildLockError("packaged runtime dependency check failed")


def validate_tool_sources() -> None:
    missing = [path.as_posix() for path in REQUIRED_TOOL_FILES if not (ROOT / path).is_file()]
    if missing:
        raise CleanBuildLockError(f"required runtime tool is missing: {', '.join(missing)}")
    if not (ROOT / "tools").is_dir():
        raise CleanBuildLockError("required tools directory is missing")


def collect_vc_runtime_dlls(search_roots: list[Path] | None = None, *, required: bool = True) -> list[tuple[str, str]]:
    roots = search_roots or _default_vc_runtime_search_roots()
    found: list[tuple[str, str]] = []
    missing: list[str] = []
    for dll_name in REQUIRED_VC_RUNTIME_DLLS:
        dll_path = _find_runtime_dll(dll_name, roots)
        if dll_path is None:
            missing.append(dll_name)
            continue
        found.append((str(dll_path), "."))
    if missing and required:
        raise CleanBuildLockError(
            "required VC++ runtime DLL is missing: "
            + ", ".join(missing)
            + ". Install Visual C++ 2015-2022 Redistributable x64 on the build machine or provide app-local runtime DLLs."
        )
    for dll_path, _target in found:
        print(f"[OK] VC runtime included: {Path(dll_path).name}")
    return found


def _default_vc_runtime_search_roots() -> list[Path]:
    candidates = [
        Path(sys.executable).resolve().parent,
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        DIST_ROOT / "NetConsole" / "_internal",
    ]
    pyside_spec = importlib.util.find_spec("PySide6")
    if pyside_spec and pyside_spec.submodule_search_locations:
        candidates.extend(Path(path).resolve() for path in pyside_spec.submodule_search_locations)
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        candidates.extend([Path(windir) / "System32", Path(windir) / "SysWOW64"])
    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    for base in program_files:
        if base:
            candidates.extend(Path(base).glob("Microsoft Visual Studio/*/*/VC/Redist/MSVC/*/x64/Microsoft.VC*.CRT"))
            candidates.extend(Path(base).glob("Microsoft Visual C++ Redistributable*/**"))
    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _find_runtime_dll(dll_name: str, roots: list[Path]) -> Path | None:
    dll_name_lower = dll_name.casefold()
    for root in roots:
        if root.is_file() and root.name.casefold() == dll_name_lower:
            return root
        direct = root / dll_name
        if direct.is_file():
            return direct
    return None


def check_packaged_tools(app_dist: Path | None = None, *, run_version_check: bool = True) -> None:
    app_dist = Path(app_dist or DIST_ROOT / "NetConsole")
    if run_version_check and _same_path(app_dist, DIST_ROOT / "NetConsole"):
        source_files = sorted(
            path.relative_to(ROOT)
            for tool_dir in (
                ROOT / "tools" / "windows-x64" / "fping",
                ROOT / "tools" / "windows-x64" / "iperf3",
            )
            for path in tool_dir.glob("**/*")
            if path.is_file()
        )
        missing_packaged = [relative for relative in source_files if not (app_dist / "_internal" / relative).is_file()]
        if missing_packaged:
            raise CleanBuildLockError(
                "packaged tools directory is incomplete: "
                + ", ".join(relative.as_posix() for relative in missing_packaged)
            )
    for relative in REQUIRED_TOOL_FILES:
        packaged = app_dist / "_internal" / relative
        if not packaged.is_file():
            raise CleanBuildLockError(f"packaged runtime tool is missing: {packaged}")
        print(f"[OK] {relative.as_posix()} included")
        if run_version_check and relative in REQUIRED_TOOL_EXECUTABLES:
            _check_tool_version(packaged, relative)


def _check_tool_version(tool_path: Path, relative: Path) -> None:
    try:
        completed = subprocess.run([str(tool_path), "-v"], cwd=tool_path.parent, capture_output=True, text=True, timeout=5)
    except Exception as exc:
        raise CleanBuildLockError(f"packaged runtime tool version check failed: {relative.as_posix()}: {exc}") from exc
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    markers = TOOL_VERSION_MARKERS[relative]
    if not any(marker in output for marker in markers):
        raise CleanBuildLockError(f"packaged runtime tool version output is invalid: {relative.as_posix()}")
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "version detected")
    print(f"[OK] {relative.as_posix()} version: {first_line}")


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _is_excluded_tool_artifact(path: Path) -> bool:
    relative_parts = path.relative_to(ROOT / "tools").parts
    if "ipop" in {part.casefold() for part in relative_parts}:
        return True
    if path.suffix.casefold() == ".py":
        return True
    if any(part == "__pycache__" for part in relative_parts):
        return True
    return any(path.match(pattern) for pattern in EXCLUDE_FILES)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and validate NetConsole clean PyInstaller build")
    parser.add_argument("--prepare", action="store_true", help="validate runtime-only graph")
    parser.add_argument("--write-spec", action="store_true", help="write project/spec/NetConsole.spec")
    parser.add_argument("--validate", action="store_true", help="validate existing dist output")
    args = parser.parse_args()

    if args.prepare:
        prepare_runtime()
    if args.write_spec:
        write_spec()
    if args.validate:
        validate_dist()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
