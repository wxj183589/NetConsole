from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
ROOT = PROJECT_DIR.parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
BUILD_ROOT = ROOT / "build" / "nuitka"
DIST_DIR = BUILD_ROOT / "NetConsole.dist"
APP_DIR_NAME = "NetConsole"

REQUIRED_FILES = (
    ROOT / "main.py",
    ROOT / "netconsole" / "core" / "version.py",
    ROOT / "netconsole" / "ui" / "icons" / "love.ico",
    ROOT / "netconsole" / "docs" / "changelog.md",
    ROOT / "tools" / "iperf" / "iperf3.exe",
    ROOT / "tools" / "fping_v3" / "Fping_v3.exe",
)

RUNTIME_FILE_COPIES = (
    (
        ROOT / "tools" / "iperf" / "iperf3.exe",
        DIST_DIR / "tools" / "iperf" / "iperf3.exe",
    ),
    (
        ROOT / "tools" / "fping_v3" / "Fping_v3.exe",
        DIST_DIR / "tools" / "fping_v3" / "Fping_v3.exe",
    ),
)

REQUIRED_MODULES = (
    ("nuitka", "nuitka"),
    ("ordered-set", "ordered_set"),
    ("zstandard", "zstandard"),
    ("PySide6", "PySide6"),
)


@dataclass(frozen=True)
class VersionInfo:
    app_name: str
    app_version: str
    app_author: str

    @property
    def release_dir(self) -> Path:
        return ROOT / "release" / "nuitka" / self.app_version

    @property
    def zip_name(self) -> str:
        return f"{self.app_name}_{self.app_version}_nuitka.zip"

    @property
    def zip_path(self) -> Path:
        return self.release_dir / self.zip_name


def main() -> int:
    parser = argparse.ArgumentParser(description="Build NetConsole with Nuitka standalone mode.")
    parser.add_argument("--dry-run", action="store_true", help="print planned paths and command without compiling")
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="install Nuitka build dependencies before dependency checks",
    )
    parser.add_argument("--jobs", default="8", help="Nuitka worker count, default: 8")
    args = parser.parse_args()

    try:
        print("[1/8] Read version information")
        version = read_version_info()
        validate_version(version)
        print(f"APP_NAME={version.app_name}")
        print(f"APP_VERSION={version.app_version}")
        print(f"APP_AUTHOR={version.app_author}")
        print(f"Output zip={version.zip_path}")

        print("[2/8] Check Python / Nuitka dependencies")
        if args.install_deps:
            install_build_dependencies()
        check_environment(require_modules=not args.dry_run)

        command = build_nuitka_command(version, args.jobs)
        if args.dry_run:
            print("[DRY-RUN] Build root:", BUILD_ROOT)
            print("[DRY-RUN] Dist dir:", DIST_DIR)
            print("[DRY-RUN] Release dir:", version.release_dir)
            print("[DRY-RUN] Nuitka command:")
            print(command_line(command))
            print("[DRY-RUN] Skipping compile, smoke test, and zip creation.")
            print("[8/8] Done")
            return 0

        print("[3/8] Clean old Nuitka artifacts")
        clean_output_paths(version)

        print("[4/8] Run Nuitka standalone compile")
        run(command)
        normalize_dist_dir()

        print("[5/8] Check runtime resources")
        copy_runtime_files()
        verify_runtime_files()
        prepare_runtime_dirs()

        print("[6/8] Run smoke test")
        run_smoke_test()

        print("[7/8] Create zip")
        create_release_zip(version)

        print("[8/8] Done")
        print("Build output:", DIST_DIR / "NetConsole.exe")
        print("Release zip:", version.zip_path)
        return 0
    except BuildError as exc:
        print("BUILD FAILED")
        print(str(exc))
        return 1


class BuildError(RuntimeError):
    pass


def read_version_info() -> VersionInfo:
    sys.path.insert(0, str(ROOT))
    try:
        from netconsole.core.version import APP_AUTHOR, APP_NAME, APP_VERSION
    except Exception as exc:  # pragma: no cover - failure text matters more than type here.
        raise BuildError(f"Unable to read netconsole.core.version: {exc}") from exc
    finally:
        try:
            sys.path.remove(str(ROOT))
        except ValueError:
            pass
    return VersionInfo(APP_NAME, APP_VERSION, APP_AUTHOR)


def validate_version(version: VersionInfo) -> None:
    if version.app_name != "NetConsole":
        raise BuildError(f"Unexpected APP_NAME: {version.app_name!r}")
    if not version.app_version.startswith("v"):
        raise BuildError(f"APP_VERSION must keep the existing v prefix: {version.app_version!r}")
    if version.app_version != "v1.3.0":
        raise BuildError(f"Unexpected APP_VERSION: {version.app_version!r}; expected v1.3.0")
    if not version.app_author:
        raise BuildError("APP_AUTHOR is empty")


