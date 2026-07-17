from __future__ import annotations

import os
import sys
import faulthandler
import traceback
from pathlib import Path

from netconsole.core.runtime_environment import app_root
from netconsole.core.paths import PathResolver


BASE_DIR = app_root()


def _runtime_log_dir() -> str:
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


def _verify_release_contract() -> None:
    from netconsole.core.feature_flags import FeatureGate
    from netconsole.core.resources import runtime_base_dir
    from netconsole.core.version import APP_TITLE_DISPLAY, REPOSITORY_WEB_URLS

    if APP_TITLE_DISPLAY != "NetConsole v1.3.9 by WXJ":
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
    gate = FeatureGate(BASE_DIR)
    for feature_id in ("module.feature_switch", "system.feature_flags"):
        if gate.is_visible(feature_id) or gate.is_enabled(feature_id):
            raise RuntimeError(f"打包版暴露了开发功能：{feature_id}")
    forbidden_ipop = [
        path
        for path in Path(BASE_DIR).rglob("*")
        if path.name.casefold() == "ipop.exe" or "ipop" in {part.casefold() for part in path.relative_to(BASE_DIR).parts}
    ]
    if forbidden_ipop:
        raise RuntimeError("发布包不得包含 IPOP.EXE 或 tools/windows-x64/ipop 目录")


def main() -> int:
    if os.environ.get("NETCONSOLE_SMOKE_TEST") == "1":
        return 0
    _enable_faulthandler()
    try:
        if len(sys.argv) >= 2 and sys.argv[1] == "--qt-probe":
            from netconsole.launcher.qt_probe import run_qt_probe

            component = sys.argv[2] if len(sys.argv) >= 3 else "widgets"
            return run_qt_probe(component)
        if len(sys.argv) >= 2 and sys.argv[1] == "--export-worker":
            from netconsole.export_worker import main as run_export_worker

            return run_export_worker(sys.argv[2:])
        if len(sys.argv) >= 3 and sys.argv[1] == "--export-worker-job":
            from netconsole.export_worker import main as run_export_worker

            return run_export_worker(["--job", sys.argv[2]])
        if len(sys.argv) >= 2 and sys.argv[1] == "--background-worker":
            from netconsole.background_worker import main as run_background_worker

            return run_background_worker(sys.argv[2:])
        if len(sys.argv) >= 2 and sys.argv[1] == "--admin-network-manager":
            from netconsole.app import run

            return run()
        if len(sys.argv) >= 2 and sys.argv[1] == "--web-shell":
            from apps.desktop.web_shell import run_web_shell

            return run_web_shell()
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
