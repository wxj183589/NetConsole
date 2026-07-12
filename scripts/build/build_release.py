from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.build import clean_build_spec
from scripts.build.build_config import BuildConfig, load_config
from netconsole.core.feature_flags import FeatureGate, engineer_package_enabled, install_runtime_feature_files, load_profile, profiles_dir
from netconsole.core.feature_registry import list_features
from netconsole.services.tool_smoke_test import run_tool_smoke_tests


BACKENDS = ("pyinstaller", "nuitka")
BUILD_EDITIONS = ("internal", "customer", "engineer", "both", "all")
NUITKA_ALLOWED_RELEASE_ITEMS = frozenset({"NetConsole.exe", "_internal", "data", "runtime", "tools"})
PYINSTALLER_ALLOWED_APP_ITEMS = frozenset({"NetConsole.exe", "_internal", "data", "runtime", "tools"})
FORBIDDEN_RELEASE_DIR_NAMES = frozenset({"docs", "tests", "project", "netconsole"})


class BuildError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Build NetConsole release artifacts")
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--skip-install", action="store_true", help="do not install build dependencies")
    parser.add_argument("--no-smoke-test", action="store_true", help="skip source and packaged smoke tests")
    parser.add_argument("--no-zip", action="store_true", help="do not create release zip")
    parser.add_argument("--jobs", default="8", help="Nuitka worker count")
    parser.add_argument("--dry-run", action="store_true", help="print command plan without compiling")
    parser.add_argument("--build-editions", choices=BUILD_EDITIONS, default="both", help="release editions to generate")
    parser.add_argument("--feature-profile", default=None, help="feature profile for single-edition customer/internal builds")
    parser.add_argument("--admin-unlock-password", default=None, help="customer edition temporary full-mode unlock password")
    args = parser.parse_args()

    try:
        config = load_config()
        editions = selected_editions(args.build_editions)
        validate_config(config, editions=editions)
        print(f"APP_NAME={config.app_name}")
        print(f"APP_VERSION={config.app_version}")
        print(f"BACKEND={args.backend}")
        if args.dry_run:
            print_command_plan(config, args.backend, args.jobs)
            return 0
        if not args.skip_install:
            install_dependencies(args.backend)
        preflight(config, smoke_test=not args.no_smoke_test)
        if args.backend == "pyinstaller":
            payload = build_pyinstaller(config, smoke_test=not args.no_smoke_test, make_zip=not args.no_zip)
        else:
            payload = build_nuitka(config, jobs=args.jobs, smoke_test=not args.no_smoke_test, make_zip=not args.no_zip)
        create_edition_releases(
            config,
            payload,
            args.build_editions,
            feature_profile=args.feature_profile,
            make_zip=not args.no_zip,
            admin_unlock_password=args.admin_unlock_password or os.environ.get("NETCONSOLE_ADMIN_UNLOCK_PASSWORD"),
        )
        assert_root_clean(config.root)
        validate_release_version_tree(config.release_version_dir)
        return 0
    except BuildError as exc:
        print("BUILD FAILED")
        print(str(exc))
        return 1


def validate_config(config: BuildConfig, *, editions: tuple[str, ...] = ()) -> None:
    missing = [
        path
        for path in (
            config.entry_file,
            config.icon_file,
            config.changelog_file,
            config.tools_dir,
            config.root / "src" / "netconsole" / "assets" / "open_source_notices.json",
            config.root / "src" / "netconsole" / "assets" / "THIRD_PARTY_COMPONENTS.md",
            config.root / "src" / "netconsole" / "assets" / "IPOP_v4.1_notice.md",
            *config.required_tool_files,
        )
        if not path.exists()
    ]
    if missing:
        raise BuildError("Missing required build input:\n" + "\n".join(str(path) for path in missing))
    if not config.app_version.startswith("v"):
        raise BuildError(f"APP_VERSION must keep the existing v prefix: {config.app_version}")


def install_dependencies(backend: str) -> None:
    if backend == "pyinstaller":
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"])
        return
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-U", "nuitka", "ordered-set", "zstandard"])


def preflight(config: BuildConfig, *, smoke_test: bool) -> None:
    clean_build_spec.validate_tool_sources()
    if smoke_test:
        print("[check] source external tools")
        for result in run_tool_smoke_tests():
            first_line = next((line.strip() for line in result.output.splitlines() if line.strip()), "OK")
            print(f"[OK] {result.name}: {first_line}")


