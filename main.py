from __future__ import annotations

import os
import sys
import faulthandler
import traceback


if os.environ.get("NETCONSOLE_SMOKE_TEST") == "1":
    raise SystemExit(0)

from netconsole.core.runtime_environment import app_root


BASE_DIR = str(app_root())


def _runtime_log_dir() -> str:
    log_dir = os.path.join(BASE_DIR, "runtime", "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


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


if __name__ == "__main__":
    _enable_faulthandler()
    try:
        if len(sys.argv) >= 2 and sys.argv[1] == "--export-worker":
            from netconsole.export_worker import main as run_export_worker

            raise SystemExit(run_export_worker(sys.argv[2:]))
        if len(sys.argv) >= 3 and sys.argv[1] == "--export-worker-job":
            from netconsole.export_worker import main as run_export_worker

            raise SystemExit(run_export_worker(["--job", sys.argv[2]]))
        if len(sys.argv) >= 2 and sys.argv[1] == "--background-worker":
            from netconsole.background_worker import main as run_background_worker

            raise SystemExit(run_background_worker(sys.argv[2:]))
        if os.environ.get("NETCONSOLE_RUNTIME_SMOKE_TEST") == "1":
            from netconsole.core.bootstrap import create_demo_context

            context = create_demo_context()
            _write_runtime_smoke_log(context)
            print(f"[OK] app_root={context.paths.app_root}")
            print(f"[OK] data_dir={context.paths.data_dir}")
            print(f"[OK] runtime_dir={context.paths.runtime_dir}")
            print(f"[OK] logs_dir={context.paths.logs_dir}")
            raise SystemExit(0)
        if os.environ.get("NETCONSOLE_TOOL_SMOKE_TEST") == "1":
            from netconsole.services.tool_smoke_test import run_tool_smoke_tests

            for result in run_tool_smoke_tests():
                first_line = next((line.strip() for line in result.output.splitlines() if line.strip()), "OK")
                print(f"[OK] {result.name}: {result.path} :: {first_line}")
            raise SystemExit(0)
        from netconsole.app import run

        raise SystemExit(run())
    except SystemExit:
        raise
    except BaseException:
        with open(os.path.join(_runtime_log_dir(), "startup_error.log"), "a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc())
            handle.write("\n")
        raise
