from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from packaging.utils import canonicalize_name

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
from netconsole.core.feature_flags import default_profile
from netconsole.core.version import APP_VERSION
from scripts.build.check_runtime_deps import (
    check_python_environment,
    check_runtime_deps,
)
from scripts.build.generate_sbom import (
    PACKAGED_PYTHON_DISTRIBUTIONS,
    required_python_component_versions,
    runtime_dependency_versions,
    runtime_direct_dependency_names,
    write_runtime_sbom,
)
from scripts.build.pyinstaller_artifact_inventory import (
    ArtifactInventoryError,
    collect_pyinstaller_distributions,
    load_approved_distributions,
    write_inventory,
)
from scripts.build.web_frontend_meta import validate_web_frontend_meta
from scripts.build.build_metadata import (
    BUILD_METADATA_ENV,
    BuildMetadataError,
    collect_build_metadata,
    decode_build_metadata,
    encode_build_metadata,
    validate_build_metadata,
)

CLEAN_BUILD = True
ROOT = PROJECT_ROOT
SRC_ROOT = ROOT / "src"
DEVICE_COMMAND_PROFILES_SOURCE = "resources/device_command_profiles.json"
DEVICE_COMPATIBILITY_PROFILES_SOURCE = "resources/device_compatibility_profiles.json"
LOG_POLICY_SOURCE = "src/netconsole/resources/log_policy.json"
PACKAGED_DEVICE_COMMAND_PROFILES = BUILD_ROOT / "packaged_assets" / "device_command_profiles.json"
PACKAGED_RUNTIME_ROOT = BUILD_ROOT / "packaged_assets" / "runtime"
PACKAGED_BUILD_INFO_SOURCE = "resources/runtime/build_info.json"
PACKAGED_FEATURE_FLAGS_SOURCE = "resources/runtime/feature_flags.json"
PACKAGED_BUILD_METADATA_SOURCE = "resources/runtime/build-metadata.json"
PACKAGED_DEVICE_COMMAND_PROFILE_OPERATION = "device.inventory.collect"
RUNTIME_DYNAMIC_IMPORTS = (
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
)
APPROVED_DISTRIBUTIONS_PATH = (
    ROOT / "config" / "pyinstaller-approved-distributions.json"
)
ANALYSIS_TOC = BUILD_ROOT / "NetConsoleBackend" / "Analysis-00.toc"

