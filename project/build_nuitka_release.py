from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project.build_release import main as build_main


def main() -> int:
    if "--backend" not in sys.argv:
        sys.argv[1:1] = ["--backend", "nuitka"]
    return build_main()


if __name__ == "__main__":
    raise SystemExit(main())
