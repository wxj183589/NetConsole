from __future__ import annotations

import sys

from netconsole.export_worker import main, run_job

__all__ = ["main", "run_job"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
