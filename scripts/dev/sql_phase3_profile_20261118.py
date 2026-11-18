"""Synthetic Phase 3 SQL profile for AC/FIT-AP, Mesh-Link and Ground ARP.

The harness reuses the Phase 2 performance profiler and only creates isolated
SQLite fixtures under the Workspace test-data container. It never opens a real
data root or starts a collector/device probe.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.dev.sql_read_sharing_profile_20261117 import (
    _audit_connections,
    _measure,
)


def _ac_fixture(root: Path, ap_count: int):
    from tests.support.ac_management_web_fixture import build_ac_management_fixture
    from netconsole.core.database import Database
    from netconsole.services.ac.query_service import AcManagementQueryService, _ReadonlyDatabase
    from netconsole.repositories.ac_repository import AcRepository

    paths, db_path, _files = build_ac_management_fixture(root)
    with Database(db_path).connect() as conn:
        template = dict(conn.execute(
            "SELECT * FROM ac_fit_ap_resources WHERE ap_uuid='ap-online'"
        ).fetchone())
        columns = [str(row[1]) for row in conn.execute("PRAGMA table_info(ac_fit_ap_resources)")]
        columns = [column for column in columns if column != "id"]
        sql = (
            "INSERT INTO ac_fit_ap_resources (" + ", ".join(columns) + ") VALUES ("
            + ", ".join("?" for _ in columns) + ")"
        )
        rows = []
        macs = ["0000-0000-0001"]
        for index in range(2, ap_count + 1):
            item = dict(template)
            item.update({
                "ap_uuid": f"ap-{index:05d}",
                "ap_name": f"AP-{index:05d}",
                "ap_mac": f"0000-{(index // 65536) % 65536:04x}-{index % 65536:04x}",
                "ap_ip": f"10.20.{index // 250}.{index % 250 + 1}",
                "serial_number": f"SYNTH-{index:05d}",
                "serial_identity_key": f"synthetic-{index:05d}",
            })
            rows.append([item.get(column) for column in columns])
            macs.append(str(item["ap_mac"]))
        conn.executemany(sql, rows)
        conn.commit()
    service = AcManagementQueryService(paths)
    repository = AcRepository(_ReadonlyDatabase(db_path))

    def optimized():
        return service.list_ap_details_for_macs("demo", macs)

    def baseline():
        resources = repository.list_fit_ap_resources_with_metadata_for_macs(macs)
        return [
            repository.list_fit_ap_radio_details(
                str(row.get("ap_uuid") or ""), str(row.get("ac_device_uuid") or "")
            )
            for row in resources
        ]

    return paths, db_path, macs, optimized, baseline


def _arp_fixture(root: Path, mr_count: int, ip_count: int):
    from netconsole.repositories.ground_arp_repository import GroundArpRepository

    path = root / "ground.sqlite"
    repository = GroundArpRepository(path, site_id="synthetic")
    mrs = [f"mr-{index:04d}" for index in range(1, mr_count + 1)]
    ips = [f"198.18.{index // 250}.{index % 250 + 1}" for index in range(ip_count)]
    for index, mr_uuid in enumerate(mrs):
        repository.save_identity_relation(
            mr={"id": mr_uuid, "train_id": mr_uuid, "train_no": str(index + 1), "role": "CT"},
            identity_mac=f"00:11:22:33:{index // 256:02x}:{index % 256:02x}",
            alias_type="PRIMARY",
            source="synthetic",
            confirmation_status="CONFIRMED",
            management_ip=ips[index % len(ips)],
            verified_at="2026-11-18T00:00:00+00:00",
        )
    def projection():
        return repository.build_identity_observation_projection(
            mr_uuids=mrs, ip_addresses=ips
        )

    def baseline():
        relations = {
            mr_uuid: repository.find_identity_relations(mr_uuid=mr_uuid)
            for mr_uuid in mrs
        }
        observations = {
            ip: repository.list_observations(ip_address=ip)
            for ip in ips
        }
        return {"relations_by_mr": relations, "observations_by_ip": observations}

    return path, projection, baseline


def _mesh_fixture(root: Path, mr_count: int):
    from tests.support.ac_mesh_link_web_fixture import build_ac_mesh_link_fixture
    from netconsole.core.database import Database
    from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService

    paths, devices_db, mesh_db = build_ac_mesh_link_fixture(root)
    now = "2026-11-18 00:00:00"
    with Database(devices_db).connect() as conn:
        rows = [
            (
                f"synthetic-mr-{index:04d}",
                f"列车{index:04d}-MR-CT",
                f"列车{index:04d}-MR-CT",
                f"198.18.{index // 250}.{index % 250 + 1}",
                now,
                now,
            )
            for index in range(4, mr_count + 1)
        ]
        conn.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, device_vendor, device_type,
                primary_address, created_at, updated_at
            ) VALUES (?, ?, ?, 'H3C', 'MR', ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    with Database(mesh_db).connect() as conn:
        snapshot_id = int(conn.execute(
            "SELECT id FROM vehicle_mr_online_snapshots ORDER BY id LIMIT 1"
        ).fetchone()[0])
        links = []
        for index in range(4, mr_count + 1):
            for role, status in (("primary", "Forwarding"), ("backup", "Standby")):
                links.append((
                    snapshot_id,
                    now,
                    f"列车{index:04d}-MR-CT",
                    f"1000-0000-{index:04x}",
                    f"AP-{role.upper()}",
                    f"0000-{index:04x}-{1 if role == 'primary' else 2:04x}",
                    status,
                    -50 if role == "primary" else -70,
                    str(index),
                    f"{index}车",
                    "CT",
                    "TC1",
                    now,
                ))
        conn.executemany(
            """
            INSERT INTO vehicle_mr_online_links (
                session_id, snapshot_id, ac_time, peer_name, peer_mac,
                local_ap_name, local_mac, status, rssi, train_id,
                train_display_name, car_end, car_end_label, created_at
            ) VALUES ('mesh-session-1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            links,
        )
        conn.execute(
            "UPDATE vehicle_mr_online_snapshots SET link_count=? WHERE id=?",
            (mr_count * 2, snapshot_id),
        )
        conn.commit()
    service = AcMeshLinkQueryService(paths)

    def optimized():
        return service.list_current_links("demo", page_size=1000)

    def baseline():
        # Reproduce the pre-fix identity fallback through the same public
        # request entry and DTO serialization as the optimized path.
        from netconsole.services.ap_identity import ApIdentityQueryService

        with patch.object(
            ApIdentityQueryService,
            "resolve_peer_macs",
            return_value=SimpleNamespace(matches={}),
        ):
            return service.list_current_links("demo", page_size=1000)

    return mesh_db, optimized, baseline


