from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from netconsole.core.paths import PathResolver


class EmptyBaseQuery:
    @staticmethod
    def list_aps(*_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)


class EmptyOnlineQuery:
    @staticmethod
    def list_sessions(*_args, **_kwargs):
        return []


def create_mesh_analysis_fixture(tmp_path: Path) -> tuple[PathResolver, str, Path, Path, Path]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    site = "demo"
    mr_id = "12345678-1234-1234-1234-123456789abc"
    mr_name = "列车01-MR-CT"
    raw_dir = paths.mesh_mr_raw_dir(site, mr_name)
    parsed_dir = paths.mesh_mr_parsed_dir(site, mr_name)
    output_dir = paths.mesh_mr_export_dir(site, mr_name)
    for directory in (raw_dir, parsed_dir, output_dir):
        directory.mkdir(parents=True, exist_ok=True)
    raw = raw_dir / "mesh.log"
    raw.write_text("[1] 2026/07/14 10:00:00.000\nmesh sample\n", encoding="utf-8")
    report = output_dir / "列车01-MR-CT_分析报告.xlsx"
    report.write_bytes(b"existing-report")
    detail = parsed_dir / "mesh.mesh.sqlite"
    _create_detail(detail)
    index = paths.mesh_mr_db_path(site, mr_name)
    with closing(sqlite3.connect(index)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE source_files (
                id INTEGER PRIMARY KEY, mr_id TEXT, original_path TEXT, archived_path TEXT,
                parsed_db_path TEXT, parsed_db_size INTEGER, db_schema_version TEXT,
                original_filename TEXT, archived_filename TEXT, sha256 TEXT, file_size INTEGER,
                file_mtime TEXT, imported_at TEXT, parser_version TEXT, parse_status TEXT,
                encoding TEXT, is_gzip INTEGER, first_sample_time TEXT, last_sample_time TEXT,
                lines_read INTEGER, records_parsed INTEGER, records_skipped INTEGER,
                duplicate_records INTEGER, issue_count INTEGER, error_message TEXT,
                file_exists INTEGER, deleted_at TEXT, delete_error TEXT, file_status TEXT,
                parsed_deleted_at TEXT, parsed_delete_error TEXT, source_file_order INTEGER,
                analysis_params_json TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO source_files VALUES (
                1, ?, ?, ?, ?, 1, 'test', 'mesh.log', 'mesh.log', 'sha', 42, NULL,
                '2026-07-14 10:10:00.000', 'test', 'done', 'utf-8', 0,
                '2026-07-14 10:00:00.000', '2026-07-14 10:00:02.000', 3, 4, 0, 0, 0,
                '', 1, '', '', 'ok', '', '', 1, ''
            )
            """,
            (mr_id, str(raw), str(raw), str(detail)),
        )
    catalog = paths.mesh_catalog_path(site)
    catalog.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(catalog)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE mr_profiles (
                mr_id TEXT PRIMARY KEY, display_name TEXT, safe_folder_name TEXT,
                relative_folder_path TEXT, linked_device_id INTEGER, earliest_sample_time TEXT,
                latest_sample_time TEXT, source_file_count INTEGER, sample_count INTEGER,
                link_record_count INTEGER, session_count INTEGER, event_count INTEGER,
                last_import_at TEXT, created_at TEXT, updated_at TEXT, notes TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO mr_profiles VALUES (?, ?, ?, ?, 1, ?, ?, 1, 3, 4, 3, 2, ?, ?, ?, '')",
            (mr_id, mr_name, mr_name, f"files/rail_transit/mr_raw_mesh/{mr_name}", "2026-07-14 10:00:00.000", "2026-07-14 10:00:02.000", "2026-07-14 10:10:00.000", "2026-07-14 10:00:00.000", "2026-07-14 10:10:00.000"),
        )
    return paths, f"{mr_id}:1", detail, raw, report


def _create_detail(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE source_files (id INTEGER PRIMARY KEY, archived_filename TEXT, analysis_params_json TEXT);
            CREATE TABLE mesh_links (
                id INTEGER PRIMARY KEY, sample_id INTEGER, source_file_id INTEGER, record_seq INTEGER,
                sample_time TEXT, radio INTEGER, link_state TEXT, peer_mac_raw TEXT,
                peer_mac_normalized TEXT, peer_mac TEXT, peer_ap_name TEXT, peer_ap_mac TEXT,
                peer_site TEXT, peer_radio_label TEXT, duration_seconds REAL, local_rssi_db INTEGER,
                local_tx_busy INTEGER, local_rx_busy INTEGER, peer_match_rule TEXT,
                peer_resolve_source TEXT, peer_radio_mac TEXT, timestamp_tag TEXT, session_id TEXT,
                local_rate_raw INTEGER, peer_rate_raw INTEGER, local_retry INTEGER, peer_retry INTEGER,
                local_err INTEGER, peer_err INTEGER
            );
            CREATE TABLE active_points (
                id INTEGER PRIMARY KEY, link_id INTEGER, source_file_id INTEGER, radio INTEGER,
                sample_time TEXT, peer_mac_raw TEXT, peer_mac_normalized TEXT, peer_mac TEXT,
                peer_ap_name TEXT, peer_site TEXT, peer_radio TEXT, peer_radio_label TEXT,
                duration_text TEXT, duration_seconds REAL, local_rssi_db INTEGER, peer_rssi_db INTEGER,
                local_tx_busy INTEGER, peer_tx_busy INTEGER, local_rx_busy INTEGER, peer_rx_busy INTEGER
            );
            CREATE TABLE active_segments (
                id INTEGER PRIMARY KEY, radio INTEGER, peer_mac TEXT, peer_mac_normalized TEXT,
                peer_ap_name TEXT, belong_station TEXT, belong_section TEXT, belong_type TEXT,
                start_time TEXT, end_time TEXT, duration_sec REAL, sample_count INTEGER,
                avg_rssi REAL, min_rssi INTEGER, max_rssi INTEGER, start_rssi INTEGER,
                end_rssi INTEGER, event_type TEXT, source_file_id INTEGER
            );
            CREATE TABLE switch_events (
                id INTEGER PRIMARY KEY, event_type TEXT, event_time TEXT, radio INTEGER,
                previous_sample_time TEXT, current_sample_time TEXT, observed_window_ms INTEGER,
                from_peer_mac TEXT, to_peer_mac TEXT, details_json TEXT, source_file_id INTEGER
            );
            CREATE TABLE parse_issues (id INTEGER PRIMARY KEY, severity TEXT, issue_type TEXT, message TEXT, line_number INTEGER);
            CREATE TABLE rssi_stats (id INTEGER PRIMARY KEY, scope_type TEXT, scope_key TEXT, sample_count INTEGER, avg_rssi REAL, min_rssi INTEGER, max_rssi INTEGER, p10_rssi REAL, p50_rssi REAL, p90_rssi REAL, low_rssi_count INTEGER, severe_low_rssi_count INTEGER);
            CREATE TABLE diagnosis_events (id INTEGER PRIMARY KEY, event_time TEXT, severity TEXT, category TEXT, title TEXT, detail TEXT, evidence TEXT, recommendation TEXT, related_peer_mac TEXT, related_sample_id INTEGER, related_segment_id INTEGER);
            INSERT INTO source_files VALUES (1, 'mesh.log', '');
            INSERT INTO mesh_links VALUES (1, 1, 1, 1, '2026-07-14 10:00:00.000', 1, 'ACTIVE', '0000-0000-001f', '00000000001f', '00000000001f', 'AP-01', '000000000010', '车站A', 'radio2', 1, 42, 2, 78, 'exact', 'mapping', '00000000001f', '', 'session-1', 100, 90, 10, 20, 1, 2);
            INSERT INTO mesh_links VALUES (2, 2, 1, 2, '2026-07-14 10:00:01.000', 1, 'ACTIVE', '0000-0000-002f', '00000000002f', '00000000002f', 'AP-02', '000000000020', '区间A-B', 'radio2', 1, NULL, 3, 80, 'exact', 'mapping', '00000000002f', '', 'session-1', 110, 95, 13, 20, 2, 4);
            INSERT INTO mesh_links VALUES (3, 3, 1, 3, '2026-07-14 10:00:02.000', 1, 'ACTIVE', '0000-0000-001f', '00000000001f', '00000000001f', 'AP-01', '000000000010', '车站A', 'radio2', 1, 43, 2, 77, 'exact', 'mapping', '00000000001f', '', 'session-1', 120, 100, 5, 25, 2, 1);
            INSERT INTO mesh_links VALUES (4, 3, 1, 4, '2026-07-14 10:00:02.000', 1, 'STANDBY', '0000-0000-003f', '00000000003f', '00000000003f', 'AP-03', '000000000030', '车站B', 'radio2', 1, 39, 1, 5, 'exact', 'mapping', '00000000003f', '', 'session-2', 80, 75, 3, 4, 0, 0);
            INSERT INTO active_points VALUES (1, 1, 1, 1, '2026-07-14 10:00:00.000', '0000-0000-001f', '00000000001f', '00000000001f', 'AP-01', '车站A', 'radio2', 'radio2', '1s', 1, 42, 45, 2, 1, 78, 77);
            INSERT INTO active_points VALUES (2, 2, 1, 1, '2026-07-14 10:00:01.000', '0000-0000-002f', '00000000002f', '00000000002f', 'AP-02', '区间A-B', 'radio2', 'radio2', '1s', 1, NULL, 44, 3, 1, 80, 76);
            INSERT INTO active_points VALUES (3, 3, 1, 1, '2026-07-14 10:00:02.000', '0000-0000-001f', '00000000001f', '00000000001f', 'AP-01', '车站A', 'radio2', 'radio2', '1s', 1, 43, 46, 2, 1, 77, 75);
            INSERT INTO active_segments VALUES (1, 1, '0000-0000-001f', '00000000001f', 'AP-01', '车站A', '', '', '2026-07-14 10:00:00.000', '2026-07-14 10:00:00.000', 1, 1, 42, 42, 42, 42, 42, 'stable', 1);
            INSERT INTO switch_events VALUES (1, 'ACTIVE_SWITCH', '2026-07-14 10:00:01.000', 1, '2026-07-14 10:00:00.000', '2026-07-14 10:00:01.000', 1000, '0000-0000-001f', '0000-0000-002f', '{"from_local_rssi":42,"to_local_rssi":null}', 1);
            INSERT INTO switch_events VALUES (2, 'ACTIVE_SWITCH', '2026-07-14 10:00:02.000', 1, '2026-07-14 10:00:01.000', '2026-07-14 10:00:02.000', 1000, '0000-0000-002f', '0000-0000-001f', '{"from_local_rssi":null,"to_local_rssi":43}', 1);
            INSERT INTO rssi_stats VALUES (1, 'all', 'all', 2, 42.5, 42, 43, 42, 42.5, 43, 0, 0);
            INSERT INTO diagnosis_events VALUES (1, '2026-07-14 10:00:01.000', 'warning', 'switch', '切换', '正式切换事件', 'event:1', '', '0000-0000-002f', NULL, NULL);

            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', 'meshlog_compact_v3_tagged_samples');
            CREATE TABLE samples (
                id INTEGER PRIMARY KEY, source_file_id INTEGER, radio INTEGER, sample_time TEXT,
                timestamp_tag TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO samples VALUES (1, 1, 1, '2026-07-14 10:00:00.000', '');
            INSERT INTO samples VALUES (2, 1, 1, '2026-07-14 10:00:01.000', '');
            INSERT INTO samples VALUES (3, 1, 1, '2026-07-14 10:00:02.000', '');

            ALTER TABLE mesh_links ADD COLUMN source_file_order INTEGER DEFAULT 0;
            ALTER TABLE mesh_links ADD COLUMN source_line_number INTEGER DEFAULT 0;
            ALTER TABLE mesh_links ADD COLUMN peer_radio TEXT DEFAULT '';
            ALTER TABLE mesh_links ADD COLUMN establish_time TEXT;
            ALTER TABLE mesh_links ADD COLUMN duration_text TEXT DEFAULT '';
            ALTER TABLE mesh_links ADD COLUMN link_count INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_rssi_db INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_cpu_percent INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_cpu_percent INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_mem_percent INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_mem_percent INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_tx_busy INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_rx_busy INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_noise_raw INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_noise_raw INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_tx_des_free_cnt INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_tx_des_free_cnt INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_tx INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_tx INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_rx INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_rx INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_tx_garp INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_rx_garp INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_tx_mul_join INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_rx_mul_join INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_noise_dbm INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_noise_dbm INTEGER;
            ALTER TABLE mesh_links ADD COLUMN local_signal_dbm INTEGER;
            ALTER TABLE mesh_links ADD COLUMN peer_signal_dbm INTEGER;
            ALTER TABLE mesh_links ADD COLUMN raw_line_start INTEGER DEFAULT 0;
            ALTER TABLE mesh_links ADD COLUMN raw_line_end INTEGER DEFAULT 0;
            ALTER TABLE mesh_links ADD COLUMN raw_offset_start INTEGER DEFAULT 0;
            ALTER TABLE mesh_links ADD COLUMN raw_offset_end INTEGER DEFAULT 0;
            UPDATE mesh_links SET source_line_number = record_seq, peer_radio = peer_radio_label,
                duration_text = '1s', link_count = 1,
                peer_rssi_db = local_rssi_db + 3,
                peer_tx_busy = 1, peer_rx_busy = 76,
                local_noise_dbm = -95, peer_noise_dbm = -94,
                local_signal_dbm = -53, peer_signal_dbm = -50;

            ALTER TABLE active_points ADD COLUMN sample_id INTEGER;
            ALTER TABLE active_points ADD COLUMN session_id TEXT DEFAULT '';
            ALTER TABLE active_points ADD COLUMN establish_time TEXT;
            ALTER TABLE active_points ADD COLUMN local_signal_dbm INTEGER;
            ALTER TABLE active_points ADD COLUMN peer_signal_dbm INTEGER;
            UPDATE active_points SET sample_id = id, session_id = 'session-1',
                establish_time = sample_time, local_signal_dbm = -53, peer_signal_dbm = -50;
            """
        )
