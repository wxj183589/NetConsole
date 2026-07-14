from __future__ import annotations

import json
from pathlib import Path

from ac_management_web_fixture import build_ac_management_fixture
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver


def build_rail_transit_base_data_fixture(tmp_path: Path) -> tuple[PathResolver, Path]:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    now = "2026-07-14T12:00:00"
    database = Database(db_path)
    with database.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO device_groups (site_id, name, sort_order, created_at, updated_at) VALUES ('demo', '车载-MR', 1, ?, ?)",
            (now, now),
        )
        group_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, mac_address, station, group_id,
                device_vendor, device_type, primary_address, protocol, port,
                username, password, remark, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'H3C', 'Cloud-AP', ?, 'ssh', 22, ?, ?, ?, ?, ?)
            """,
            [
                ("mr-01-ct", "列车01-MR-CT", "MR01CT", "0011-2233-4401", "列车01车头", group_id, "10.10.0.1", "private-user", "private-pass", "正式 MR", now, now),
                ("mr-01-cw", "列车01-MR-CW", "MR01CW", "0011-2233-4402", "列车01车尾", group_id, "10.10.0.1", "private-user", "private-pass", "正式 MR", now, now),
                ("mr-temp", "临时目标", "TEMP", "", "", group_id, "10.10.0.3", "private-user", "private-pass", "Agent 临时名称", now, now),
            ],
        )
        conn.executemany(
            """
            INSERT INTO ap_extension_points (
                site_id, line_name, system_type, network_domain, belong_type,
                station_name, section_name, section_start_station, section_end_station,
                line_side, direction, mileage_text, mileage_m, ap_point_code,
                ap_name, ap_mac_norm, ap_mac_display, remark, source_file,
                source_sheet, source_row, created_at, updated_at
            ) VALUES ('demo', '测试线', 'PIS', 'default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("station", "车站A", "A-B 区间", "车站A", "车站B", "左线", "下行", "ZDK1+100", 1100, "AP001", "AP-Online", "000000000001", "0000-0000-0001", "", "point-table.xlsx", "AP", 2, now, now),
                ("section", "", "A-B 区间", "车站A", "车站B", "右线", "上行", "YDK1+200", 1200, "AP002", "AP-Section", "000000000002", "0000-0000-0002", "仅归属区间", "point-table.xlsx", "AP", 3, now, now),
                ("station", "车站B", "B-C 区间", "车站B", "车站C", "左线", "下行", "BAD", None, "AP003", "AP-Duplicate", "000000000001", "0000-0000-0001", "错误样例", "point-table.xlsx", "AP", 4, now, now),
            ],
        )
        conn.commit()
    with database.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    paths.app_config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text(json.dumps({"current_site": "demo"}, ensure_ascii=False), encoding="utf-8")
    (paths.site_dir("demo") / "site_meta.json").write_text(
        json.dumps(
            {
                "display_name": "测试线路局点",
                "line_name": "测试线",
                "system_type": "PIS",
                "network_domain": "default",
                "created_at": now,
                "updated_at": now,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return paths, db_path


__all__ = ["build_rail_transit_base_data_fixture"]