ALLOWED_DATA = [
    ("src/netconsole", "netconsole"),
    (LOG_POLICY_SOURCE, "netconsole/resources"),
    ("apps/desktop_renderer/dist", "netconsole/assets/desktop_renderer"),
    ("src/netconsole/assets/open_source_notices.json", "netconsole/assets"),
    ("src/netconsole/assets/THIRD_PARTY_COMPONENTS.md", "netconsole/assets"),
    ("src/netconsole/assets/IPOP_v4.1_notice.md", "netconsole/assets"),
    (
        "src/netconsole/assets/licenses/PYINSTALLER_COPYING.txt",
        "netconsole/assets/licenses",
    ),
    (
        "src/netconsole/assets/licenses/PYINSTALLER_HOOKS_CONTRIB_LICENSE.txt",
        "netconsole/assets/licenses",
    ),
    (DEVICE_COMMAND_PROFILES_SOURCE, "netconsole/assets"),
    (DEVICE_COMPATIBILITY_PROFILES_SOURCE, "netconsole/assets"),
    (PACKAGED_BUILD_INFO_SOURCE, "netconsole/assets/runtime"),
    (PACKAGED_FEATURE_FLAGS_SOURCE, "netconsole/assets/runtime"),
    (PACKAGED_BUILD_METADATA_SOURCE, "netconsole/assets/runtime"),
]
_BUILD_METADATA: dict[str, object] | None = None
FORBIDDEN_DATA = [(item, item) for item in FORBIDDEN_DATAS]
EXCLUDE_DIRS = [
    *FORBIDDEN_PROJECT_SOURCES,
    "build",
    "spec",
    "release",
]
EXCLUDE_FILES = {"*.pyc", "*.pyo"}
REQUIRED_TOOL_FILES = (
    Path("resources") / "tools" / "windows-x64" / "fping" / "fping.exe",
    Path("resources") / "tools" / "windows-x64" / "fping" / "cygwin1.dll",
    Path("resources") / "tools" / "windows-x64" / "fping" / "COPYING",
    Path("resources") / "tools" / "windows-x64" / "fping" / "COPYING.LIB",
    Path("resources") / "tools" / "windows-x64" / "fping" / "GPL-3.0.txt",
    Path("resources") / "tools" / "windows-x64" / "fping" / "CYGWIN_LICENSE",
    Path("resources") / "tools" / "windows-x64" / "fping" / "CORRESPONDING_SOURCE.md",
    Path("resources") / "tools" / "windows-x64" / "fping" / "BUILD_RECIPE.md",
    Path("resources") / "tools" / "windows-x64" / "fping" / "CYGWIN_ICMP_COMPAT.patch",
    Path("resources") / "tools" / "windows-x64" / "fping" / "SOURCE_PROVENANCE.json",
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "iperf3.exe",
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "cygcrypto-3.dll",
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "cygwin1.dll",
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "cygz.dll",
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "SOURCE_PROVENANCE.json",
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "CORRESPONDING_SOURCE.md",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "licenses"
    / "AR51AN_APACHE-2.0.txt",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "licenses"
    / "CYGWIN_LGPL-3.0.txt",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "licenses"
    / "CYGWIN_LINKING_EXCEPTION.txt",
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "licenses" / "GPL-3.0.txt",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "licenses"
    / "IPERF3_LICENSE.txt",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "licenses"
    / "OPENSSL_APACHE-2.0.txt",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "licenses"
    / "ZLIB_LICENSE.txt",
)
REQUIRED_TOOL_EXECUTABLES = (
    Path("resources") / "tools" / "windows-x64" / "fping" / "fping.exe",
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "iperf3.exe",
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
    Path("resources") / "tools" / "windows-x64" / "fping" / "fping.exe": (
        "Version 5.5",
        "fping",
    ),
    Path("resources") / "tools" / "windows-x64" / "iperf3" / "iperf3.exe": (
        "iperf 3.21",
    ),
}
IPERF_RELEASE_SHA256 = {
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "iperf3.exe": "4aae5eee2b90c716d93bdc54c530a854596c92ff996859973b9f44e73799294e",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "cygwin1.dll": "0ab76b4724499df54b75b7fa701788f1e77425ce65c8bca0a9f2120598bb8a70",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "cygcrypto-3.dll": "3cfcab214b827485265c21f5c365af5055ee47ca507cc56a1422661288d51ea6",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "iperf3"
    / "cygz.dll": "827576482185c48ed3698454594260ee27ba32180127b8ba28c5ca68a867ce38",
}
FPING_RELEASE_SHA256 = {
    Path("resources")
    / "tools"
    / "windows-x64"
    / "fping"
    / "fping.exe": "9c9ab2f26d3d32818b53ed7b664ec53546fc5cd59f4d953e06f9d3e28673f9d9",
    Path("resources")
    / "tools"
    / "windows-x64"
    / "fping"
    / "cygwin1.dll": "d5562774ec1475bd1dab84c5249b273e60cc53e6aa968981414a4d6a3f8e2bfd",
}
IPERF_LICENSE_SHA256 = {
    "AR51AN_APACHE-2.0.txt": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    "CYGWIN_LGPL-3.0.txt": "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
    "CYGWIN_LINKING_EXCEPTION.txt": "794433752103cf4bbb4a84a1bdb8fbc150abb1762704bb35fecc9f7f820be984",
    "GPL-3.0.txt": "0ae0485a5bd37a63e63603596417e4eb0e653334fa6c7f932ca3a0e85d4af227",
    "IPERF3_LICENSE.txt": "6c6e9abd761ff429c11189cd93bdee5bff7e3591253bd614b253a5f4fd30cbe5",
    "OPENSSL_APACHE-2.0.txt": "7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a",
    "ZLIB_LICENSE.txt": "e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2",
}
FPING_LICENSE_SHA256 = {
    "COPYING": "6051b27e4b4a648f7bc8b329024da53a6e95ce88fcf0ccc259c371a74b741757",
    "COPYING.LIB": "1a45b1d0a8603dfe2cfc644f9dab970b1762f92babe2aac6eb2f5d4572c4a680",
    "GPL-3.0.txt": "0ae0485a5bd37a63e63603596417e4eb0e653334fa6c7f932ca3a0e85d4af227",
    "CYGWIN_LICENSE": "794433752103cf4bbb4a84a1bdb8fbc150abb1762704bb35fecc9f7f820be984",
    "CYGWIN_LICENSE_NOTE.txt": "39872eccdbdb5ed0952e2bf175532227defa3fc97fec69a96a7fef744535fbf4",
}
FPING_COMPLIANCE_SHA256 = {
    "BUILD_RECIPE.md": "e1019b55830d91a97314b26985193b254507b3495f225681cc101288fa1ca1f5",
    "CORRESPONDING_SOURCE.md": "a0ca3f1e13af8ad8ae66ad5c2db7c11faba3b9392ca9c1426856ae476b9f22f3",
    "CYGWIN_ICMP_COMPAT.patch": "f245e88cbc111d4bc3476c1146713cc1462fff5011baf41926f2dfdabb30bf83",
}
IPERF_COMPLIANCE_SHA256 = {
    "CORRESPONDING_SOURCE.md": "faea146cd105ffb781c188e6b9576691cf7f4a37ba033226007b37410669e468",
    "licenses/README.md": "31d120a478c8d5f245b31fba5e74f9cc5960dc801907b9dee370da4157820909",
}
IPERF_RELEASE_ASSET = {
    "name": "iperf-3.21-win64-dynamic-auth.zip",
    "sha256": "0d3ac723df5cc7b2ab1851fe9441c14291c6583b6acf8ef81dabee73c145c2eb",
}
ALLOWED_TOOL_FILES = {
    Path("resources/tools/windows-x64/fping"): frozenset(
        {
            "COPYING",
            "COPYING.LIB",
            "GPL-3.0.txt",
            "BUILD_RECIPE.md",
            "CORRESPONDING_SOURCE.md",
            "CYGWIN_ICMP_COMPAT.patch",
            "cygwin1.dll",
            "CYGWIN_LICENSE",
            "CYGWIN_LICENSE_NOTE.txt",
            "fping.exe",
            "README.md",
            "README.txt",
            "SOURCE_PROVENANCE.json",
            "VERSION.txt",
        }
    ),
    Path("resources/tools/windows-x64/iperf3"): frozenset(
        {
            "cygcrypto-3.dll",
            "cygwin1.dll",
            "cygz.dll",
            "iperf3.exe",
            "README.md",
            "CORRESPONDING_SOURCE.md",
            "SOURCE_PROVENANCE.json",
            "licenses/AR51AN_APACHE-2.0.txt",
            "licenses/CYGWIN_LGPL-3.0.txt",
            "licenses/CYGWIN_LINKING_EXCEPTION.txt",
            "licenses/GPL-3.0.txt",
            "licenses/IPERF3_LICENSE.txt",
            "licenses/OPENSSL_APACHE-2.0.txt",
            "licenses/README.md",
            "licenses/ZLIB_LICENSE.txt",
        }
    ),
}
IMAGE_FILE_MACHINE_AMD64 = 0x8664
VERSION_INFO_FILE = BUILD_ROOT / "version_info.txt"


def scan_import_graph() -> list[str]:
    return sorted(
        set(build_runtime_module_map())
        | set(build_direct_runtime_hidden_imports())
        | set(RUNTIME_DYNAMIC_IMPORTS)
    )


