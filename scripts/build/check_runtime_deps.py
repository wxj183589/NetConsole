from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


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
    Path("tools") / "windows-x64" / "iperf3" / "iperf3.exe",
)
FORBIDDEN_QT_MARKERS = (
    "pyside6",
    "shiboken6",
    "qfluentwidgets",
    "qt6core",
    "qt6gui",
    "qt6widgets",
    "qt6webengine",
    "qwindows.dll",
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimeCheckResult:
    ok: bool
    messages: tuple[str, ...]


def check_runtime_deps(app_dir: Path | str) -> RuntimeCheckResult:
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
        require(tool.is_file(), relative.as_posix() + " found", f"{relative.as_posix()} missing")

    qt_residue = sorted(
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*")
        if path.is_file() and _is_qt_residue(path)
    )
    require(
        not qt_residue,
        "Qt runtime residue not found",
        "Qt runtime residue found: " + ", ".join(qt_residue[:20]),
    )
    return RuntimeCheckResult(ok, tuple(messages))


def _is_qt_residue(path: Path) -> bool:
    lowered = path.as_posix().casefold()
    return any(marker in lowered for marker in FORBIDDEN_QT_MARKERS)


def _find_first(root: Path, pattern: str) -> Path | None:
    return next((path for path in root.rglob(pattern) if path.is_file()), None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the packaged Qt-free NetConsole Backend")
    parser.add_argument(
        "app_dir",
        nargs="?",
        default=PROJECT_ROOT / "dist" / "_build" / "pyinstaller" / "dist" / "NetConsoleBackend",
        help="PyInstaller dist/NetConsoleBackend directory",
    )
    args = parser.parse_args()
    result = check_runtime_deps(Path(args.app_dir))
    for message in result.messages:
        print(message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
