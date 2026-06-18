from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT_RELEASE = Path(__file__).resolve().parents[1] / "release.py"
SPEC = importlib.util.spec_from_file_location("_netconsole_release", ROOT_RELEASE)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"cannot load release module from {ROOT_RELEASE}")

_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = _module
SPEC.loader.exec_module(_module)

for _name in dir(_module):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_module, _name)