def _explain(path: Path, sql: str, params: tuple[object, ...]) -> list[str]:
    from netconsole.core.database import Database

    connection = Database(path).connect_readonly()
    try:
        return [str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + sql, params)]
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args()
    if args.iterations < 30:
        parser.error("iterations must be at least 30")
    fixture_root = args.fixture_root.resolve()
    fixture_root.mkdir(parents=True, exist_ok=False)
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_DATA_ROOT"] = str((fixture_root / "data-root").resolve())
    result: dict[str, object] = {
        "harness": Path(__file__).name,
        "iterations": args.iterations,
        "data_safety": {
            "synthetic_only": True,
            "PRODUCTION_DATA_MODIFIED": 0,
            "DATABASES_REMOVED": 0,
        },
        "scales": {},
        "notes": [
            "Continuous reads are measured over repeated isolated-fixture calls.",
            "The first sample is reported separately as application cold read; this is not a disk cold start.",
            "Baseline uses the same request entry and DTO response with the pre-fix per-link identity fallback.",
        ],
    }
    with _audit_connections():
        run_root = fixture_root / "run"
        run_root.mkdir(parents=True, exist_ok=False)
        for ap_count in (100, 500, 1000):
            root = run_root / f"ac-{ap_count}"
            _paths, db_path, macs, optimized, baseline = _ac_fixture(root, ap_count)
            result["scales"][f"ac_fit_ap_{ap_count}"] = {
                    "domain": "AC/FIT-AP",
                    "size": {"ac": 2 if ap_count <= 100 else 4 if ap_count <= 500 else 8, "ap": ap_count},
                    "baseline": _measure("ac-baseline", baseline, args.iterations),
                    "optimized_continuous": _measure("ac-optimized", optimized, args.iterations),
                    "query_plan": _explain(
                        db_path,
                        "SELECT * FROM ac_fit_ap_radio_details WHERE ac_device_uuid = ? AND ap_uuid = ?",
                        ("ac-1", "ap-online"),
                    ),
                    "response_scope": {"requested_macs": len(macs)},
            }
        for mr_count, ip_count in ((50, 100), (100, 200), (200, 400)):
            root = run_root / f"arp-{mr_count}"
            db_path, optimized, baseline = _arp_fixture(root, mr_count, ip_count)
            result["scales"][f"arp_{mr_count}_{ip_count}"] = {
                    "domain": "Ground ARP",
                    "size": {"mr": mr_count, "ip": ip_count},
                    "baseline": _measure("arp-baseline", baseline, args.iterations),
                    "optimized_continuous": _measure("arp-optimized", optimized, args.iterations),
                    "query_plan": _explain(
                        db_path,
                        "SELECT * FROM ground_mr_identity_relations WHERE site_id=? AND mr_uuid IN (?, ?)",
                        ("synthetic", "mr-0001", "mr-0002"),
                    ),
            }
        for mr_count in (50, 100, 200):
            root = run_root / f"mesh-{mr_count}"
            db_path, optimized, baseline = _mesh_fixture(root, mr_count)
            result["scales"][f"mesh_{mr_count}"] = {
                "domain": "Mesh-Link",
                "size": {"mr": mr_count, "links": mr_count * 2, "primary_backup": True},
                "baseline": _measure("mesh-baseline", baseline, args.iterations),
                "optimized_continuous": _measure("mesh-optimized", optimized, args.iterations),
                "query_plan": _explain(
                    db_path,
                    "SELECT * FROM vehicle_mr_online_links WHERE snapshot_id=? ORDER BY id",
                    (1,),
                ),
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "scales": list(result["scales"])} , ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
