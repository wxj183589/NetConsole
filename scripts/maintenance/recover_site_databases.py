"""Explicit maintenance entry for backup-before-remove site recovery."""

from __future__ import annotations

import argparse
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.maintenance.site_database_recovery import (
    run_authorized_site_database_recovery,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--confirm-remove", action="store_true")
    args = parser.parse_args()
    if not args.confirm_remove:
        parser.error("--confirm-remove is required for database removal")
    backups = run_authorized_site_database_recovery(
        PathResolver(data_root=Path(args.data_root)),
        authorization=args.authorization,
    )
    print(f"backed up and removed {len(backups)} site database file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
