from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from netconsole.core.database import Database  # noqa: E402
from netconsole.core.runtime_environment import test_data_root_base, write_data_environment  # noqa: E402
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode  # noqa: E402
from netconsole.services.ap_identity import ApIdentityQueryService  # noqa: E402
from netconsole.services.production_database_maintenance import PRODUCTION_SITE_ALLOWLIST  # noqa: E402


SITE_ID = "sxl1"
SCENARIOS = frozenset({"missing", "stale"})
DATABASE_RELATIVE_PATH = Path("sites") / SITE_ID / "db" / "devices.db"
STATE_RELATIVE_PATH = Path("runtime") / "temp" / "ap-identity-startup-fixture.json"
SOURCE_TABLES = (
    "ap_extension_points",
    "ac_fit_ap_resources",
    "ac_fit_ap_metadata",
    "devices",
    "device_facts",
    "ap_identity_radio_evidence",
    "ac_fit_ap_radio_history",
    "device_lldp_neighbors",
    "ap_entities",
    "ac_fit_ap_optical",
    "trackside_ap_view_cache",
    "ap_identity_source_state",
)


def prepare_fixture(
    data_root: Path,
    scenario: str,
    *,
    repository_root: Path = PROJECT_ROOT,
) -> dict[str, object]:
    root = _validate_fixture_root(data_root, repository_root=repository_root)
    _validate_scenario(scenario)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"AP Identity startup fixture root must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)

    _write_runtime_marker(root)
    _write_production_config(root)
    database_path = root / DATABASE_RELATIVE_PATH
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(database_path)
    database.initialize()
    _insert_source_row(database_path)

    service = ApIdentityQueryService(database)
    if scenario == "stale":
        if service.ensure_index("package_smoke_fixture") is None:
            raise RuntimeError("stale fixture could not build its initial AP Identity index")
        _make_source_revision_stale(database_path)

    revision_state = service.revision_state()
    expected_status = "missing" if scenario == "missing" else "stale"
    if revision_state.status != expected_status:
        raise RuntimeError(
            f"fixture did not produce {expected_status} AP Identity state: "
            f"{revision_state}"
        )
    source_snapshot = _source_snapshot(database_path)
    state_path = root / STATE_RELATIVE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scenario": scenario,
                "database": DATABASE_RELATIVE_PATH.as_posix(),
                "source_snapshot": source_snapshot,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "scenario": scenario,
        "database": str(database_path),
        "state": expected_status,
        "source_revision": revision_state.current_source_revision,
    }


def verify_fixture(
    data_root: Path,
    *,
    repository_root: Path = PROJECT_ROOT,
) -> dict[str, object]:
    root = _validate_fixture_root(data_root, repository_root=repository_root)
    state_path = root / STATE_RELATIVE_PATH
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"AP Identity fixture state is invalid: {state_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError(f"AP Identity fixture state schema is invalid: {state_path}")
    database_path = root / DATABASE_RELATIVE_PATH
    if payload.get("database") != DATABASE_RELATIVE_PATH.as_posix():
        raise RuntimeError("AP Identity fixture database path changed")
    expected_snapshot = payload.get("source_snapshot")
    actual_snapshot = _source_snapshot(database_path)
    if actual_snapshot != expected_snapshot:
        raise RuntimeError("AP Identity startup changed source rows")

    with closing(sqlite3.connect(database_path)) as connection:
        index_state = connection.execute(
            """
            SELECT revision, source_revision
            FROM ap_identity_index_state
            WHERE site_id = 'current'
            """
        ).fetchone()
        source_state = connection.execute(
            """
            SELECT revision
            FROM ap_identity_source_state
            WHERE site_id = 'current'
            """
        ).fetchone()
        source_row_count = int(
            connection.execute("SELECT COUNT(*) FROM ap_extension_points").fetchone()[0]
        )
    if index_state is None or source_state is None:
        raise RuntimeError("AP Identity startup did not leave current revision state")
    index_revision, indexed_source_revision = map(int, index_state)
    current_source_revision = int(source_state[0])
    if index_revision <= 0:
        raise RuntimeError(f"AP Identity index revision is not ready: {index_revision}")
    if indexed_source_revision != current_source_revision:
        raise RuntimeError(
            "AP Identity index/source revisions are not aligned: "
            f"indexed={indexed_source_revision} current={current_source_revision}"
        )
    if source_row_count <= 0:
        raise RuntimeError("AP Identity fixture source rows disappeared")
    revision_state = ApIdentityQueryService(Database(database_path)).revision_state()
    if revision_state.status != "ready":
        raise RuntimeError(f"AP Identity index is not ready after startup: {revision_state}")
    return {
        "status": revision_state.status,
        "index_revision": index_revision,
        "source_revision": current_source_revision,
        "source_rows": source_row_count,
    }


def _validate_fixture_root(data_root: Path, *, repository_root: Path) -> Path:
    root = Path(data_root).expanduser().resolve()
    base = test_data_root_base(repository_root=Path(repository_root).resolve())
    if root == base or not root.is_relative_to(base):
        raise ValueError(
            f"AP Identity startup fixture must be inside {base}\\<run-id>: {root}"
        )
    if root == PROJECT_ROOT or root.is_relative_to(PROJECT_ROOT):
        raise ValueError(f"AP Identity startup fixture must not be inside source tree: {root}")
    return root


def _validate_scenario(scenario: str) -> None:
    if scenario not in SCENARIOS:
        allowed = ", ".join(sorted(SCENARIOS))
        raise ValueError(f"scenario must be one of {allowed}: {scenario}")


def _write_runtime_marker(root: Path) -> None:
    write_data_environment(
        root,
        DataEnvironmentInfo(
            DataEnvironmentMode.PRODUCTION,
            created_from="package-smoke-ap-identity-startup",
            readonly_warning=True,
        ),
    )


def _write_production_config(root: Path) -> None:
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": SITE_ID,
                        "display_name": PRODUCTION_SITE_ALLOWLIST[SITE_ID],
                        "relative_path": f"sites/{SITE_ID}",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (config / "application.json").write_text(
        json.dumps(
            {
                "current_site": SITE_ID,
                "active_site_id": SITE_ID,
                "recent_sites": [SITE_ID],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _insert_source_row(database_path: Path) -> None:
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, station_id, station_name, section_id, section_name,
                ap_point_code, ap_name, ap_vendor, ap_mac_norm, ap_mac_display,
                created_at, updated_at
            ) VALUES (
                'sxl1', 'station-1', 'Station 1', 'section-1', 'Section 1',
                'AP-001', 'AP 001', 'H3C', '487397cce9af', '4873-97cc-e9af',
                '2026-09-22T00:00:00Z', '2026-09-22T00:00:00Z'
            )
            """
        )
        connection.commit()


def _make_source_revision_stale(database_path: Path) -> None:
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            """
            UPDATE ap_extension_points
            SET ap_name = ?, updated_at = ?
            WHERE id = 1
            """,
            ("AP 001 changed", "2026-09-22T00:01:00Z"),
        )
        connection.commit()


def _source_snapshot(database_path: Path) -> list[list[object]]:
    with closing(sqlite3.connect(database_path)) as connection:
        return [
            [
                table,
                [list(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")],
            ]
            for table in SOURCE_TABLES
        ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the packaged Production AP Identity startup fixture")
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS))
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            if args.scenario is None:
                parser.error("prepare requires --scenario")
            result = prepare_fixture(args.data_root, args.scenario)
        else:
            result = verify_fixture(args.data_root)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"AP Identity startup fixture failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
