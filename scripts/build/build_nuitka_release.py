from __future__ import annotations

import sys

from scripts.build.build_release import main as build_main


def main() -> int:
    if "--backend" not in sys.argv:
        sys.argv[1:1] = ["--backend", "nuitka"]
    return build_main()


if __name__ == "__main__":
    raise SystemExit(main())
