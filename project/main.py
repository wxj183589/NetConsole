from __future__ import annotations

import sys
import os
from pathlib import Path


if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)

if not getattr(sys, "frozen", False):
    ROOT = Path(BASE_DIR).resolve().parent
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    if os.environ.get("NETCONSOLE_SMOKE_TEST") == "1":
        raise SystemExit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "--export-worker":
        from netconsole.export_worker import main as run_export_worker

        raise SystemExit(run_export_worker(sys.argv[2:]))
    if len(sys.argv) >= 3 and sys.argv[1] == "--export-worker-job":
        from netconsole.export_worker import main as run_export_worker

        raise SystemExit(run_export_worker(["--job", sys.argv[2]]))
    if len(sys.argv) >= 2 and sys.argv[1] == "--background-worker":
        from netconsole.background_worker import main as run_background_worker

        raise SystemExit(run_background_worker(sys.argv[2:]))
    from netconsole.app import run

    raise SystemExit(run())