def build_pyinstaller(config: BuildConfig, *, smoke_test: bool, make_zip: bool) -> Path:
    build_root = config.backend_build_dir("pyinstaller")
    release_root = config.backend_release_dir("pyinstaller")
    dist_root = build_root / "dist"
    app_dist = dist_root / config.app_name
    clean_backend_dirs(build_root, release_root)

    clean_build_spec.write_spec()
    command = pyinstaller_command(config)
    run(command)
    (app_dist / "data").mkdir(parents=True, exist_ok=True)
    (app_dist / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    copy_release_tools(config, app_dist)
    clean_build_spec.validate_dist()
    final_app = release_root / config.app_name
    validate_payload_source(app_dist, PYINSTALLER_ALLOWED_APP_ITEMS)
    copy_tree(app_dist, final_app)
    validate_release_app_dir(final_app, PYINSTALLER_ALLOWED_APP_ITEMS)
    if smoke_test:
        run_packaged_smoke(final_app / f"{config.app_name}.exe", final_app)
    if make_zip:
        zip_directory(final_app, config.zip_path("pyinstaller"), release_root, PYINSTALLER_ALLOWED_APP_ITEMS)
        validate_zip_file(config.zip_path("pyinstaller"))
    validate_release_app_dir(final_app, PYINSTALLER_ALLOWED_APP_ITEMS)
    print("PyInstaller output:", final_app / f"{config.app_name}.exe")
    return final_app


def build_nuitka(config: BuildConfig, *, jobs: str, smoke_test: bool, make_zip: bool) -> Path:
    build_root = config.backend_build_dir("nuitka")
    release_root = config.backend_release_dir("nuitka")
    clean_backend_dirs(build_root, release_root)
    package_config = write_nuitka_package_config(config, build_root)
    command = nuitka_command(config, jobs, package_config)
    run(command)
    built_exe = build_root / f"{config.app_name}.exe"
    if not built_exe.is_file():
        raise BuildError(f"Nuitka onefile output not found: {built_exe}")
    final_exe = release_root / f"{config.app_name}.exe"
    shutil.copy2(built_exe, final_exe)
    copy_release_tools(config, release_root)
    prepare_writable_release_dirs(release_root)
    validate_release_app_dir(release_root, NUITKA_ALLOWED_RELEASE_ITEMS)
    validate_release_fping(release_root)
    if smoke_test:
        run_packaged_smoke(final_exe, release_root)
    if make_zip:
        zip_directory(release_root, config.zip_path("nuitka"), release_root, NUITKA_ALLOWED_RELEASE_ITEMS)
        validate_zip_file(config.zip_path("nuitka"))
    validate_release_app_dir(release_root, NUITKA_ALLOWED_RELEASE_ITEMS)
    print("Nuitka output:", final_exe)
    return release_root


def create_edition_releases(
    config: BuildConfig,
    payload: Path,
    build_editions: str,
    *,
    feature_profile: str | None,
    make_zip: bool,
    admin_unlock_password: str | None = None,
) -> None:
    for edition in selected_editions(build_editions):
        profile = feature_profile or ("full" if edition in {"internal", "engineer"} else "customer")
        destination = config.release_version_dir / edition
        remove_tree(destination)
        copy_tree(payload, destination)
        remove_copied_zip_files(destination)
        unlock_password = admin_unlock_password if edition == "customer" else None
        install_runtime_feature_files(destination, edition=edition, profile=profile, admin_unlock_password=unlock_password)
        validate_embedded_feature_gate(destination, edition=edition, profile=profile)
        validate_release_app_dir(destination, NUITKA_ALLOWED_RELEASE_ITEMS)
        validate_release_fping(destination)
        validate_no_ipop_artifacts(destination)
        run_packaged_release_contract(destination / f"{config.app_name}.exe", destination)
        if make_zip:
            zip_path = config.release_version_dir / f"{config.app_name}_{config.app_version}_{edition}.zip"
            zip_directory(destination, zip_path, destination, NUITKA_ALLOWED_RELEASE_ITEMS)
            validate_zip_file(zip_path)
        validate_release_app_dir(destination, NUITKA_ALLOWED_RELEASE_ITEMS)
        print(f"{edition.title()} output:", destination / f"{config.app_name}.exe")


def selected_editions(value: str) -> tuple[str, ...]:
    if value == "all":
        return ("internal", "customer", "engineer")
    if value == "both":
        editions = ["internal", "customer"]
        if engineer_package_enabled():
            editions.append("engineer")
        return tuple(editions)
    return (value,)


def remove_copied_zip_files(destination: Path) -> None:
    for zip_path in destination.glob("*.zip"):
        zip_path.unlink()


def validate_embedded_feature_gate(destination: Path, *, edition: str, profile: str) -> None:
    gate = FeatureGate(destination)
    if gate.build_info.get("edition") != edition or gate.build_info.get("feature_profile") != profile:
        raise BuildError(f"FeatureGate build info mismatch for {destination}: {gate.build_info}")
    runtime = destination / "runtime"
    hidden_runtime = destination / ".runtime_feature_gate_validation"
    if hidden_runtime.exists():
        shutil.rmtree(hidden_runtime)
    if runtime.exists():
        runtime.rename(hidden_runtime)
    try:
        embedded_gate = FeatureGate(destination)
        if embedded_gate.build_info.get("edition") != edition or embedded_gate.build_info.get("feature_profile") != profile:
            raise BuildError(f"Embedded FeatureGate fallback mismatch for {destination}: {embedded_gate.build_info}")
        if profile == "customer":
            validate_customer_feature_gate(embedded_gate)
    finally:
        if hidden_runtime.exists():
            if runtime.exists():
                shutil.rmtree(runtime)
            hidden_runtime.rename(runtime)


def validate_customer_feature_gate(gate: FeatureGate) -> None:
    for feature_id in ("module.feature_switch", "system.feature_flags"):
        if gate.is_visible(feature_id) or gate.is_enabled(feature_id):
            raise BuildError(f"Customer build exposes {feature_id}")
    expected = load_profile(profiles_dir() / "customer.json", "customer")
    for feature_id, state in expected.items():
        if not state.get("visible", True) and gate.is_visible(feature_id):
            raise BuildError(f"Customer build exposes hidden feature: {feature_id}")
        if not state.get("enabled", True) and gate.is_enabled(feature_id):
            raise BuildError(f"Customer build enables disabled feature: {feature_id}")
    for item in list_features():
        if item.internal_only and (gate.is_visible(item.feature_id) or gate.is_enabled(item.feature_id)):
            raise BuildError(f"Customer build exposes internal-only feature: {item.feature_id}")


def pyinstaller_command(config: BuildConfig) -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(config.backend_build_dir("pyinstaller") / "dist"),
        "--workpath",
        str(config.backend_build_dir("pyinstaller") / "build"),
        str(config.backend_build_dir("pyinstaller") / "spec" / "NetConsole.spec"),
    ]


