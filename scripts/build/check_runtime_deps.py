from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path
from typing import Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from scripts.build.generate_sbom import (
    PACKAGED_PYTHON_LICENSES,
    validate_notice_file,
    validate_sbom,
)
from scripts.build.pyinstaller_artifact_inventory import (
    ArtifactInventoryError,
    load_approved_distributions,
    load_inventory,
)
from scripts.build.python_runtime_contract import (
    assert_current_python_runtime,
    load_python_runtime_version,
)


APP_EXE = "NetConsoleBackend.exe"
INTERNAL_DIR = "_internal"
REQUIRED_VC_RUNTIME_DLLS = (
    "VCRUNTIME140.dll",
    "VCRUNTIME140_1.dll",
    "MSVCP140.dll",
    "CONCRT140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
)
REQUIRED_TOOLS = (
    Path("tools") / "windows-x64" / "fping" / "fping.exe",
    Path("tools") / "windows-x64" / "fping" / "cygwin1.dll",
    Path("tools") / "windows-x64" / "fping" / "COPYING",
    Path("tools") / "windows-x64" / "fping" / "COPYING.LIB",
    Path("tools") / "windows-x64" / "fping" / "GPL-3.0.txt",
    Path("tools") / "windows-x64" / "fping" / "CYGWIN_LICENSE",
    Path("tools") / "windows-x64" / "fping" / "BUILD_RECIPE.md",
    Path("tools") / "windows-x64" / "fping" / "CORRESPONDING_SOURCE.md",
    Path("tools") / "windows-x64" / "fping" / "CYGWIN_ICMP_COMPAT.patch",
    Path("tools") / "windows-x64" / "fping" / "SOURCE_PROVENANCE.json",
    Path("tools") / "windows-x64" / "iperf3" / "iperf3.exe",
    Path("tools") / "windows-x64" / "iperf3" / "cygwin1.dll",
    Path("tools") / "windows-x64" / "iperf3" / "cygcrypto-3.dll",
    Path("tools") / "windows-x64" / "iperf3" / "cygz.dll",
    Path("tools") / "windows-x64" / "iperf3" / "SOURCE_PROVENANCE.json",
    Path("tools") / "windows-x64" / "iperf3" / "CORRESPONDING_SOURCE.md",
    Path("tools") / "windows-x64" / "iperf3" / "licenses" / "AR51AN_APACHE-2.0.txt",
    Path("tools") / "windows-x64" / "iperf3" / "licenses" / "CYGWIN_LGPL-3.0.txt",
    Path("tools")
    / "windows-x64"
    / "iperf3"
    / "licenses"
    / "CYGWIN_LINKING_EXCEPTION.txt",
    Path("tools") / "windows-x64" / "iperf3" / "licenses" / "GPL-3.0.txt",
    Path("tools") / "windows-x64" / "iperf3" / "licenses" / "IPERF3_LICENSE.txt",
    Path("tools") / "windows-x64" / "iperf3" / "licenses" / "OPENSSL_APACHE-2.0.txt",
    Path("tools") / "windows-x64" / "iperf3" / "licenses" / "ZLIB_LICENSE.txt",
)
FORBIDDEN_QT_PACKAGE_PREFIXES = (
    "pyside2",
    "pyside6",
    "pyqt5",
    "pyqt6",
    "shiboken2",
    "shiboken6",
    "qfluentwidgets",
    "pyqt-fluent-widgets",
    "pyqt6-fluent-widgets",
    "pyside2-fluent-widgets",
    "pyside6-fluent-widgets",
    "sip",
)
FORBIDDEN_QT_IMPORTS = (
    "PySide2",
    "PySide6",
    "PyQt5",
    "PyQt6",
    "shiboken2",
    "shiboken6",
    "qfluentwidgets",
    "sip",
)
FORBIDDEN_QT_BASENAMES = frozenset(
    {
        "qwindows.dll",
        "qwindowsd.dll",
        "qminimal.dll",
        "qminimald.dll",
        "qoffscreen.dll",
        "qoffscreend.dll",
        "qgif.dll",
        "qgifd.dll",
        "qico.dll",
        "qicod.dll",
        "qjpeg.dll",
        "qjpegd.dll",
        "qsvg.dll",
        "qsvgd.dll",
        "qsvgicon.dll",
        "qsvgicond.dll",
        "qtga.dll",
        "qtgad.dll",
        "qtiff.dll",
        "qtiffd.dll",
        "qwbmp.dll",
        "qwbmpd.dll",
        "qwebp.dll",
        "qwebpd.dll",
        "qtwebengineprocess.exe",
        "qt.conf",
        "sip.pyd",
        "sip.dll",
        "sip.so",
    }
)
QT_LIBRARY_PATTERN = re.compile(
    r"^(?:lib)?qt[56][a-z0-9_.-]*\.(?:dll|pyd|so|dylib)$", re.IGNORECASE
)
QT_PYTHON_EXTENSION_PATTERN = re.compile(
    r"^qt(?:core|gui|widgets|network|qml|quick|svg|webengine|webchannel|websockets|opengl|printsupport)\.(?:pyd|so)$",
    re.IGNORECASE,
)
QT_TRANSLATION_PATTERN = re.compile(
    r"^qt(?:base|declarative|quickcontrols|webengine)?_[a-z0-9_-]+\.qm$", re.IGNORECASE
)
COMPLIANCE_FILES = (
    Path("_internal") / "netconsole" / "assets" / "open_source_notices.json",
    Path("_internal") / "netconsole" / "assets" / "THIRD_PARTY_COMPONENTS.md",
    Path("_internal") / "netconsole" / "assets" / "sbom.cdx.json",
    Path("_internal") / "netconsole" / "assets" / "pyinstaller-artifact-inventory.json",
    Path("_internal")
    / "netconsole"
    / "assets"
    / "licenses"
    / "PYINSTALLER_COPYING.txt",
    Path("_internal")
    / "netconsole"
    / "assets"
    / "licenses"
    / "PYINSTALLER_HOOKS_CONTRIB_LICENSE.txt",
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimeCheckResult:
    ok: bool
    messages: tuple[str, ...]


def check_runtime_deps(
    app_dir: Path | str, *, require_compliance_artifacts: bool = False
) -> RuntimeCheckResult:
    app_dir = Path(app_dir)
    messages: list[str] = []
    ok = True

    def require(condition: bool, ok_message: str, fail_message: str) -> None:
        nonlocal ok
        if condition:
            messages.append(f"[OK] {ok_message}")
        else:
            ok = False
            messages.append(f"[ERROR] {fail_message}")

    internal_dir = app_dir / INTERNAL_DIR
    require((app_dir / APP_EXE).is_file(), f"{APP_EXE} found", f"{APP_EXE} missing")
    require(
        internal_dir.is_dir(),
        "_internal found",
        "Backend 发布目录不完整：缺少 _internal，请复制完整的 NetConsoleBackend 目录。",
    )
    require(
        not (app_dir / "data").exists() and not (app_dir / "runtime").exists(),
        "no writable data/runtime directory in backend bundle",
        "Backend bundle must not contain writable data or runtime directories",
    )
    if not internal_dir.is_dir():
        return RuntimeCheckResult(False, tuple(messages))

    require(
        (internal_dir / "netconsole").is_dir(),
        "Python package found",
        "_internal/netconsole missing",
    )
    python_dll = _find_first(internal_dir, "python*.dll")
    require(
        python_dll is not None,
        f"{python_dll.name if python_dll else 'python runtime DLL'} found",
        "python runtime DLL missing",
    )
    for dll_name in REQUIRED_VC_RUNTIME_DLLS:
        found = _find_first(internal_dir, dll_name)
        require(found is not None, f"{dll_name} found", f"{dll_name} missing")
    for relative in REQUIRED_TOOLS:
        tool = app_dir / relative
        require(
            tool.is_file(),
            relative.as_posix() + " found",
            f"{relative.as_posix()} missing",
        )

    qt_residue = sorted(
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*")
        if path.is_file() and _is_qt_residue(path.relative_to(app_dir))
    )
    require(
        not qt_residue,
        "Qt runtime residue not found",
        "Qt runtime residue found: " + ", ".join(qt_residue[:20]),
    )
    if require_compliance_artifacts:
        compliance_paths = [app_dir / relative for relative in COMPLIANCE_FILES]
        for path in compliance_paths:
            require(
                path.is_file(),
                f"{path.relative_to(app_dir).as_posix()} found",
                f"required compliance file missing: {path}",
            )
        if all(path.is_file() for path in compliance_paths):
            errors: tuple[str, ...]
            try:
                approved = load_approved_distributions(
                    PROJECT_ROOT / "config" / "pyinstaller-approved-distributions.json",
                    platform="windows-x64",
                    python_version=load_python_runtime_version(PROJECT_ROOT),
                )
                artifact_distributions = load_inventory(
                    compliance_paths[3],
                    expected=approved,
                    executable=app_dir / APP_EXE,
                )
                notice_errors = validate_notice_file(compliance_paths[0])
                sbom_errors = validate_sbom(
                    compliance_paths[2],
                    required_python_components=artifact_distributions,
                )
                license_errors = tuple(
                    f"随包组件许可证哈希不一致：{name}"
                    for name, (relative, _source_suffix, expected_sha256) in (
                        PACKAGED_PYTHON_LICENSES.items()
                    )
                    if hashlib.sha256(
                        (
                            app_dir / "_internal" / "netconsole" / "assets" / relative
                        ).read_bytes()
                    ).hexdigest()
                    != expected_sha256
                )
                errors = (*notice_errors, *sbom_errors, *license_errors)
            except (ArtifactInventoryError, OSError, ValueError) as exc:
                errors = (f"制品 Python 清单校验失败：{exc}",)
            require(
                not errors,
                "NOTICE, SBOM and artifact inventory validated",
                "NOTICE/SBOM/artifact inventory validation failed: "
                + "; ".join(errors),
            )
    return RuntimeCheckResult(ok, tuple(messages))


def check_python_environment() -> RuntimeCheckResult:
    forbidden_metadata: list[str] = []
    for distribution in metadata.distributions():
        name = str(distribution.metadata.get("Name") or "")
        lowered = canonicalize_name(name)
        if _matches_qt_package_name(lowered):
            forbidden_metadata.append(name)
    forbidden_imports = [
        module for module in FORBIDDEN_QT_IMPORTS if _module_available(module)
    ]
    if forbidden_metadata or forbidden_imports:
        details = ", ".join((*forbidden_metadata, *forbidden_imports))
        return RuntimeCheckResult(
            False,
            (f"[ERROR] Python environment contains forbidden Qt packages: {details}",),
        )
    return RuntimeCheckResult(
        True, ("[OK] Python environment contains no Qt package metadata or imports",)
    )


def check_locked_environment(
    requirements_path: Path | str = PROJECT_ROOT / "requirements-build.txt",
    constraints_path: Path | str = PROJECT_ROOT / "constraints.txt",
    *,
    distributions: Iterable[object] | None = None,
) -> RuntimeCheckResult:
    try:
        assert_current_python_runtime(PROJECT_ROOT)
    except RuntimeError as exc:
        return RuntimeCheckResult(False, (f"[ERROR] {exc}",))
    requirements_path = Path(requirements_path).resolve()
    constraints_path = Path(constraints_path).resolve()
    try:
        roots = _read_requirements(requirements_path)
        constraints = _read_constraints(constraints_path)
    except (OSError, InvalidRequirement, ValueError) as exc:
        return RuntimeCheckResult(False, (f"[ERROR] 无法读取依赖锁：{exc}",))

    available: dict[str, object] = {}
    for distribution in (
        distributions if distributions is not None else metadata.distributions()
    ):
        name = str(getattr(distribution, "metadata", {}).get("Name") or "")
        if name:
            available[canonicalize_name(name)] = distribution

    errors: list[str] = []
    pending = list(roots)
    visited: set[str] = set()
    while pending:
        requirement = pending.pop(0)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        name = canonicalize_name(requirement.name)
        should_expand = name not in visited
        visited.add(name)
        expected = constraints.get(name)
        if expected is None:
            errors.append(f"constraints.txt 缺少依赖：{requirement.name}")
            continue
        distribution = available.get(name)
        if distribution is None:
            errors.append(f"构建环境缺少依赖：{requirement.name}=={expected}")
            continue
        actual = str(getattr(distribution, "version", "") or "")
        try:
            parsed_actual = Version(actual)
        except InvalidVersion:
            parsed_actual = None
        if requirement.specifier and (
            parsed_actual is None or parsed_actual not in requirement.specifier
        ):
            errors.append(
                f"依赖声明不满足：{requirement.name}{requirement.specifier}, actual={actual or '<unknown>'}"
            )
        try:
            matches = Version(actual) == Version(expected)
        except InvalidVersion:
            matches = actual == expected
        if not matches:
            errors.append(
                f"依赖版本不一致：{requirement.name} expected={expected}, actual={actual or '<unknown>'}"
            )
        if not should_expand:
            continue
        for raw_dependency in getattr(distribution, "requires", None) or ():
            try:
                dependency = Requirement(str(raw_dependency))
            except InvalidRequirement as exc:
                errors.append(f"依赖元数据无效：{requirement.name}: {exc}")
                continue
            if dependency.marker is None or dependency.marker.evaluate():
                pending.append(dependency)

    if errors:
        return RuntimeCheckResult(
            False, tuple(f"[ERROR] {message}" for message in errors)
        )
    return RuntimeCheckResult(
        True,
        (f"[OK] 构建依赖闭包与 constraints.txt 一致：{len(visited)} distributions",),
    )


def _is_qt_residue(relative_path: Path) -> bool:
    parts = tuple(part.casefold() for part in relative_path.parts)
    if any(_matches_qt_package_name(part) for part in parts):
        return True
    basename = relative_path.name.casefold()
    return bool(
        basename in FORBIDDEN_QT_BASENAMES
        or QT_LIBRARY_PATTERN.fullmatch(basename)
        or QT_PYTHON_EXTENSION_PATTERN.fullmatch(basename)
        or QT_TRANSLATION_PATTERN.fullmatch(basename)
    )


def _matches_qt_package_name(value: str) -> bool:
    normalized = canonicalize_name(value)
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}-")
        for prefix in FORBIDDEN_QT_PACKAGE_PREFIXES
    )