def build_direct_runtime_hidden_imports() -> list[str]:
    """Keep every declared direct runtime distribution reachable in the artifact."""

    direct_distributions = set(runtime_direct_dependency_names(ROOT))
    modules: dict[str, set[str]] = {name: set() for name in direct_distributions}
    for module, raw_owners in metadata.packages_distributions().items():
        if (
            not module
            or module.startswith("__")
            or any(not part.isidentifier() for part in module.split("."))
        ):
            continue
        owners = {canonicalize_name(owner) for owner in raw_owners}
        for owner in owners & direct_distributions:
            try:
                available = importlib.util.find_spec(module) is not None
            except (ImportError, AttributeError, ValueError):
                available = False
            if available:
                modules[owner].add(module)
    missing = sorted(name for name, names in modules.items() if not names)
    if missing:
        raise CleanBuildLockError(
            "运行时直接依赖没有可冻结的顶层模块：" + ", ".join(missing)
        )
    return sorted({module for names in modules.values() for module in names})


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
            for resolved_module, module_file in _resolve_module_with_packages(
                module
            ).items():
                if resolved_module not in module_files:
                    module_files[resolved_module] = module_file
                    pending_sources.append(module_file)
    return dict(sorted(module_files.items()))


def build_runtime_subset_from_import_graph() -> list[Path]:
    return list(build_runtime_module_map().values())


def build_runtime_datas_from_import_graph() -> list[tuple[str, str]]:
    datas: list[tuple[str, str]] = []
    for module_file in build_runtime_subset_from_import_graph():
        relative = module_file.relative_to(SRC_ROOT)
        datas.append((str(module_file), relative.parent.as_posix()))
    changelog = SRC_ROOT / "netconsole" / "docs" / "changelog.md"
    if changelog.is_file():
        datas.append((str(changelog), "netconsole/assets"))
    for source, destination in ALLOWED_DATA:
        if source == DEVICE_COMMAND_PROFILES_SOURCE:
            source_path = write_packaged_device_command_profiles()
        elif source in {
            PACKAGED_BUILD_INFO_SOURCE,
            PACKAGED_FEATURE_FLAGS_SOURCE,
            PACKAGED_BUILD_METADATA_SOURCE,
        }:
            source_path = write_packaged_runtime_feature_policy()[source]
        else:
            source_path = ROOT / source
        if (
            source == "apps/desktop_renderer/dist" and source_path.is_dir()
        ) or source_path.is_file():
            if (str(source_path), destination) in datas:
                continue
            datas.append((str(source_path), destination))
    return datas