def nuitka_command(config: BuildConfig, jobs: str, package_config: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        "--msvc=latest",
        f"--jobs={jobs}",
        "--enable-plugin=pyside6",
        "--include-qt-plugins=sensible",
        "--windows-console-mode=disable",
        "--assume-yes-for-downloads",
        f"--report={config.backend_build_dir('nuitka') / 'nuitka-report.xml'}",
        f"--output-dir={config.backend_build_dir('nuitka')}",
        f"--output-filename={config.app_name}.exe",
        f"--windows-icon-from-ico={config.icon_file}",
        f"--include-raw-dir={config.tools_dir / 'windows-x64' / 'fping'}=tools/windows-x64/fping",
        f"--include-raw-dir={config.tools_dir / 'windows-x64' / 'iperf3'}=tools/windows-x64/iperf3",
        f"--include-data-dir={config.root / 'src' / 'netconsole' / 'ui' / 'icons'}=netconsole/ui/icons",
        f"--include-data-file={config.changelog_file}=netconsole/assets/changelog.md",
        f"--include-data-file={config.root / 'src' / 'netconsole' / 'assets' / 'open_source_notices.json'}=netconsole/assets/open_source_notices.json",
        f"--include-data-file={config.root / 'src' / 'netconsole' / 'assets' / 'THIRD_PARTY_COMPONENTS.md'}=netconsole/assets/THIRD_PARTY_COMPONENTS.md",
        f"--include-data-file={config.root / 'src' / 'netconsole' / 'assets' / 'IPOP_v4.1_notice.md'}=netconsole/assets/IPOP_v4.1_notice.md",
        str(config.entry_file),
    ]


