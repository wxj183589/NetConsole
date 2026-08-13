from __future__ import annotations

import os
import sys
import argparse
import faulthandler
import traceback
from pathlib import Path

from netconsole.core.runtime_environment import app_root, is_packaged_runtime


BASE_DIR = app_root()
MANAGED_BACKEND_STANDALONE_EXIT_CODE = 2
MANAGED_BACKEND_STANDALONE_MESSAGE = (
    "NetConsoleBackend.exe 是 NetConsole 桌面程序的受管后端，不能单独运行。\n"
    "请启动 NetConsole.exe 或使用正式安装程序。"
)


def _runtime_log_dir() -> str:
    from netconsole.core.paths import PathResolver

    log_dir = PathResolver().logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir)


def _enable_faulthandler() -> None:
    try:
        if sys.stderr is not None:
            faulthandler.enable()
            return
        fault_log = open(os.path.join(_runtime_log_dir(), "faulthandler.log"), "a", encoding="utf-8")
        faulthandler.enable(file=fault_log)
    except Exception:
        pass


def _write_runtime_smoke_log(context) -> None:
    try:
        log_path = os.path.join(_runtime_log_dir(), "runtime_smoke.log")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(f"app_root={context.paths.app_root}\n")
            handle.write(f"data_dir={context.paths.data_dir}\n")
            handle.write(f"runtime_dir={context.paths.runtime_dir}\n")
            handle.write(f"logs_dir={context.paths.logs_dir}\n")
    except Exception:
        pass


def _reject_managed_backend_standalone_launch() -> int:
    try:
        from netconsole.core import app_logger

        app_logger.log_error("MANAGED_BACKEND_STANDALONE_LAUNCH", MANAGED_BACKEND_STANDALONE_MESSAGE)
    except Exception:
        pass
    diagnostics = sys.stderr or getattr(sys, "__stderr__", None)
    if diagnostics is not None:
        try:
            print(MANAGED_BACKEND_STANDALONE_MESSAGE, file=diagnostics)
        except Exception:
            pass
    _show_managed_backend_standalone_message()
    return MANAGED_BACKEND_STANDALONE_EXIT_CODE


def _show_managed_backend_standalone_message() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            MANAGED_BACKEND_STANDALONE_MESSAGE,
            "NetConsole",
            0x00000010,
        )
    except Exception:
        pass


def _verify_release_contract() -> None:
    from netconsole.core.feature_flags import PACKAGED_CORE_FEATURE_IDS, FeatureGate
    from netconsole.core.feature_registry import FeatureStatus, list_features
    from netconsole.core.resources import runtime_base_dir
    from netconsole.core.version import APP_TITLE_DISPLAY, REPOSITORY_WEB_URLS

    if APP_TITLE_DISPLAY != "NetConsole v1.4.9 by WXJ":
        raise RuntimeError(f"发布标题不正确：{APP_TITLE_DISPLAY}")
    if not REPOSITORY_WEB_URLS or any(not url.startswith("https://") for url in REPOSITORY_WEB_URLS):
        raise RuntimeError(f"关于页仓库地址必须全部使用 HTTPS：{REPOSITORY_WEB_URLS}")
    assets = runtime_base_dir() / "netconsole" / "assets"
    required_assets = (
        assets / "open_source_notices.json",
        assets / "THIRD_PARTY_COMPONENTS.md",
        assets / "IPOP_v4.1_notice.md",
    )
    missing_assets = [str(path) for path in required_assets if not path.is_file()]
    if missing_assets:
        raise RuntimeError("发布包缺少第三方说明：" + ", ".join(missing_assets))
    gate = FeatureGate(BASE_DIR, packaged_runtime=True)
    for feature_id in ("internal.feature_switch",):
        if gate.is_visible(feature_id) or gate.is_enabled(feature_id):
            raise RuntimeError(f"打包版暴露了开发功能：{feature_id}")
    for feature_id in PACKAGED_CORE_FEATURE_IDS:
        if not gate.is_visible(feature_id) or not gate.is_enabled(feature_id):
            raise RuntimeError(f"打包版缺少核心生产功能：{feature_id}")
    for item in list_features():
        if item.internal_only or item.status in {
            FeatureStatus.DISABLED,
            FeatureStatus.HIDDEN,
            FeatureStatus.DEVELOPMENT,
        }:
            if gate.is_visible(item.feature_id) or gate.is_enabled(item.feature_id):
                raise RuntimeError(f"打包版暴露了受限功能：{item.feature_id}")
    forbidden_ipop = [
        path
        for path in Path(BASE_DIR).rglob("*")
        if path.name.casefold() == "ipop.exe" or "ipop" in {part.casefold() for part in path.relative_to(BASE_DIR).parts}
    ]
    if forbidden_ipop:
            raise RuntimeError("发布包不得包含 IPOP.EXE 或 tools/windows-x64/ipop 目录")


