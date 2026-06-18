from __future__ import annotations

import argparse
import ast
import importlib.util
import shutil
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
    RUNTIME_ROOT,
    SPEC_FILE,
    SPEC_ROOT,
    validate_allowed_runtime,
    validate_dist_output,
    validate_project_safety,
)

CLEAN_BUILD = True
ROOT = Path(__file__).resolve().parent

ALLOWED_DATA = [
    ("netconsole", "netconsole"),
    ("data", "data"),
    ("netconsole/ui/icons", "netconsole/ui/icons"),
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
    module_map = build_runtime_module_map()
    staged_files: list[Path] = []
    for module_file in module_map.values():
        relative = module_file.relative_to(ROOT)
        destination = RUNTIME_ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module_file, destination)
        staged_files.append(destination)
    _copy_runtime_assets()
    (RUNTIME_ROOT / "data").mkdir(parents=True, exist_ok=True)
    return staged_files


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
    validate_project_safety(ALLOWED_DATA)
    validate_allowed_runtime(ALLOWED_DATA)
    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    RUNTIME_ROOT.mkdir(parents=True)
    build_runtime_subset_from_import_graph()


def write_spec() -> Path:
    validate_project_safety(ALLOWED_DATA)
    validate_allowed_runtime(ALLOWED_DATA)
    SPEC_ROOT.mkdir(parents=True, exist_ok=True)
    runtime_imports = scan_import_graph()
    spec_text = f'''# -*- mode: python ; coding: utf-8 -*-
# Generated by clean_build_spec.py. Do not add project/docs/tests or "." to datas.

CLEAN_BUILD = {CLEAN_BUILD!r}
ALLOWED_DATA = {ALLOWED_DATA!r}
EXCLUDE_DIRS = {EXCLUDE_DIRS!r}
RUNTIME_IMPORTS = {runtime_imports!r}

a = Analysis(
    [{str(ENTRY_FILE)!r}],
    pathex=[{str(ROOT)!r}],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    version={str(PROJECT_ROOT / "version_info.txt")!r},
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


def finalize_dist() -> None:
    app_dist = DIST_ROOT / "NetConsole"
    if not app_dist.exists():
        raise FileNotFoundError(f"missing PyInstaller output: {app_dist}")
    _replace_with_staged_files(RUNTIME_ROOT / "netconsole", app_dist / "netconsole")
    _replace_with_staged_files(RUNTIME_ROOT / "data", app_dist / "data")
    validate_dist()


def validate_dist() -> None:
    app_dist = DIST_ROOT / "NetConsole"
    validate_dist_output(app_dist)
    icon = app_dist / "netconsole" / "ui" / "icons" / "love.ico"
    if not icon.exists():
        raise CleanBuildLockError("runtime icon is missing")


def _copy_runtime_assets() -> None:
    for icon in (ROOT / "netconsole" / "ui" / "icons").glob("*"):
        if icon.is_file():
            destination = RUNTIME_ROOT / "netconsole" / "ui" / "icons" / icon.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(icon, destination)


def _replace_with_staged_files(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and validate NetConsole clean PyInstaller build")
    parser.add_argument("--prepare", action="store_true", help="stage runtime-only files")
    parser.add_argument("--write-spec", action="store_true", help="write project/spec/NetConsole.spec")
    parser.add_argument("--finalize", action="store_true", help="copy runtime subset into dist and validate")
    parser.add_argument("--validate", action="store_true", help="validate existing dist output")
    args = parser.parse_args()

    if args.prepare:
        prepare_runtime()
    if args.write_spec:
        write_spec()
    if args.finalize:
        finalize_dist()
    if args.validate:
        validate_dist()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
