from __future__ import annotations

from contextlib import closing
from pathlib import Path

from ac_management_web_fixture import build_ac_management_fixture
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore


def build_ac_mesh_link_fixture(tmp_path: Path) -> tuple[PathResolver, Path, Path]:
    paths, devices_db, _files = build_ac_management_fixture(tmp_path)
    now = "2026-07-14 12:00:00"
    database = Database(devices_db)
    with closing(database.connect()) as conn:
        conn.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, device_vendor, device_type,
                primary_address, created_at, updated_at
            ) VALUES (?, ?, ?, 'H3C', 'MR', ?, ?, ?)
            """,
            [
                ("mr-01-ct", "列车01-MR-CT", "列车01-MR-CT", "10.12.1.11", now, now),
                ("mr-02-ct", "列车02-MR-CT", "列车02-MR-CT", "10.12.2.11", now, now),
                ("mr-03-ct", "列车03-MR-CT", "列车03-MR-CT", "10.12.3.11", now, now),
            ],
        )
        ac_id = int(conn.execute("SELECT id FROM devices WHERE device_uuid = 'ac-1'").fetchone()[0])
        conn.commit()

    store = VehicleMrOnlineStore(paths, "demo")
    with closing(store.connect()) as conn:
        conn.execute(
            """
            INSERT INTO vehicle_mr_online_sessions (
                session_id, ac_device_id, ac_name, started_at, status, created_at, updated_at
            ) VALUES ('mesh-session-1', ?, '测试 AC', ?, '运行中', ?, ?)
            """,
            (ac_id, now, now, now),
        )
        cursor = conn.execute(
            """
            INSERT INTO vehicle_mr_online_snapshots (
                session_id, sample_index, ac_time, local_time, command_duration_ms,
                link_count, parse_status, error_message, created_at
            ) VALUES ('mesh-session-1', 1, ?, ?, 120, 3, 'ok', '', ?)
            """,
            (now, now, now),
        )
        snapshot_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO vehicle_mr_online_links (
                session_id, snapshot_id, ac_time, peer_name, peer_mac,
                local_ap_name, local_mac, status, rssi, train_id,
                train_display_name, train_no, car_end, car_end_label,
                matched_station, matched_ap_name, match_method, created_at
            ) VALUES ('mesh-session-1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CT', 'TC1', ?, ?, ?, ?)
            """,
            [
                (
                    snapshot_id,
                    now,
                    "列车01-MR-CT",
                    "1000-0000-0001",
                    "",
                    "0000-0001-0001",
                    "Forwarding",
                    -52,
                    "01",
                    "01车",
                    "01",
                    "车站A",
                    "AP-Online",
                    "ap_name_exact",
                    now,
                ),
                (
                    snapshot_id,
                    now,
                    "列车02-MR-CT",
                    "1000-0000-0002",
                    "AP-Offline",
                    "",
                    "Down",
                    -88,
                    "02",
                    "02车",
                    "02",
                    "车站B",
                    "AP-Offline",
                    "ap_name_exact",
                    now,
                ),
                (
                    snapshot_id,
                    now,
                    "列车99-MR-CT",
                    "1000-0000-0099",
                    "AP-Unknown",
                    "9999-9999-9999",
                    "Forwarding",
                    -70,
                    "99",
                    "99车",
                    "99",
                    "",
                    "",
                    "unmatched",
                    now,
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO vehicle_mr_train_current_state (
                session_id, train_id, train_display_name, train_no, is_registered,
                status, current_station, last_ac_time, last_seen_at,
                tc1_seen, tc1_station, tc1_ap_name, tc1_rssi, tc1_last_seen_at,
                online_policy, status_reason, updated_at
            ) VALUES ('mesh-session-1', ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'auto', ?, ?)
            """,
            [
                ("01", "01车", "01", "在线", "车站A", now, now, 1, "车站A", "AP-Online", -52, now, "活动链路", now),
                ("02", "02车", "02", "离线", "车站B", now, now, 1, "车站B", "AP-Offline", -88, now, "链路断开", now),
                ("03", "03车", "03", "离线", "车站C", now, now, 1, "车站C", "AP-History", -80, now, "快照未出现", now),
            ],
        )
        conn.execute(
            """
            INSERT INTO vehicle_mr_train_pass_events (
                session_id, train_id, train_display_name, train_no, car_end,
                car_end_label, event_time, event_type, status, station,
                ap_name, rssi, created_at
            ) VALUES ('mesh-session-1', '01', '01车', '01', 'CT', 'TC1',
                      ?, 'link_seen', 'Forwarding', '车站A', 'AP-Online', -52, ?)
            """,
            (now, now),
        )
        conn.commit()
    ApIdentityQueryService(database).rebuild_index("test_fixture_ready")
    return paths, devices_db, store.db_path


__all__ = ["build_ac_mesh_link_fixture"]
