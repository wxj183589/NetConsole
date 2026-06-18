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

from netconsole.app import run


if __name__ == "__main__":
    if os.environ.get("NETCONSOLE_SMOKE_TEST") == "1":
        raise SystemExit(0)
    raise SystemExit(run())