def install_build_dependencies() -> None:
    run([str(VENV_PYTHON), "-m", "pip", "install", "-U", "nuitka", "ordered-set", "zstandard"])


def check_environment(require_modules: bool = True) -> None:
    if sys.version_info[:2] != (3, 13):
        raise BuildError(f"Python 3.13.x is required, current: {sys.version.split()[0]}")
    if not VENV_PYTHON.exists():
        raise BuildError(f"Missing virtual environment Python: {VENV_PYTHON}")
    if Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        raise BuildError(f"Please run through build_nuitka_release.bat so {VENV_PYTHON} is used")

    missing_modules = [name for name, module in REQUIRED_MODULES if importlib.util.find_spec(module) is None]
    if missing_modules:
        message = (
            "Missing build dependencies: "
            + ", ".join(missing_modules)
            + os.linesep
            + r"Please run: .\.venv\Scripts\python.exe -m pip install -U nuitka ordered-set zstandard"
        )
        if not require_modules:
            print("[DRY-RUN] " + message)
            return
        raise BuildError(
            message
        )

    missing_files = [path for path in REQUIRED_FILES if not path.exists()]
    if missing_files:
        raise BuildError("Missing required files:" + os.linesep + os.linesep.join(str(path) for path in missing_files))


def build_nuitka_command(version: VersionInfo, jobs: str) -> list[str]:
    return [
        str(VENV_PYTHON),
        "-m",
        "nuitka",
        "--standalone",
        "--msvc=latest",
        f"--jobs={jobs}",
        "--enable-plugin=pyside6",
        "--include-qt-plugins=sensible",
        "--windows-console-mode=disable",
        "--assume-yes-for-downloads",
        f"--output-dir={BUILD_ROOT}",
        f"--output-filename={version.app_name}",
        "--windows-icon-from-ico=netconsole\\ui\\icons\\love.ico",
        "--include-data-dir=netconsole\\ui\\icons=netconsole\\ui\\icons",
        "--include-data-file=netconsole\\docs\\changelog.md=netconsole\\docs\\changelog.md",
        "--include-data-files=tools/iperf/iperf3.exe=tools/iperf/iperf3.exe",
        "--include-data-files=tools/fping_v3/Fping_v3.exe=tools/fping_v3/Fping_v3.exe",
        "--include-data-dir=tools=tools",
        "main.py",
    ]


def clean_output_paths(version: VersionInfo) -> None:
    remove_tree(BUILD_ROOT)
    remove_tree(version.release_dir)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    version.release_dir.mkdir(parents=True, exist_ok=True)


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    resolved = path.resolve()
    root = ROOT.resolve()
    if root not in resolved.parents:
        raise BuildError(f"Refusing to remove path outside project root: {path}")
    shutil.rmtree(resolved)


def verify_runtime_files() -> None:
    expected = (
        DIST_DIR / "NetConsole.exe",
        DIST_DIR / "netconsole" / "ui" / "icons" / "love.ico",
        DIST_DIR / "netconsole" / "docs" / "changelog.md",
        DIST_DIR / "tools" / "iperf" / "iperf3.exe",
        DIST_DIR / "tools" / "fping_v3" / "Fping_v3.exe",
    )
    missing = [path for path in expected if not path.exists()]
    if missing:
        raise BuildError("Missing packaged runtime files:" + os.linesep + os.linesep.join(str(path) for path in missing))


def normalize_dist_dir() -> None:
    if DIST_DIR.exists():
        return
    fallback = BUILD_ROOT / "main.dist"
    if fallback.exists():
        fallback.rename(DIST_DIR)
        return
    raise BuildError(f"Nuitka output directory was not found: {DIST_DIR}")


def copy_runtime_files() -> None:
    if not DIST_DIR.exists():
        raise BuildError(f"Nuitka output directory was not found: {DIST_DIR}")
    for source, destination in RUNTIME_FILE_COPIES:
        if not source.exists():
            raise BuildError(f"Missing source runtime file: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def prepare_runtime_dirs() -> None:
    for relative in ("data", "runtime\\cache"):
        (DIST_DIR / relative).mkdir(parents=True, exist_ok=True)


def run_smoke_test() -> None:
    exe = DIST_DIR / "NetConsole.exe"
    env = os.environ.copy()
    env["NETCONSOLE_SMOKE_TEST"] = "1"
    run([str(exe)], env=env)


def create_release_zip(version: VersionInfo) -> None:
    app_root = version.release_dir / APP_DIR_NAME
    if app_root.exists():
        shutil.rmtree(app_root)
    shutil.copytree(DIST_DIR, app_root)
    if version.zip_path.exists():
        version.zip_path.unlink()
    with zipfile.ZipFile(version.zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in app_root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(version.release_dir))


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print(command_line(cmd))
    try:
        subprocess.run(cmd, cwd=ROOT, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"Command failed with exit code {exc.returncode}: {command_line(cmd)}") from exc


def command_line(cmd: list[str]) -> str:
    return subprocess.list2cmdline(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