def _read_requirements(path: Path, seen: set[Path] | None = None) -> list[Requirement]:
    seen = seen or set()
    path = path.resolve()
    if path in seen:
        return []
    seen.add(path)
    result: list[Requirement] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            included = line.split(maxsplit=1)[1]
            result.extend(_read_requirements(path.parent / included, seen))
            continue
        if line.startswith("-"):
            continue
        result.append(Requirement(line))
    return result


def _read_constraints(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        exact_versions = [
            item.version
            for item in requirement.specifier
            if item.operator == "==" and "*" not in item.version
        ]
        if len(exact_versions) != 1 or len(tuple(requirement.specifier)) != 1:
            raise ValueError(f"constraint 必须是单一精确版本：{line}")
        result[canonicalize_name(requirement.name)] = exact_versions[0]
    return result


def _module_available(module: str) -> bool:
    try:
        return util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _find_first(root: Path, pattern: str) -> Path | None:
    return next((path for path in root.rglob(pattern) if path.is_file()), None)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the packaged Qt-free NetConsole Backend"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--python-environment",
        action="store_true",
        help="check the current Python environment for Qt metadata/imports",
    )
    mode.add_argument(
        "--locked-environment",
        action="store_true",
        help="check the installed dependency closure against constraints.txt",
    )
    parser.add_argument(
        "--require-compliance",
        action="store_true",
        help="require packaged NOTICE and CycloneDX SBOM artifacts",
    )
    parser.add_argument(
        "--requirements",
        default="requirements-build.txt",
        help="root requirements file for --locked-environment",
    )
    parser.add_argument(
        "--constraints",
        default="constraints.txt",
        help="constraints file for --locked-environment",
    )
    parser.add_argument(
        "app_dir",
        nargs="?",
        default=PROJECT_ROOT
        / "dist"
        / "_build"
        / "pyinstaller"
        / "dist"
        / "NetConsoleBackend",
        help="PyInstaller dist/NetConsoleBackend directory",
    )
    args = parser.parse_args()
    if args.python_environment:
        result = check_python_environment()
    elif args.locked_environment:
        result = check_locked_environment(
            Path(args.requirements), Path(args.constraints)
        )
    else:
        result = check_runtime_deps(
            Path(args.app_dir), require_compliance_artifacts=args.require_compliance
        )
    for message in result.messages:
        print(message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
