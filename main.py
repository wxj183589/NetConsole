from __future__ import annotations

import os
import sys


if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)

from netconsole.app import run


if __name__ == "__main__":
    raise SystemExit(run())
