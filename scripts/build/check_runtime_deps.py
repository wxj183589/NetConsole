from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


APP_EXE = "NetConsole.exe"
INTERNAL_DIR = "_internal"
REQUIRED_QT_DLLS = ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll")
OPTIONAL_QT_DLLS = ("Qt6Network.dll", "Qt6Svg.dll", "Qt6PrintSupport.dll")
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
    require(internal_dir.is_dir(), "_internal found", "发布包不完整：缺少 _internal 目录，请完整复制 dist/NetConsole 目录，不要只复制 NetConsole.exe")
    require((app_dir / "data").is_dir(), "data directory found", "data directory missing")
    require((app_dir / "runtime" / "logs").is_dir(), "runtime/logs directory found", "runtime/logs directory missing")
    if not internal_dir.is_dir():
        messages.append("建议：重新打包，或完整解压整个 NetConsole 文件夹。")
        messages.append("如仍提示 QtGui DLL load failed，请安装 Microsoft Visual C++ 2015-2022 Redistributable x64。")
        return RuntimeCheckResult(False, tuple(messages))

    for dll_name in REQUIRED_QT_DLLS:
        found = _find_first(internal_dir, dll_name)
        require(found is not None, f"{dll_name} found", f"{dll_name} missing：QtGui 依赖缺失，发布包不完整")

    python_dll = _find_first(internal_dir, "python*.dll")
    require(python_dll is not None, f"{python_dll.name if python_dll else 'python runtime DLL'} found", "python runtime DLL missing")

    for dll_name in REQUIRED_VC_RUNTIME_DLLS:
        found = _find_first(internal_dir, dll_name)
        require(found is not None, f"{dll_name} found", f"{dll_name} missing：VC++ app-local runtime 缺失")

    qwindows = _find_first(internal_dir, "qwindows.dll")
    require(qwindows is not None, "qwindows.dll found", "qwindows.dll missing：Qt platform plugin missing")

    for dll_name in OPTIONAL_QT_DLLS:
        found = _find_first(internal_dir, dll_name)
        if found is not None:
            messages.append(f"[OK] {dll_name} found")

    for relative in REQUIRED_TOOLS:
        tool = internal_dir / relative
        require(tool.is_file(), relative.as_posix() + " found", f"{relative.as_posix()} missing")

    if not ok:
        messages.append("建议：发布包不完整，请重新打包或完整复制 dist/NetConsole 目录。")
        messages.append("如果关键 DLL 已存在但 Windows 10 仍提示 VCRUNTIME140.dll、MSVCP140.dll 或 QtGui DLL load failed，请安装 Microsoft Visual C++ 2015-2022 Redistributable x64。")
    return RuntimeCheckResult(ok, tuple(messages))


def _find_first(root: Path, pattern: str) -> Path | None:
    return next((path for path in root.rglob(pattern) if path.is_file()), None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check NetConsole packaged runtime dependencies")
    parser.add_argument(
        "app_dir",
        nargs="?",
        default=PROJECT_ROOT / "dist" / "_build" / "pyinstaller" / "dist" / "NetConsole",
        help="PyInstaller dist/NetConsole directory",
    )
    args = parser.parse_args()
    result = check_runtime_deps(Path(args.app_dir))
    for message in result.messages:
        print(message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