def write_packaged_device_command_profiles() -> Path:
    source_path = ROOT / DEVICE_COMMAND_PROFILES_SOURCE
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanBuildLockError("packaged device command profiles cannot be prepared") from exc
    if payload.get("schema_version") != "2026.07.device-command-profiles.v1":
        raise CleanBuildLockError("packaged device command profiles schema_version is unsupported")
    source_profiles = payload.get("profiles")
    if not isinstance(source_profiles, list):
        raise CleanBuildLockError("packaged device command profiles source has invalid profiles")
    profiles = [
        profile
        for profile in source_profiles
        if isinstance(profile, dict)
        and profile.get("operation_id") == PACKAGED_DEVICE_COMMAND_PROFILE_OPERATION
    ]
    if not profiles:
        raise CleanBuildLockError("packaged device command profiles missing device.inventory.collect")
    PACKAGED_DEVICE_COMMAND_PROFILES.parent.mkdir(parents=True, exist_ok=True)
    PACKAGED_DEVICE_COMMAND_PROFILES.write_text(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "profiles": profiles,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return PACKAGED_DEVICE_COMMAND_PROFILES


def write_packaged_runtime_feature_policy() -> dict[str, Path]:
    PACKAGED_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    build_metadata = require_build_metadata()
    payloads = {
        PACKAGED_BUILD_INFO_SOURCE: {
            "edition": "customer",
            "feature_profile": "production",
            "admin_unlock_enabled": False,
        },
        PACKAGED_FEATURE_FLAGS_SOURCE: default_profile("production"),
        PACKAGED_BUILD_METADATA_SOURCE: build_metadata,
    }
    paths: dict[str, Path] = {}
    for source, payload in payloads.items():
        path = PACKAGED_RUNTIME_ROOT / Path(source).name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        paths[source] = path
    return paths


def set_build_metadata(payload: dict[str, object]) -> None:
    global _BUILD_METADATA
    selected = dict(payload)
    validate_build_metadata(selected, release=False)
    _BUILD_METADATA = selected


def require_build_metadata() -> dict[str, object]:
    global _BUILD_METADATA
    if _BUILD_METADATA is not None:
        return dict(_BUILD_METADATA)
    encoded = os.environ.get(BUILD_METADATA_ENV, "")
    if encoded:
        _BUILD_METADATA = decode_build_metadata(encoded)
        return dict(_BUILD_METADATA)
    try:
        _BUILD_METADATA = collect_build_metadata(
            ROOT,
            app_version=APP_VERSION,
            release=False,
        )
        return dict(_BUILD_METADATA)
    except BuildMetadataError as exc:
        raise CleanBuildLockError(str(exc)) from exc


def build_non_runtime_module_excludes() -> list[str]:
    """Return top-level modules owned only by ambient non-runtime distributions."""

    runtime_distributions = {
        canonicalize_name(name) for name in runtime_dependency_versions(ROOT)
    }
    excluded: set[str] = set()
    for module, raw_owners in metadata.packages_distributions().items():
        if module == "netconsole":
            continue
        owners = {canonicalize_name(owner) for owner in raw_owners}
        if owners and owners.isdisjoint(runtime_distributions):
            excluded.add(module)
    for distribution in metadata.distributions():
        raw_name = str(distribution.metadata.get("Name") or "")
        if not raw_name or canonicalize_name(raw_name) in runtime_distributions:
            continue
        for relative in distribution.files or ():
            filename = Path(str(relative)).name
            module = filename.split(".", 1)[0]
            if module == "__init__" or not module.isidentifier():
                continue
            try:
                spec = importlib.util.find_spec(module)
                origin = Path(spec.origin).resolve() if spec and spec.origin else None
                source = Path(distribution.locate_file(relative)).resolve()
            except (ImportError, OSError, TypeError, ValueError):
                continue
            if origin == source:
                excluded.add(module)
    return sorted(excluded)


def _imports_from_source(source: Path) -> set[str]:
    runtime_modules: set[str] = set()
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return runtime_modules
    current_module = _source_to_module(source)
    current_package = (
        current_module
        if source.name == "__init__.py"
        else current_module.rpartition(".")[0]
    )
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


def _resolve_import_from_module(
    node: ast.ImportFrom, current_package: str
) -> str | None:
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
    module_path = SRC_ROOT.joinpath(*relative_parts)
    package_init = module_path / "__init__.py"
    if package_init.exists():
        return package_init
    file_path = module_path.with_suffix(".py")
    if file_path.exists():
        return file_path
    return None


def _source_to_module(source: Path) -> str:
    if source.resolve() == ENTRY_FILE.resolve():
        return "main"
    relative = source.resolve().relative_to(SRC_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def prepare_runtime() -> None:
    if not CLEAN_BUILD:
        raise CleanBuildLockError("Clean Build Mode is required for release packaging")
    ensure_desktop_renderer()
    environment_result = check_python_environment()
    for message in environment_result.messages:
        print(message)
    if not environment_result.ok:
        raise CleanBuildLockError(
            "Python environment contains forbidden Qt dependencies"
        )
    clean_tool_cache_artifacts()
    validate_project_safety(ALLOWED_DATA)
    validate_allowed_runtime(ALLOWED_DATA)
    validate_tool_sources()


def ensure_desktop_renderer() -> None:
    dist_index = ROOT / "apps" / "desktop_renderer" / "dist" / "index.html"
    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
    if pnpm is None:
        raise CleanBuildLockError("未找到 pnpm，无法构建 Desktop Renderer。")
    renderer_dir = ROOT / "apps" / "desktop_renderer"
    if not (renderer_dir / "node_modules").is_dir():
        raise CleanBuildLockError(
            "apps/desktop_renderer/node_modules 不存在，请先执行 pnpm install --frozen-lockfile。"
        )
    env = os.environ.copy()
    build_metadata = require_build_metadata()
    env[BUILD_METADATA_ENV] = encode_build_metadata(build_metadata)
    subprocess.run([pnpm, "build"], cwd=renderer_dir, check=True, env=env)
    try:
        validate_web_frontend_meta(
            dist_index.parent,
            expected_version=APP_VERSION,
            expected_commit=str(build_metadata["git_commit_full"]),
            expected_build_time=str(build_metadata["build_time_utc"]),
            expected_dirty=bool(build_metadata["build_dirty"]),
        )
    except ValueError as exc:
        raise CleanBuildLockError(str(exc)) from exc


def clean_tool_cache_artifacts() -> None:
    tools_root = ROOT / "resources" / "tools"
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
    runtime_excludes = build_non_runtime_module_excludes()
    vc_runtime_binaries = collect_vc_runtime_dlls()
    spec_text = f"""# -*- mode: python ; coding: utf-8 -*-
# Generated by clean_build_spec.py. Do not add project/docs/tests or "." to datas.

CLEAN_BUILD = {CLEAN_BUILD!r}
ALLOWED_DATA = {ALLOWED_DATA!r}
EXCLUDE_DIRS = {EXCLUDE_DIRS!r}
RUNTIME_IMPORTS = {runtime_imports!r}
RUNTIME_DATAS = {runtime_datas!r}
RUNTIME_EXCLUDES = {runtime_excludes!r}
VC_RUNTIME_BINARIES = {vc_runtime_binaries!r}

a = Analysis(
    [{str(ENTRY_FILE)!r}],
    pathex=[{str(SRC_ROOT)!r}],
    binaries=VC_RUNTIME_BINARIES,
    datas=RUNTIME_DATAS,
    hiddenimports=RUNTIME_IMPORTS,
    hookspath=[],
    hooksconfig={{'matplotlib': {{'backends': 'Agg'}}}},
    runtime_hooks=[],
    excludes=sorted(set(['tests', 'docs', 'project', '__pycache__', *RUNTIME_EXCLUDES])),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NetConsoleBackend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name='NetConsoleBackend',
)
"""
    validate_project_safety(ALLOWED_DATA, spec_text)
    SPEC_FILE.write_text(spec_text, encoding="utf-8")
    return SPEC_FILE


def write_version_info_file() -> Path:
    from netconsole.core.version import APP_VERSION
    from scripts.build.release import render_version_info

    VERSION_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_INFO_FILE.write_text(render_version_info(APP_VERSION), encoding="utf-8")
    return VERSION_INFO_FILE


def validate_dist() -> None:
    app_dist = DIST_ROOT / "NetConsoleBackend"
    validate_dist_output(app_dist)
    validate_packaged_runtime_feature_policy(app_dist)
    check_packaged_tools(app_dist)
    validate_packaged_web_frontend(app_dist)
    try:
        approved_distributions = load_packaged_distribution_approval()
        actual_distributions = collect_pyinstaller_distributions(
            ANALYSIS_TOC,
            app_dist,
        )
        write_inventory(
            app_dist
            / "_internal"
            / "netconsole"
            / "assets"
            / "pyinstaller-artifact-inventory.json",
            actual_distributions,
            executable=app_dist / "NetConsoleBackend.exe",
            expected=approved_distributions,
        )
        write_runtime_sbom(
            app_dist / "_internal" / "netconsole" / "assets" / "sbom.cdx.json",
            packaged_python_components=actual_distributions,
        )
    except (ArtifactInventoryError, OSError, ValueError, RuntimeError) as exc:
        raise CleanBuildLockError(f"无法生成制品清单或运行时 SBOM：{exc}") from exc
    runtime_result = check_runtime_deps(app_dist, require_compliance_artifacts=True)
    for message in runtime_result.messages:
        print(message)
    if not runtime_result.ok:
        raise CleanBuildLockError("packaged runtime dependency check failed")


def validate_packaged_runtime_feature_policy(app_dist: Path) -> None:
    runtime = app_dist / "_internal" / "netconsole" / "assets" / "runtime"
    try:
        build_info = json.loads((runtime / "build_info.json").read_text(encoding="utf-8"))
        feature_flags = json.loads((runtime / "feature_flags.json").read_text(encoding="utf-8"))
        build_metadata = json.loads((runtime / "build-metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanBuildLockError("packaged runtime feature policy is missing or invalid") from exc
    if build_info.get("edition") != "customer" or build_info.get("feature_profile") != "production":
        raise CleanBuildLockError("packaged build_info must use customer/production")
    if feature_flags.get("profile") != "production" or not isinstance(feature_flags.get("features"), dict):
        raise CleanBuildLockError("packaged feature_flags must contain the production baseline")
    try:
        validate_build_metadata(
            build_metadata,
            release=str(build_metadata.get("build_source") or "") == "git-release",
        )
    except BuildMetadataError as exc:
        raise CleanBuildLockError(str(exc)) from exc
    if _BUILD_METADATA is None and not os.environ.get(BUILD_METADATA_ENV, ""):
        try:
            current_source = collect_build_metadata(
                ROOT,
                app_version=APP_VERSION,
                release=str(build_metadata.get("build_source") or "") == "git-release",
                build_time_utc=str(build_metadata.get("build_time_utc") or ""),
            )
        except BuildMetadataError as exc:
            raise CleanBuildLockError(str(exc)) from exc
        if build_metadata != current_source:
            raise CleanBuildLockError(
                "packaged build metadata no longer matches the current Git source"
            )
        set_build_metadata(build_metadata)
    expected = require_build_metadata()
    if build_metadata != expected:
        raise CleanBuildLockError("packaged build metadata differs from build invocation")
    if (runtime / "feature_flags.local.json").exists() or (app_dist / "runtime" / "feature_flags.local.json").exists():
        raise CleanBuildLockError("packaged runtime must not contain a local feature override")


def load_packaged_distribution_approval() -> dict[str, str]:
    approved = load_approved_distributions(
        APPROVED_DISTRIBUTIONS_PATH,
        platform="windows-x64",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    allowed = required_python_component_versions(ROOT)
    unapproved = sorted(
        name for name, version in approved.items() if allowed.get(name) != version
    )
    if unapproved:
        raise ArtifactInventoryError(
            "Approved artifact contains components outside the locked runtime: "
            + ", ".join(unapproved)
        )
    required = set(runtime_direct_dependency_names(ROOT)) | {
        canonicalize_name(name) for name in PACKAGED_PYTHON_DISTRIBUTIONS
    }
    missing = sorted(required - set(approved))
    if missing:
        raise ArtifactInventoryError(
            "Approved artifact omits direct or packaged components: "
            + ", ".join(missing)
        )
    return approved


def validate_packaged_web_frontend(app_dist: Path) -> None:
    build_metadata = require_build_metadata()
    try:
        validate_web_frontend_meta(
            app_dist / "_internal" / "netconsole" / "assets" / "desktop_renderer",
            expected_version=APP_VERSION,
            expected_commit=str(build_metadata["git_commit_full"]),
            expected_build_time=str(build_metadata["build_time_utc"]),
            expected_dirty=bool(build_metadata["build_dirty"]),
        )
    except ValueError as exc:
        raise CleanBuildLockError(str(exc)) from exc


def validate_tool_sources() -> None:
    missing = [
        path.as_posix() for path in REQUIRED_TOOL_FILES if not (ROOT / path).is_file()
    ]
    if missing:
        raise CleanBuildLockError(
            f"required runtime tool is missing: {', '.join(missing)}"
        )
    mismatched = _hash_mismatches({**IPERF_RELEASE_SHA256, **FPING_RELEASE_SHA256})
    if mismatched:
        raise CleanBuildLockError(
            "runtime tool hash mismatch: " + ", ".join(mismatched)
        )
    _validate_allowed_tool_files()
    _validate_iperf_provenance()
    _validate_fping_provenance()
    if not (ROOT / "resources" / "tools").is_dir():
        raise CleanBuildLockError("required resources/tools directory is missing")


def _validate_exact_keys(value: object, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise CleanBuildLockError(
            f"{label} properties do not match the approved manifest"
        )


def _validate_exact_mapping(
    value: object, expected: dict[str, object], label: str
) -> None:
    if not _deep_strict_equal(value, expected):
        raise CleanBuildLockError(f"{label} does not match the approved manifest")


def _validate_exact_named_entries(
    value: object,
    expected: dict[str, dict[str, object]],
    label: str,
) -> None:
    if not isinstance(value, list) or len(value) != len(expected):
        raise CleanBuildLockError(f"{label} is not the exact approved set")
    actual: dict[str, dict[str, object]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise CleanBuildLockError(f"{label} contains a non-object entry")
        name = item.get("name")
        if not isinstance(name, str) or not name or name in actual:
            raise CleanBuildLockError(f"{label} contains a missing or duplicate name")
        actual[name] = item
    if not _deep_strict_equal(actual, expected):
        raise CleanBuildLockError(f"{label} does not match the approved manifest")


def _deep_strict_equal(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _deep_strict_equal(actual[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _deep_strict_equal(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def _validate_iperf_provenance() -> None:
    path = (
        ROOT
        / "resources"
        / "tools"
        / "windows-x64"
        / "iperf3"
        / "SOURCE_PROVENANCE.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanBuildLockError(f"invalid iPerf3 provenance: {exc}") from exc
    _validate_exact_keys(
        payload,
        {
            "schema_version",
            "component",
            "version",
            "platform",
            "verified_at",
            "distribution",
            "files",
            "license_files",
            "upstream_sources",
            "compliance_files",
            "corresponding_source_notice",
            "external_distribution_source_policy",
            "distributor_license_file",
        },
        "iPerf3 provenance root",
    )
    if (
        payload.get("schema_version") != "netconsole.tool-provenance.v1"
        or payload.get("component") != "iperf3-win64-dynamic-auth"
        or payload.get("version") != "3.21"
        or payload.get("platform") != "windows-x64-cygwin"
        or payload.get("verified_at") != "2026-07-18"
        or payload.get("corresponding_source_notice") != "CORRESPONDING_SOURCE.md"
        or payload.get("external_distribution_source_policy")
        != "publish the exact corresponding source archive beside the binary release or provide a valid written offer"
        or payload.get("distributor_license_file") != "licenses/AR51AN_APACHE-2.0.txt"
    ):
        raise CleanBuildLockError(
            "iPerf3 provenance does not identify the approved 3.21 dynamic-auth asset"
        )
    _validate_exact_mapping(
        payload.get("distribution"),
        {
            "repository": "https://github.com/ar51an/iperf3-win-builds",
            "tag": "3.21",
            "tag_commit": "7a24a0a352b6e177993e3b6375e7d38bc8f913e8",
            "release_id": 307349802,
            "release_url": "https://github.com/ar51an/iperf3-win-builds/releases/tag/3.21",
            "asset_name": IPERF_RELEASE_ASSET["name"],
            "asset_id": 392879715,
            "asset_url": "https://github.com/ar51an/iperf3-win-builds/releases/download/3.21/iperf-3.21-win64-dynamic-auth.zip",
            "published_at": "2026-04-10T01:44:57Z",
            "sha256": IPERF_RELEASE_ASSET["sha256"],
        },
        "iPerf3 distribution provenance",
    )
    _validate_exact_named_entries(
        payload.get("files"),
        {
            "iperf3.exe": {
                "name": "iperf3.exe",
                "version": "3.21",
                "sha256": IPERF_RELEASE_SHA256[
                    Path("resources/tools/windows-x64/iperf3/iperf3.exe")
                ],
            },
            "cygwin1.dll": {
                "name": "cygwin1.dll",
                "version": "3.6.7-1",
                "sha256": IPERF_RELEASE_SHA256[
                    Path("resources/tools/windows-x64/iperf3/cygwin1.dll")
                ],
            },
            "cygcrypto-3.dll": {
                "name": "cygcrypto-3.dll",
                "version": "3.0.19",
                "sha256": IPERF_RELEASE_SHA256[
                    Path("resources/tools/windows-x64/iperf3/cygcrypto-3.dll")
                ],
            },
            "cygz.dll": {
                "name": "cygz.dll",
                "version": "1.3.2",
                "sha256": IPERF_RELEASE_SHA256[
                    Path("resources/tools/windows-x64/iperf3/cygz.dll")
                ],
            },
        },
        "iPerf3 provenance files",
    )
    _validate_exact_named_entries(
        payload.get("license_files"),
        {
            name: {"name": name, "sha256": sha256}
            for name, sha256 in IPERF_LICENSE_SHA256.items()
        },
        "iPerf3 provenance license files",
    )
    license_root = path.parent / "licenses"
    license_mismatches = _named_hash_mismatches(license_root, IPERF_LICENSE_SHA256)
    if license_mismatches:
        raise CleanBuildLockError(
            "iPerf3 license hash mismatch: " + ", ".join(license_mismatches)
        )
    _validate_exact_named_entries(
        payload.get("compliance_files"),
        {
            name: {"name": name, "sha256": sha256}
            for name, sha256 in IPERF_COMPLIANCE_SHA256.items()
        },
        "iPerf3 provenance compliance files",
    )
    compliance_mismatches = _named_hash_mismatches(path.parent, IPERF_COMPLIANCE_SHA256)
    if compliance_mismatches:
        raise CleanBuildLockError(
            "iPerf3 corresponding-source material hash mismatch: "
            + ", ".join(compliance_mismatches)
        )
    _validate_exact_named_entries(
        payload.get("upstream_sources"),
        {
            "iperf3": {
                "name": "iperf3",
                "version": "3.21",
                "repository": "https://github.com/esnet/iperf",
                "tag": "3.21",
                "tag_object": "ec66336d2c152bf964f671e9e20a11de05edb239",
                "tag_commit": "d39cf41526626b4e5a130f115d931cd6cbdffc19",
                "license_file": "licenses/IPERF3_LICENSE.txt",
            },
            "Cygwin Runtime": {
                "name": "Cygwin Runtime",
                "version": "3.6.7-1",
                "source_package": "cygwin-3.6.7-1-src",
                "source_index": "https://cygwin.com/packages/summary/cygwin-src.html",
                "source_contents": "https://cygwin.com/packages/src/cygwin-src/cygwin-3.6.7-1-src",
                "source_archive_path": "src/release/cygwin/cygwin-3.6.7-1-src.tar.xz",
                "source_archive_size": 9309160,
                "source_archive_sha512": "82a190c3516511af7d1305e1bcd4aa0177c1fb584b6468a887a9119565bccd88630b2a3b826d902983a83adefb11545346dcf27616186304d6c66879e1647335",
                "license_file": "licenses/CYGWIN_LGPL-3.0.txt",
                "gpl_file": "licenses/GPL-3.0.txt",
                "exception_file": "licenses/CYGWIN_LINKING_EXCEPTION.txt",
            },
            "OpenSSL Cygwin Runtime": {
                "name": "OpenSSL Cygwin Runtime",
                "version": "3.0.19-1",
                "source_index": "https://cygwin.com/packages/summary/openssl-src.html",
                "license_file": "licenses/OPENSSL_APACHE-2.0.txt",
            },
            "zlib Cygwin Runtime": {
                "name": "zlib Cygwin Runtime",
                "version": "1.3.2-1",
                "source_index": "https://cygwin.com/packages/summary/zlib-src.html",
                "license_file": "licenses/ZLIB_LICENSE.txt",
            },
        },
        "iPerf3 provenance upstream sources",
    )


def _validate_fping_provenance() -> None:
    path = (
        ROOT
        / "resources"
        / "tools"
        / "windows-x64"
        / "fping"
        / "SOURCE_PROVENANCE.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanBuildLockError(f"invalid fping provenance: {exc}") from exc
    _validate_exact_keys(
        payload,
        {
            "schema_version",
            "component",
            "version",
            "platform",
            "verified_at",
            "build",
            "files",
            "license_files",
            "compliance_files",
            "upstream_sources",
            "corresponding_source_notice",
            "external_distribution_source_policy",
        },
        "fping provenance root",
    )
    if (
        payload.get("schema_version") != "netconsole.tool-provenance.v1"
        or payload.get("component") != "fping-windows-x64-cygwin"
        or payload.get("version") != "5.5"
        or payload.get("platform") != "windows-x64-cygwin"
        or payload.get("verified_at") != "2026-07-18"
        or payload.get("corresponding_source_notice") != "CORRESPONDING_SOURCE.md"
        or payload.get("external_distribution_source_policy")
        != "publish the exact corresponding source archive beside the binary release or provide a valid written offer"
    ):
        raise CleanBuildLockError(
            "fping provenance does not identify the approved 5.5 Cygwin build"
        )
    _validate_exact_mapping(
        payload.get("build"),
        {
            "method": "local Cygwin x86_64 build",
            "built_at": "2026-06-27T00:28:00+08:00",
            "git_describe_at_build": "v5.5-dirty",
            "source_state": "upstream v5.5 plus archived Cygwin ICMP compatibility patch",
            "configure_args": ["--disable-ipv6", "--enable-safe-limits"],
            "patch_file": "CYGWIN_ICMP_COMPAT.patch",
            "patch_sha256": FPING_COMPLIANCE_SHA256["CYGWIN_ICMP_COMPAT.patch"],
            "recipe_file": "BUILD_RECIPE.md",
            "recipe_sha256": FPING_COMPLIANCE_SHA256["BUILD_RECIPE.md"],
            "network_required_during_product_packaging": False,
        },
        "fping build provenance",
    )
    _validate_exact_named_entries(
        payload.get("files"),
        {
            "fping.exe": {
                "name": "fping.exe",
                "version": "5.5",
                "sha256": FPING_RELEASE_SHA256[
                    Path("resources/tools/windows-x64/fping/fping.exe")
                ],
            },
            "cygwin1.dll": {
                "name": "cygwin1.dll",
                "version": "3.6.9-1",
                "sha256": FPING_RELEASE_SHA256[
                    Path("resources/tools/windows-x64/fping/cygwin1.dll")
                ],
            },
        },
        "fping provenance files",
    )
    _validate_exact_named_entries(
        payload.get("license_files"),
        {
            name: {"name": name, "sha256": sha256}
            for name, sha256 in FPING_LICENSE_SHA256.items()
        },
        "fping provenance license files",
    )
    license_mismatches = _named_hash_mismatches(path.parent, FPING_LICENSE_SHA256)
    if license_mismatches:
        raise CleanBuildLockError(
            "fping license hash mismatch: " + ", ".join(license_mismatches)
        )
    _validate_exact_named_entries(
        payload.get("compliance_files"),
        {
            name: {"name": name, "sha256": sha256}
            for name, sha256 in FPING_COMPLIANCE_SHA256.items()
        },
        "fping provenance compliance files",
    )
    compliance_mismatches = _named_hash_mismatches(path.parent, FPING_COMPLIANCE_SHA256)
    if compliance_mismatches:
        raise CleanBuildLockError(
            "fping corresponding-source material hash mismatch: "
            + ", ".join(compliance_mismatches)
        )
    _validate_exact_named_entries(
        payload.get("upstream_sources"),
        {
            "fping": {
                "name": "fping",
                "version": "5.5",
                "repository": "https://github.com/schweikert/fping",
                "tag": "v5.5",
                "tag_commit": "06f9481ef3cf79c2aa973718366fb13927777689",
            },
            "Cygwin Runtime": {
                "name": "Cygwin Runtime",
                "version": "3.6.9-1",
                "source_package": "cygwin-3.6.9-1-src",
                "source_index": "https://cygwin.com/packages/summary/cygwin-src.html",
                "source_contents": "https://cygwin.com/packages/src/cygwin-src/cygwin-3.6.9-1-src",
                "source_archive_path": "src/release/cygwin/cygwin-3.6.9-1-src.tar.xz",
                "source_archive_size": 9312760,
                "source_archive_sha512": "771ab64fff17323a32b7cb56140c974d446899a5d4eb5b76115e14cd8fe2e4108be5f30112e441def0f86666d37ab35ba5fb31950910d91ffc12ba69e0934f6e",
                "repository": "https://cygwin.com/git/newlib-cygwin.git",
                "tag": "cygwin-3.6.9",
                "tag_object": "f802d89cdc3fbbfbb47f5a6b3a4e27b7a2363795",
                "tag_commit": "daabea98682f3f4bef0044829a8d24226135bb71",
            },
        },
        "fping provenance upstream sources",
    )


def _hash_mismatches(expected_files: dict[Path, str]) -> list[str]:
    return [
        relative.as_posix()
        for relative, expected in expected_files.items()
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected
    ]


def _named_hash_mismatches(root: Path, expected_files: dict[str, str]) -> list[str]:
    return [
        name
        for name, expected in expected_files.items()
        if not (root / name).is_file()
        or hashlib.sha256((root / name).read_bytes()).hexdigest() != expected
    ]


def _validate_allowed_tool_files() -> None:
    for relative_root, allowed in ALLOWED_TOOL_FILES.items():
        tool_root = ROOT / relative_root
        actual: set[str] = set()
        for directory, _dir_names, file_names in os.walk(tool_root):
            base = Path(directory)
            actual.update(
                (base / name).relative_to(tool_root).as_posix() for name in file_names
            )
        unexpected = sorted(actual - allowed)
        missing = sorted(allowed - actual)
        if unexpected or missing:
            raise CleanBuildLockError(
                f"versioned runtime tool directory {relative_root.as_posix()} is not exact; "
                f"unexpected: {', '.join(unexpected) or '<none>'}; "
                f"missing: {', '.join(missing) or '<none>'}"
            )


def collect_vc_runtime_dlls(
    search_roots: list[Path] | None = None,
    *,
    required: bool = True,
) -> list[tuple[str, str]]:
    roots = search_roots or _default_vc_runtime_search_roots()
    selected_root: Path | None = None
    selected_files: list[Path] = []
    best_missing = list(REQUIRED_VC_RUNTIME_DLLS)
    for root in roots:
        files = [root / dll_name for dll_name in REQUIRED_VC_RUNTIME_DLLS]
        missing = [path.name for path in files if not path.is_file()]
        if len(missing) < len(best_missing):
            best_missing = missing
        if all(path.is_file() for path in files):
            selected_root = root
            selected_files = files
            break
    if selected_root is None and required:
        raise CleanBuildLockError(
            "required VC++ x64 runtime DLL set is incomplete in every search root. "
            f"Missing from the closest root: {', '.join(best_missing)}. "
            "Install Visual C++ 2015-2022 Redistributable x64 on the build machine "
            "or provide one complete app-local x64 runtime set."
        )
    if selected_root is None:
        return []
    wrong_machine = [
        path.name
        for path in selected_files
        if _read_pe_machine(path) != IMAGE_FILE_MACHINE_AMD64
    ]
    if wrong_machine:
        raise CleanBuildLockError(
            "VC++ runtime DLL is not Windows x64 (AMD64): " + ", ".join(wrong_machine)
        )
    found = [(str(path), ".") for path in selected_files]
    for dll_path, _target in found:
        print(f"[OK] VC runtime included: {Path(dll_path).name}")
    return found


def _default_vc_runtime_search_roots() -> list[Path]:
    candidates = [
        Path(sys.executable).resolve().parent,
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
    ]
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        candidates.append(Path(windir) / "System32")
    program_files = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    for base in program_files:
        if base:
            candidates.extend(
                Path(base).glob(
                    "Microsoft Visual Studio/*/*/VC/Redist/MSVC/*/x64/Microsoft.VC*.CRT"
                )
            )
            candidates.extend(
                Path(base).glob("Microsoft Visual C++ Redistributable*/**")
            )
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


def _read_pe_machine(path: Path) -> int:
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("missing MZ header")
            stream.seek(0x3C)
            pe_offset_bytes = stream.read(4)
            if len(pe_offset_bytes) != 4:
                raise ValueError("truncated DOS header")
            pe_offset = int.from_bytes(pe_offset_bytes, "little")
            stream.seek(pe_offset)
            if stream.read(4) != b"PE\x00\x00":
                raise ValueError("missing PE signature")
            machine_bytes = stream.read(2)
            if len(machine_bytes) != 2:
                raise ValueError("truncated COFF header")
            return int.from_bytes(machine_bytes, "little")
    except (OSError, ValueError) as exc:
        raise CleanBuildLockError(
            f"invalid VC++ runtime PE file {path}: {exc}"
        ) from exc


def check_packaged_tools(
    app_dist: Path | None = None, *, run_version_check: bool = True
) -> None:
    app_dist = Path(app_dist or DIST_ROOT / "NetConsoleBackend")
    if run_version_check and _same_path(app_dist, DIST_ROOT / "NetConsoleBackend"):
        source_root = ROOT / "resources"
        source_files = sorted(
            path.relative_to(source_root)
            for tool_dir in (
                ROOT / "resources" / "tools" / "windows-x64" / "fping",
                ROOT / "resources" / "tools" / "windows-x64" / "iperf3",
            )
            for path in tool_dir.glob("**/*")
            if path.is_file()
        )
        missing_packaged = [
            relative for relative in source_files if not (app_dist / relative).is_file()
        ]
        if missing_packaged:
            raise CleanBuildLockError(
                "packaged tools directory is incomplete: "
                + ", ".join(relative.as_posix() for relative in missing_packaged)
            )
    for relative in REQUIRED_TOOL_FILES:
        packaged_relative = relative.relative_to(Path("resources"))
        packaged = app_dist / packaged_relative
        if not packaged.is_file():
            raise CleanBuildLockError(f"packaged runtime tool is missing: {packaged}")
        print(f"[OK] {packaged_relative.as_posix()} included")
        if run_version_check and relative in REQUIRED_TOOL_EXECUTABLES:
            _check_tool_version(packaged, relative)


def _check_tool_version(tool_path: Path, relative: Path) -> None:
    try:
        completed = subprocess.run(
            [str(tool_path), "-v"],
            cwd=tool_path.parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        raise CleanBuildLockError(
            f"packaged runtime tool version check failed: {relative.as_posix()}: {exc}"
        ) from exc
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    markers = TOOL_VERSION_MARKERS[relative]
    if not any(marker in output for marker in markers):
        raise CleanBuildLockError(
            f"packaged runtime tool version output is invalid: {relative.as_posix()}"
        )
    first_line = next(
        (line.strip() for line in output.splitlines() if line.strip()),
        "version detected",
    )
    print(f"[OK] {relative.as_posix()} version: {first_line}")


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _is_excluded_tool_artifact(path: Path) -> bool:
    relative_parts = path.relative_to(ROOT / "resources" / "tools").parts
    if "ipop" in {part.casefold() for part in relative_parts}:
        return True
    if path.suffix.casefold() == ".py":
        return True
    if any(part == "__pycache__" for part in relative_parts):
        return True
    return any(path.match(pattern) for pattern in EXCLUDE_FILES)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and validate the Qt-free NetConsole Backend bundle"
    )
    parser.add_argument(
        "--prepare", action="store_true", help="validate runtime-only graph"
    )
    parser.add_argument(
        "--write-spec",
        action="store_true",
        help="write dist/_build/pyinstaller/spec/NetConsoleBackend.spec",
    )
    parser.add_argument(
        "--validate", action="store_true", help="validate existing dist output"
    )
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
