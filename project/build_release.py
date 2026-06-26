from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import clean_build_spec
from project.build_config import BuildConfig, load_config
from netconsole.services.tool_smoke_test import run_tool_smoke_tests


BACKENDS = ("pyinstaller", "nuitka")
NUITKA_ALLOWED_RELEASE_ITEMS = frozenset({"NetConsole.exe", "_internal", "data", "runtime"})
PYINSTALLER_ALLOWED_APP_ITEMS = frozenset({"NetConsole.exe", "_internal", "data", "runtime"})
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
    args = parser.parse_args()

    try:
        config = load_config()
        validate_config(config)
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
            build_pyinstaller(config, smoke_test=not args.no_smoke_test, make_zip=not args.no_zip)
        else:
            build_nuitka(config, jobs=args.jobs, smoke_test=not args.no_smoke_test, make_zip=not args.no_zip)
        assert_root_clean(config.root)
        validate_release_version_tree(config.release_version_dir)
        return 0
    except BuildError as exc:
        print("BUILD FAILED")
        print(str(exc))
        return 1


def validate_config(config: BuildConfig) -> None:
    missing = [
        path
        for path in (config.entry_file, config.icon_file, config.changelog_file, config.tools_dir, *config.required_tool_files)
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


def build_pyinstaller(config: BuildConfig, *, smoke_test: bool, make_zip: bool) -> None:
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


def build_nuitka(config: BuildConfig, *, jobs: str, smoke_test: bool, make_zip: bool) -> None:
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
    prepare_writable_release_dirs(release_root)
    validate_release_app_dir(release_root, NUITKA_ALLOWED_RELEASE_ITEMS)
    if smoke_test:
        run_packaged_smoke(final_exe, release_root)
    if make_zip:
        zip_directory(release_root, config.zip_path("nuitka"), release_root, NUITKA_ALLOWED_RELEASE_ITEMS)
        validate_zip_file(config.zip_path("nuitka"))
    validate_release_app_dir(release_root, NUITKA_ALLOWED_RELEASE_ITEMS)
    print("Nuitka output:", final_exe)


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
        f"--include-raw-dir={config.tools_dir}=tools",
        f"--include-data-dir={config.root / 'netconsole' / 'ui' / 'icons'}=netconsole/ui/icons",
        f"--include-data-file={config.changelog_file}=netconsole/assets/changelog.md",
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
                f"      - '{config.tools_dir.as_posix()}'",
                "      - 'netconsole/ui/icons'",
                "    patterns:",
                "      - 'netconsole/assets/changelog.md'",
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
    forbidden = find_forbidden_release_dirs(app_dir)
    if forbidden:
        raise BuildError("Forbidden release directories found:\n" + "\n".join(str(path) for path in forbidden))


def validate_release_version_tree(version_dir: Path) -> None:
    if not version_dir.exists():
        return
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
            effective = _strip_zip_app_root(lowered)
            if any(part in FORBIDDEN_RELEASE_DIR_NAMES for part in effective):
                if _is_under_internal_netconsole(effective) and not any(part in {"docs", "tests", "project"} for part in effective):
                    continue
                forbidden.append(name)
        if forbidden:
            raise BuildError("Forbidden release zip entries found:\n" + "\n".join(forbidden))


def _strip_zip_app_root(parts: tuple[str, ...]) -> tuple[str, ...]:
    if len(parts) >= 2 and parts[0] == "netconsole" and parts[1] in {"netconsole.exe", "_internal", "data", "runtime"}:
        return parts[1:]
    return parts


def _is_internal_netconsole_dir(parts: tuple[str, ...]) -> bool:
    return bool(len(parts) >= 2 and parts[-2:] == ("_internal", "netconsole"))


def _is_under_internal_netconsole(parts: tuple[str, ...]) -> bool:
    return any(parts[index : index + 2] == ("_internal", "netconsole") for index in range(max(0, len(parts) - 1)))


def assert_root_clean(root: Path) -> None:
    forbidden = [root / "build", root / "dist", *root.glob("*.spec"), *root.glob("*.exe"), *root.glob("*.zip"), root / "build_meta.env"]
    dirty = [path for path in forbidden if path.exists()]
    if dirty:
        raise BuildError("Forbidden build artifact exists in project root:\n" + "\n".join(str(path) for path in dirty))


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int | None = None) -> None:
    print(subprocess.list2cmdline(cmd))
    try:
        subprocess.run(cmd, cwd=cwd or Path(__file__).resolve().parents[1], env=env, check=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"Command failed with exit code {exc.returncode}: {subprocess.list2cmdline(cmd)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildError(f"Command timed out: {subprocess.list2cmdline(cmd)}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