def write_nuitka_package_config(config: BuildConfig, build_root: Path) -> Path:
    build_root.mkdir(parents=True, exist_ok=True)
    path = build_root / "netconsole.nuitka-package.config.yml"
    path.write_text(
        "\n".join(
            [
                "- module-name: 'netconsole'",
                "  data-files:",
                "    dirs:",
                f"      - '{(config.tools_dir / 'windows-x64' / 'fping').as_posix()}'",
                f"      - '{(config.tools_dir / 'windows-x64' / 'iperf3').as_posix()}'",
                "      - 'netconsole/ui/icons'",
                "    patterns:",
                "      - 'netconsole/assets/changelog.md'",
                "      - 'netconsole/assets/open_source_notices.json'",
                "      - 'netconsole/assets/THIRD_PARTY_COMPONENTS.md'",
                "      - 'netconsole/assets/IPOP_v4.1_notice.md'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def print_command_plan(config: BuildConfig, backend: str, jobs: str) -> None:
    if backend == "pyinstaller":
        print(subprocess.list2cmdline(pyinstaller_command(config)))
    else:
        package_config = config.backend_build_dir("nuitka") / "netconsole.nuitka-package.config.yml"
        print(subprocess.list2cmdline(nuitka_command(config, jobs, package_config)))


def clean_backend_dirs(build_root: Path, release_root: Path) -> None:
    remove_tree(build_root)
    remove_tree(release_root)
    build_root.mkdir(parents=True, exist_ok=True)
    release_root.mkdir(parents=True, exist_ok=True)


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    root = load_config().root.resolve()
    resolved = path.resolve()
    if root not in resolved.parents:
        raise BuildError(f"Refusing to remove path outside project root: {path}")
    shutil.rmtree(resolved)


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def copy_release_tools(config: BuildConfig, release_root: Path) -> None:
    destination = release_root / "tools" / "windows-x64"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for tool_name in ("fping", "iperf3"):
        shutil.copytree(
            config.tools_dir / "windows-x64" / tool_name,
            destination / tool_name,
            ignore=shutil.ignore_patterns("__pycache__", "*.py", "*.pyc", "*.pyo"),
        )
    validate_no_ipop_artifacts(release_root)


def validate_no_ipop_artifacts(root: Path) -> None:
    if not root.exists():
        return
    forbidden: list[Path] = []
    for directory, dir_names, file_names in os.walk(root):
        base = Path(directory)
        for name in (*dir_names, *file_names):
            path = base / name
            relative_parts = {part.casefold() for part in path.relative_to(root).parts}
            if path.name.casefold() == "ipop.exe" or "ipop" in relative_parts:
                forbidden.append(path)
    if forbidden:
        detail = "\n".join(str(path) for path in forbidden[:20])
        raise BuildError(f"检测到未经确认可再分发的第三方工具 IPOP.EXE，已停止构建发布包。\n{detail}")


def validate_release_fping(release_root: Path) -> None:
    fping_dir = release_root / "tools" / "windows-x64" / "fping"
    exe = fping_dir / "fping.exe"
    dlls = list(fping_dir.glob("*.dll"))
    if not exe.is_file():
        raise BuildError(f"Release is missing fping.exe: {exe}")
    if not dlls:
        raise BuildError(f"Release is missing fping runtime DLLs: {fping_dir}")


def prepare_writable_release_dirs(release_root: Path) -> None:
    (release_root / "data").mkdir(parents=True, exist_ok=True)
    (release_root / "runtime" / "logs").mkdir(parents=True, exist_ok=True)


def run_packaged_smoke(exe: Path, cwd: Path) -> None:
    env = os.environ.copy()
    env["NETCONSOLE_SMOKE_TEST"] = "1"
    run([str(exe)], cwd=cwd, env=env, timeout=30)
    env = os.environ.copy()
    env["NETCONSOLE_RUNTIME_SMOKE_TEST"] = "1"
    run([str(exe)], cwd=cwd, env=env, timeout=30)
    env = os.environ.copy()
    env["NETCONSOLE_TOOL_SMOKE_TEST"] = "1"
    run([str(exe)], cwd=cwd, env=env, timeout=30)
    run_packaged_release_contract(exe, cwd)


def run_packaged_release_contract(exe: Path, cwd: Path) -> None:
    env = os.environ.copy()
    env["NETCONSOLE_RELEASE_CONTRACT_SMOKE_TEST"] = "1"
    run([str(exe)], cwd=cwd, env=env, timeout=30)


def validate_payload_source(source: Path, allowed_items: frozenset[str]) -> None:
    if not source.exists():
        raise BuildError(f"Release payload source does not exist: {source}")
    config = load_config()
    resolved = source.resolve()
    forbidden_sources = {config.root.resolve(), (config.root / "project").resolve()}
    if resolved in forbidden_sources:
        raise BuildError(f"Refusing to package source tree as release payload: {source}")
    validate_release_app_dir(source, allowed_items)


def zip_directory(source: Path, destination: Path, base_dir: Path, allowed_items: frozenset[str]) -> None:
    if destination.exists():
        destination.unlink()
    validate_payload_source(source, allowed_items)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in iter_allowed_payload_paths(source, allowed_items):
            if path == destination:
                continue
            arcname = path.relative_to(base_dir).as_posix()
            if path.is_dir():
                archive.write(path, arcname.rstrip("/") + "/")
            else:
                archive.write(path, arcname)


def iter_allowed_payload_paths(source: Path, allowed_items: frozenset[str]) -> list[Path]:
    paths: list[Path] = []
    for name in sorted(allowed_items):
        path = source / name
        if not path.exists():
            continue
        paths.extend(iter_payload_path(path))
    return paths


def iter_payload_path(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    children = sorted(path.iterdir(), key=lambda item: item.as_posix().lower())
    paths = [path]
    for child in children:
        paths.extend(iter_payload_path(child))
    return paths


def validate_release_app_dir(app_dir: Path, allowed_items: frozenset[str]) -> None:
    if not app_dir.exists():
        raise BuildError(f"Release app directory does not exist: {app_dir}")
    unexpected = sorted(path.name for path in app_dir.iterdir() if path.name not in allowed_items and not path.name.endswith(".zip"))
    if unexpected:
        raise BuildError(f"Unexpected release items in {app_dir}: {unexpected}")
    validate_no_ipop_artifacts(app_dir)
    forbidden = find_forbidden_release_dirs(app_dir)
    if forbidden:
        raise BuildError("Forbidden release directories found:\n" + "\n".join(str(path) for path in forbidden))


def validate_release_version_tree(version_dir: Path) -> None:
    if not version_dir.exists():
        return
    validate_no_ipop_artifacts(version_dir)
    forbidden = find_forbidden_release_dirs(version_dir)
    if forbidden:
        raise BuildError("Forbidden release directories found under release version directory:\n" + "\n".join(str(path) for path in forbidden))


def find_forbidden_release_dirs(root: Path) -> list[Path]:
    forbidden: list[Path] = []
    for path in iter_directories(root):
        if path.name not in FORBIDDEN_RELEASE_DIR_NAMES:
            continue
        relative = path.relative_to(root).parts
        if path.name == "netconsole" and _is_internal_netconsole_dir(tuple(part.lower() for part in relative)):
            continue
        forbidden.append(path)
    return forbidden


def iter_directories(root: Path) -> list[Path]:
    if not root.exists():
        return []
    directories: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda item: item.as_posix().lower()):
        if not child.is_dir():
            continue
        directories.append(child)
        directories.extend(iter_directories(child))
    return directories


def validate_zip_file(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        forbidden = []
        for name in archive.namelist():
            parts = tuple(part for part in Path(name).parts if part not in {"", "."})
            lowered = tuple(part.lower() for part in parts)
            if "ipop" in lowered or (lowered and lowered[-1] == "ipop.exe"):
                raise BuildError("检测到未经确认可再分发的第三方工具 IPOP.EXE，已停止构建发布包。")
            effective = _strip_zip_app_root(lowered)
            if any(part in FORBIDDEN_RELEASE_DIR_NAMES for part in effective):
                if _is_under_internal_netconsole(effective) and not any(part in {"docs", "tests", "project"} for part in effective):
                    continue
                forbidden.append(name)
        if forbidden:
            raise BuildError("Forbidden release zip entries found:\n" + "\n".join(forbidden))


def _strip_zip_app_root(parts: tuple[str, ...]) -> tuple[str, ...]:
    if len(parts) >= 2 and parts[0] == "netconsole" and parts[1] in {"netconsole.exe", "_internal", "data", "runtime", "tools"}:
        return parts[1:]
    return parts


def _is_internal_netconsole_dir(parts: tuple[str, ...]) -> bool:
    return bool(len(parts) >= 2 and parts[-2:] == ("_internal", "netconsole"))


def _is_under_internal_netconsole(parts: tuple[str, ...]) -> bool:
    return any(parts[index : index + 2] == ("_internal", "netconsole") for index in range(max(0, len(parts) - 1)))


def assert_root_clean(root: Path) -> None:
    forbidden = [root / "build", root / "release", *root.glob("*.spec"), *root.glob("*.exe"), *root.glob("*.zip"), root / "build_meta.env"]
    dirty = [path for path in forbidden if path.exists()]
    if dirty:
        raise BuildError("Forbidden build artifact exists in project root:\n" + "\n".join(str(path) for path in dirty))


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int | None = None) -> None:
    print(subprocess.list2cmdline(cmd))
    try:
        subprocess.run(cmd, cwd=cwd or Path(__file__).resolve().parents[2], env=env, check=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"Command failed with exit code {exc.returncode}: {subprocess.list2cmdline(cmd)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildError(f"Command timed out: {subprocess.list2cmdline(cmd)}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
