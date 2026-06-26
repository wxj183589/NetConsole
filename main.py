from __future__ import annotations

import os
import sys


if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)

from netconsole.app import run


if __name__ == "__main__":
    if os.environ.get("NETCONSOLE_RUNTIME_SMOKE_TEST") == "1":
        from netconsole.core.bootstrap import create_demo_context

        context = create_demo_context()
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
    if os.environ.get("NETCONSOLE_SMOKE_TEST") == "1":
        raise SystemExit(0)
    raise SystemExit(run())
