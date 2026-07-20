from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver


def build_ac_management_fixture(
    tmp_path: Path,
) -> tuple[PathResolver, Path, dict[str, Path]]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    db_path = paths.site_db_path("demo")
    database = Database(db_path)
    database.initialize()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with database.connect() as conn:
        conn.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, device_vendor, device_type,
                primary_address, created_at, updated_at
            ) VALUES (?, ?, ?, 'H3C', ?, ?, ?, ?)
            """,
            [
                ("ac-1", "测试 AC", "AC-TEST", "AC", "10.0.0.1", now, now),
                ("switch-1", "接入交换机", "SW-TEST", "SWITCH", "10.0.0.2", now, now),
            ],
        )
        conn.execute(
            """
            INSERT INTO ac_ap_summary (
                ac_device_uuid, total_aps, online_aps, offline_aps, model,
                software_version, collected_at, updated_at
            ) VALUES ('ac-1', 3, 2, 1, 'WX-Test', 'Version Test', ?, ?)
            """,
            (now, now),
        )
        conn.executemany(
            """
            INSERT INTO ac_fit_ap_resources (
                ac_device_uuid, ap_uuid, ap_name, ap_ip, ap_mac, model,
                serial_number, state, state_display, site, rid1_channel,
                rid1_bandwidth, rid1_tx_power, rid1_bbssid, rid1_status,
                rid1_mode, rid1_band, rid1_usage, rid1_clients, rid2_channel,
                rid2_bandwidth, rid2_tx_power, rid2_bbssid, rid2_status,
                rid2_mode, rid2_band, rid2_usage, rid2_clients,
                connection_ip, connection_state, connection_time,
                lldp_neighbor_name, lldp_neighbor_interface, lldp_match_status,
                collected_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'WA-Test', ?, ?, ?, ?, ?, ?, ?, ?, 'Up',
                      '802.11n', '5GHz', '12', 3, ?, ?, ?, ?, 'Up',
                      '802.11n', '2.4GHz', '8', 1, ?, 'Run', '05-06 09:47:44',
                      '接入交换机', ?, 'matched', ?, ?)
            """,
            [
                (
                    "ac-1",
                    "ap-online",
                    "AP-Online",
                    "10.0.1.1",
                    "0000-0000-0001",
                    "SECRET-SN-1",
                    "R/M",
                    "运行(主)",
                    "车站A",
                    "1",
                    "80",
                    "15",
                    "0000-0001-0001",
                    "36",
                    "80",
                    "17",
                    "0000-0001-0002",
                    "10.0.1.1",
                    "GigabitEthernet1/0/1",
                    now,
                    now,
                ),
                (
                    "ac-1",
                    "ap-offline",
                    "AP-Offline",
                    "10.0.1.2",
                    "0000-0000-0002",
                    "SECRET-SN-2",
                    "Idle",
                    "Idle",
                    "车站B",
                    "6",
                    "40",
                    "13",
                    "0000-0002-0001",
                    "44",
                    "80",
                    "16",
                    "0000-0002-0002",
                    "10.0.1.2",
                    "GigabitEthernet1/0/2",
                    now,
                    now,
                ),
                (
                    "ac-1",
                    "ap-unauth",
                    "AP-Unauth",
                    "10.0.1.3",
                    "0000-0000-0003",
                    "SECRET-SN-3",
                    "R/M",
                    "运行(主)",
                    "车站A",
                    "11",
                    "40",
                    "12",
                    "0000-0003-0001",
                    "149",
                    "80",
                    "14",
                    "0000-0003-0002",
                    "10.0.1.3",
                    "GigabitEthernet1/0/3",
                    now,
                    now,
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO ac_fit_ap_metadata (
                ap_uuid, ap_name, site_name, belong_type, belong_section,
                mileage, direction, created_at, updated_at
            ) VALUES (?, ?, ?, 'section', ?, ?, ?, ?, ?)
            """,
            [
                (
                    "ap-online",
                    "AP-Online",
                    "车站A",
                    "A-B 区间",
                    "K1+100",
                    "上行",
                    now,
                    now,
                ),
                (
                    "ap-offline",
                    "AP-Offline",
                    "车站B",
                    "B-C 区间",
                    "K2+200",
                    "下行",
                    now,
                    now,
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO ac_fit_ap_optical (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, ap_ip,
                neighbor_device_name, neighbor_interface, rx_power, tx_power,
                temperature, voltage, bias_current, rx_low_alarm,
                rx_low_warning, status, collected_at, updated_at
            ) VALUES ('ac-1', ?, ?, ?, ?, '接入交换机', ?, ?, ?, '35 C', '3.3 V', '5 mA', '-19 dBm', '-17 dBm', 'success', ?, ?)
            """,
            [
                (
                    "ap-online",
                    "AP-Online",
                    "0000-0000-0001",
                    "10.0.1.1",
                    "GigabitEthernet1/0/1",
                    "-10 dBm",
                    "-3 dBm",
                    now,
                    now,
                ),
                (
                    "ap-offline",
                    "AP-Offline",
                    "0000-0000-0002",
                    "10.0.1.2",
                    "GigabitEthernet1/0/2",
                    "-25 dBm",
                    "-3 dBm",
                    now,
                    now,
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO ac_fit_ap_unauthenticated (
                ac_device_uuid, ap_name, apid, state, state_display, model,
                serial_number, inferred_ap_mac, collected_at, updated_at
            ) VALUES ('ac-1', 'AP-Unauth', '3', 'R/M', '运行(主)', 'WA-Test',
                      'SECRET-SN-3', '0000-0000-0003', ?, ?)
            """,
            (now, now),
        )
        conn.executemany(
            """
            INSERT INTO device_interfaces (
                device_uuid, interface_name, link_status, port_status, pvid,
                vlan, collected_at, updated_at
            ) VALUES ('switch-1', ?, 'UP', 'UP', '100', '100', ?, ?)
            """,
            [("GigabitEthernet1/0/1", now, now), ("GigabitEthernet1/0/2", now, now)],
        )
        conn.executemany(
            """
            INSERT INTO device_optical_modules (
                device_uuid, interface_name, rx_power, tx_power, rx_low_alarm,
                rx_low_warning, status, collected_at, updated_at
            ) VALUES ('switch-1', ?, ?, '-3 dBm', '-19 dBm', '-17 dBm', 'success', ?, ?)
            """,
            [
                ("GigabitEthernet1/0/1", "-40 dBm", now, now),
                ("GigabitEthernet1/0/2", "-25 dBm", now, now),
            ],
        )

        snapshot_dir = (
            paths.site_dir("demo") / "files" / "config_center" / "snapshots" / "ac-1"
        )
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        running = snapshot_dir / "running.txt"
        saved = snapshot_dir / "saved.txt"
        diff = snapshot_dir / "diff.txt"
        running.write_text(
            "header\n#\nsysname AC-TEST\ninterface Vlan-interface1\n ip address 10.0.0.1\n#\nreturn\n<AC-TEST>\n",
            encoding="utf-8",
        )
        saved.write_text(
            "header\n#\nsysname AC-TEST\ninterface Vlan-interface1\n ip address 10.0.0.9\n#\nreturn\n<AC-TEST>\n",
            encoding="utf-8",
        )
        diff.write_text("--- saved\n+++ running\n", encoding="utf-8")
        for snapshot_type, path in (
            ("running", running),
            ("saved", saved),
            ("diff", diff),
        ):
            relative = path.relative_to(paths.site_dir("demo")).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            conn.execute(
                """
                INSERT INTO config_snapshots (
                    device_uuid, timestamp, type, file_path, hash, created_at
                ) VALUES ('ac-1', '20260714_120000', ?, ?, ?, ?)
                """,
                (snapshot_type, relative, digest, now),
            )
        conn.commit()
    with database.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return paths, db_path, {"running": running, "saved": saved, "diff": diff}