def _validate_data_root_from_installer(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="NetConsoleBackend.exe --validate-data-root")
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--installation-root", type=Path)
    values = parser.parse_args(arguments)
    from netconsole.core.data_root_configuration import prepare_installation_data_root

    prepare_installation_data_root(values.data_root, installation_root=values.installation_root)
    return 0


def _migrate_data_root_from_installer(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="NetConsoleBackend.exe --migrate-data-root")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--installation-root", type=Path)
    values = parser.parse_args(arguments)
    from netconsole.core.backend_instance_lock import BackendInstanceLock
    from netconsole.core.data_root_configuration import validate_installation_data_root
    from netconsole.core.paths import PathResolver
    from netconsole.services.site_storage import DataRootApplicationService

    # The installer owns the pointer update.  This helper only migrates a
    # configured source after proving the selected target is safe.
    os.environ["NETCONSOLE_DATA_ROOT"] = str(values.source)
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "desktop-packaged"
    validate_installation_data_root(values.target, installation_root=values.installation_root)
    paths = PathResolver()
    with BackendInstanceLock(paths):
        DataRootApplicationService(paths).migrate(values.target)
    return 0


def _collect_host_profile_from_installer(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="NetConsoleBackend.exe --collect-host-profile")
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=4.0)
    values = parser.parse_args(arguments)
    from netconsole.core.runtime_profile import collect_and_write_host_environment_profile

    target = values.data_root / "runtime" / "environment" / "host-profile.json"
    collect_and_write_host_environment_profile(
        target,
        data_root=values.data_root,
        timeout_seconds=min(max(values.timeout_seconds, 0.1), 15.0),
    )
    return 0


def _set_runtime_performance_mode_from_installer(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="NetConsoleBackend.exe --set-runtime-performance-mode"
    )
    parser.add_argument("data_root", type=Path)
    parser.add_argument("mode", choices=("standard", "server_unattended"))
    values = parser.parse_args(arguments)
    from netconsole.core.paths import PathResolver
    from netconsole.core.settings import SettingsStore

    SettingsStore(PathResolver(data_root=values.data_root)).set_value(
        "app/runtime_performance_mode", values.mode
    )
    return 0


def main() -> int:
    if os.environ.get("NETCONSOLE_SMOKE_TEST") == "1":
        return 0
    _enable_faulthandler()
    try:
        if len(sys.argv) >= 2 and sys.argv[1] == "--electron-backend":
            from netconsole.backend.electron_runtime import main as run_electron_backend

            return run_electron_backend(sys.argv[2:])
        if len(sys.argv) >= 2 and sys.argv[1] == "--validate-data-root":
            return _validate_data_root_from_installer(sys.argv[2:])
        if len(sys.argv) >= 2 and sys.argv[1] == "--migrate-data-root":
            return _migrate_data_root_from_installer(sys.argv[2:])
        if len(sys.argv) >= 2 and sys.argv[1] == "--collect-host-profile":
            return _collect_host_profile_from_installer(sys.argv[2:])
        if len(sys.argv) >= 2 and sys.argv[1] == "--set-runtime-performance-mode":
            return _set_runtime_performance_mode_from_installer(sys.argv[2:])
        if len(sys.argv) >= 2 and sys.argv[1] == "--export-worker":
            from netconsole.export_worker import main as run_export_worker

            return run_export_worker(sys.argv[2:])
        if len(sys.argv) >= 3 and sys.argv[1] == "--export-worker-job":
            from netconsole.export_worker import main as run_export_worker

            return run_export_worker(["--job", sys.argv[2]])
        if len(sys.argv) >= 2 and sys.argv[1] == "--background-worker":
            from netconsole.background_worker import main as run_background_worker

            return run_background_worker(sys.argv[2:])
        if os.environ.get("NETCONSOLE_RUNTIME_SMOKE_TEST") == "1":
            from netconsole.core.bootstrap import create_demo_context

            context = create_demo_context()
            _write_runtime_smoke_log(context)
            print(f"[OK] app_root={context.paths.app_root}")
            print(f"[OK] data_dir={context.paths.data_dir}")
            print(f"[OK] runtime_dir={context.paths.runtime_dir}")
            print(f"[OK] logs_dir={context.paths.logs_dir}")
            return 0
        if os.environ.get("NETCONSOLE_TOOL_SMOKE_TEST") == "1":
            from netconsole.services.tool_smoke_test import run_tool_smoke_tests

            for result in run_tool_smoke_tests():
                first_line = next((line.strip() for line in result.output.splitlines() if line.strip()), "OK")
                print(f"[OK] {result.name}: {result.path} :: {first_line}")
            return 0
        if os.environ.get("NETCONSOLE_RELEASE_CONTRACT_SMOKE_TEST") == "1":
            _verify_release_contract()
            return 0
        if is_packaged_runtime():
            return _reject_managed_backend_standalone_launch()
        if not sys.argv[1:]:
            from netconsole.launcher.electron_desktop import launch_electron_desktop

            return launch_electron_desktop()
        from netconsole.launcher.launcher import launch

        return launch(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException:
        with open(os.path.join(_runtime_log_dir(), "startup_error.log"), "a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc())
            handle.write("\n")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
