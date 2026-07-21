from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from matplotlib.dates import date2num

from netconsole.core.database import Database
from netconsole.models.mesh_log_models import EVENT_ACTIVE_SWITCH, EVENT_MULTI_ACTIVE, EVENT_NO_ACTIVE
from netconsole.parsers import mesh_log_parser
from netconsole.parsers.mesh_log_parser import MeshLogParser, calculate_signal
from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_mr_repository import MeshMrRepository, MeshSchemaRebuildRequired
from netconsole.models.mesh_analysis_params import mesh_analysis_params_to_json, normalize_mesh_analysis_params
from netconsole.services.mesh_log_analysis_service import MeshLogAnalysisService
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.mesh_link_analyzer import MeshLinkAnalyzer
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.network_tools.trackside_bssid_resolver import TracksideApBssidResolver




LINE_A = "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0"
LINE_B = "[1] Active 30f5-277a-5a3f 2025/12/03 10:12:30 0d 00h 00m 03s 1 37/44 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0"
LINE_STANDBY = "[1] Standy 30f5-277a-5a4f 2025/12/03 10:12:30 0d 00h 00m 03s 1 30/31 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0"


def test_mesh_link_parameters_use_v140_defaults_and_hyphen_aliases() -> None:
    params = normalize_mesh_analysis_params({
        "link-time-window": 5000,
        "link-switch-threshold": 12,
        "link-hold-rssi": 30,
        "link-establish-threshold": 5,
    })
    assert params.link_time_window == 5000
    assert params.link_switch_threshold == 12
    assert params.link_hold_rssi == 30
    assert params.link_establish_threshold == 5
    assert params.link_establish_rssi == 35
    defaults = normalize_mesh_analysis_params(None)
    assert defaults.link_time_window == 4000
    assert defaults.link_establish_rssi == 26


def test_mesh_link_analyzer_accepts_first_link_and_applies_establishment_threshold() -> None:
    analyzer = MeshLinkAnalyzer({"link_hold_rssi": 22, "link_establish_threshold": 4})
    first = analyzer.evaluate_establishment({"avg_mr_rssi": 10}, first_link=True)
    below = analyzer.evaluate_establishment({"avg_mr_rssi": 25}, first_link=False)
    accepted = analyzer.evaluate_establishment({"avg_mr_rssi": 26}, first_link=False)
    switch_rejected = analyzer.evaluate_establishment({"avg_mr_rssi": 30}, first_link=False, previous_signal=25)
    assert first.accepted is True
    assert below.accepted is False
    assert accepted.accepted is True
    assert accepted.threshold == 26
    assert switch_rejected.accepted is False


def test_parse_timestamp_and_standy(tmp_path):
    path = tmp_path / "14CW-01-2026_02_01_1meshlog.log"
    path.write_text("[1] 2025/12/03 10:12:33.579 (3)\n" + LINE_STANDBY + "\n", encoding="utf-8")
    _, records, issues = MeshLogParser().parse_file(path)
    assert not [issue for issue in issues if issue.issue_type in {"缺少采样时间", "无法识别链路状态"}]
    assert records[0].radio == 1
    assert records[0].sample_time == datetime(2025, 12, 3, 10, 12, 33, 579000)
    assert records[0].timestamp_tag == "3"
    assert records[0].link_state_raw == "Standy"
    assert records[0].link_state == "STANDBY"


def test_same_timestamp_with_different_tags_remains_distinct(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text(
        "\n".join(
            [
                "[1] 2025/12/03 10:12:33.579 (2)",
                LINE_A,
                "[1] 2025/12/03 10:12:33.579 (4)",
                LINE_A,
            ]
        ),
        encoding="utf-8",
    )

    MeshImportService("demo", paths).import_files(profile, [source])
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    total, rows = repository.query_links(10, 0)

    assert total == 2
    assert [row["timestamp_tag"] for row in rows] == ["2", "4"]
    assert len({row["sample_id"] for row in rows}) == 2
    _, events = repository.query_events(10, 0)
    assert not [event for event in events if event["event_type"] == EVENT_MULTI_ACTIVE]
    parsed_db_path = Path(repository.list_source_files()[0]["parsed_db_path"])
    with sqlite3.connect(parsed_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 2


def test_signal_dbm_calculation():
    metrics = {"local_rssi_db": 36, "peer_rssi_db": 43, "local_noise_raw": 88, "peer_noise_raw": 105}
    assert calculate_signal(metrics) == (-88, -105, -52, -62)


def test_active_switch_observed_window(tmp_path):
    path = tmp_path / "14CW-01-2026_06_19-meshlog.log"
    path.write_text(
        "\n".join(
            [
                "[1] 2025/12/03 10:12:35.964",
                LINE_A,
                "[1] 2025/12/03 10:12:36.681",
                LINE_B,
            ]
        ),
        encoding="utf-8",
    )
    result = MeshLogAnalysisService("demo", tmp_path).analyze([path])
    switches = [event for event in result.switch_events if event.event_type == EVENT_ACTIVE_SWITCH]
    assert len(switches) == 1
    assert switches[0].from_peer_mac == "30f5-277a-5a2f"
    assert switches[0].to_peer_mac == "30f5-277a-5a3f"
    assert switches[0].observed_window_ms == 717


def test_no_active_and_multi_active(tmp_path):
    path = tmp_path / "meshlog.log"
    path.write_text(
        "\n".join(
            [
                "[1] 2025/12/03 10:12:33.000",
                LINE_STANDBY,
                "[1] 2025/12/03 10:12:34.000",
                LINE_A,
                LINE_B,
            ]
        ),
        encoding="utf-8",
    )
    result = MeshLogAnalysisService("demo", tmp_path).analyze([path])
    assert any(event.event_type == EVENT_NO_ACTIVE for event in result.switch_events)
    assert any(event.event_type == EVENT_MULTI_ACTIVE for event in result.switch_events)


def test_gzip_matches_plain_text(tmp_path):
    text = "[1] 2025/12/03 10:12:33.579 (3)\n" + LINE_A + "\n"
    plain = tmp_path / "a-meshlog.log"
    gz = tmp_path / "a-meshlog.log.gz"
    plain.write_text(text, encoding="utf-8")
    with gzip.open(gz, "wt", encoding="utf-8") as file:
        file.write(text)
    _, plain_records, _ = MeshLogParser().parse_file(plain)
    _, gz_records, _ = MeshLogParser().parse_file(gz)
    assert plain_records[0].metrics == gz_records[0].metrics
    assert plain_records[0].local_signal_dbm == gz_records[0].local_signal_dbm


def test_duplicate_records_are_removed(tmp_path):
    first = tmp_path / "14CW-01-2026_02_01_1meshlog.log"
    second = tmp_path / "14CW-01-2026_02_01_2meshlog.log"
    content = "[1] 2025/12/03 10:12:33.579 (3)\n" + LINE_A + "\n"
    first.write_text(content, encoding="utf-8")
    second.write_text(content, encoding="utf-8")
    result = MeshLogAnalysisService("demo", tmp_path).analyze([first, second])
    assert result.summary.raw_record_count == 2
    assert result.summary.record_count == 1
    assert result.summary.duplicate_record_count == 1


def test_dynamic_same_filename_archives_without_overwrite(tmp_path):
    paths = PathResolver(tmp_path)
    storage = MeshStorageService("demo", paths)
    profile = storage.create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.579\n" + LINE_A + "\n", encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [source])
    source.write_text("[1] 2025/12/03 10:12:34.579\n" + LINE_B + "\n", encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [source])
    archived = list(paths.mesh_mr_raw_dir("demo", profile.safe_folder_name).rglob("meshlog*.log"))
    assert len(archived) == 2
    assert len({item.name for item in archived}) == 2










def test_duplicate_sha_is_skipped(tmp_path):
    paths = PathResolver(tmp_path)
    storage = MeshStorageService("demo", paths)
    profile = storage.create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.579\n" + LINE_A + "\n", encoding="utf-8")
    service = MeshImportService("demo", paths)
    service.import_files(profile, [source])
    duplicate = service.import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    assert duplicate.duplicate_count == 1
    assert len(repo.list_source_files()) == 1


def test_mesh_import_creates_compact_schema_without_raw_payload_columns(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.579\n" + LINE_A + "\n", encoding="utf-8")

    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))

    with sqlite3.connect(repo.path) as conn:
        schema_version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        assert schema_version == "meshlog_compact_v3_tagged_samples"
        parsed_db_path = Path(conn.execute("SELECT parsed_db_path FROM source_files").fetchone()[0])
        assert parsed_db_path.name.endswith(".mesh.sqlite")
        assert conn.execute("SELECT COUNT(*) FROM mesh_links").fetchone()[0] == 0
    with sqlite3.connect(parsed_db_path) as conn:
        schema_version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        assert schema_version == "meshlog_compact_v3_tagged_samples"
        table_names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()}
        assert {"active_points", "active_segments", "switch_events", "rssi_stats", "diagnosis_events"} <= table_names
        forbidden = {"raw_line", "raw_text", "raw_block", "raw_payload", "full_command_output", "debug_text", "metrics_json", "deltas_json", "raw_file"}
        for table in ("mesh_links", "parse_issues", "samples", "active_points"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            assert not (columns & forbidden)
        assert conn.execute("SELECT COUNT(*) FROM active_points").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM active_segments").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM rssi_stats").fetchone()[0] >= 1


def test_mesh_repository_requires_external_rebuild_for_incompatible_schema(tmp_path):
    db_path = tmp_path / "mesh.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE mesh_links(raw_line TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(MeshSchemaRebuildRequired, match="rebuild_mesh_parsed_data"):
        MeshMrRepository(db_path)
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(mesh_links)").fetchall()}
    assert "raw_line" in columns
    assert not list(tmp_path.glob("mesh.sqlite.legacy_*"))


def test_multiple_mrs_use_isolated_databases(tmp_path):
    paths = PathResolver(tmp_path)
    storage = MeshStorageService("demo", paths)
    mr1 = storage.create_mr_profile("14CW-01")
    mr2 = storage.create_mr_profile("14CW-02")
    source1 = tmp_path / "mr1.log"
    source2 = tmp_path / "mr2.log"
    source1.write_text("[1] 2025/12/03 10:12:33.579\n" + LINE_A + "\n", encoding="utf-8")
    source2.write_text("[1] 2025/12/03 10:12:33.579\n" + LINE_B + "\n", encoding="utf-8")
    service = MeshImportService("demo", paths)
    service.import_files(mr1, [source1])
    service.import_files(mr2, [source2])
    assert paths.mesh_mr_db_path("demo", mr1.safe_folder_name) != paths.mesh_mr_db_path("demo", mr2.safe_folder_name)
    total1, rows1 = MeshMrRepository(paths.mesh_mr_db_path("demo", mr1.safe_folder_name)).query_links(10, 0)
    total2, rows2 = MeshMrRepository(paths.mesh_mr_db_path("demo", mr2.safe_folder_name)).query_links(10, 0)
    assert total1 == total2 == 1
    assert rows1[0]["peer_mac_raw"] == "30f5-277a-5a2f"
    assert rows2[0]["peer_mac_raw"] == "30f5-277a-5a3f"


def test_mesh_links_keep_import_record_sequence_order(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    first.write_text("[1] 2025/12/03 10:00:03.000\n" + LINE_A + "\n", encoding="utf-8")
    second.write_text("[1] 2025/12/03 10:00:01.000\n" + LINE_B + "\n", encoding="utf-8")

    MeshImportService("demo", paths).import_files(profile, [first, second])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    _, links = repo.query_links(10, 0)

    assert [link["peer_mac_raw"] for link in links] == ["30f5-277a-5a2f", "30f5-277a-5a3f"]
    assert [link["record_seq"] for link in links] == [1, 2]
    assert [link["source_file_order"] for link in links] == [1, 2]


def test_mesh_query_sorts_record_seq_as_integer(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    lines = ["[1] 2025/12/03 10:00:00.000"]
    for suffix in ("1f", "2f", "3f", "4f", "5f"):
        lines.append(LINE_A.replace("30f5-277a-5a2f", f"30f5-277a-5a{suffix}"))
    source.write_text("\n".join(lines), encoding="utf-8")

    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    detail_path = Path(repo.list_source_files()[0]["parsed_db_path"])
    with sqlite3.connect(detail_path) as conn:
        ids = [row[0] for row in conn.execute("SELECT id FROM mesh_links ORDER BY id ASC").fetchall()]
        for link_id, seq in zip(ids, [1000, 10, 1, 100, 2], strict=True):
            conn.execute("UPDATE mesh_links SET record_seq = ? WHERE id = ?", (seq, link_id))

    _, rows = repo.query_links(10, 0)

    assert [row["record_seq"] for row in rows] == [1, 2, 10, 100, 1000]




def test_mesh_peer_mapping_keeps_ap_mac_and_radio_mac_separate(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.000\n" + LINE_A + "\n", encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))

    repo.upsert_peer_mappings(
        [
            {
                "peer_mac_normalized": "30f5277a5a2f",
                "peer_ap_name": "AP-01",
                "peer_ap_mac": "30f5277a5a3f",
                "peer_radio_mac": "30f5277a5a2f",
                "peer_radio_label": "radio2",
                "peer_site": "站点",
                "match_rule": "resolver",
                "match_confidence": 90,
            }
        ]
    )
    repo.refresh_peer_mapping_on_links()
    _, links = repo.query_links(10, 0)

    assert links[0]["peer_mac_raw"] == "30f5-277a-5a2f"
    assert links[0]["peer_ap_mac"] == "30f5277a5a3f"
    assert links[0]["peer_radio_mac"] == "30f5277a5a2f"


def test_mesh_peer_mapping_service_uses_h3c_radio_rule_fields(tmp_path):
    paths = PathResolver(tmp_path)
    service = MeshPeerMappingService("demo", paths)
    service._resolver = TracksideApBssidResolver([{"ap_name": "AP-01", "ap_mac": "083b-e9ec-da40", "site_name": "S1"}])

    resolved = service.resolve("083b-e9ec-da5f")

    assert resolved is not None
    assert resolved["peer_mac_normalized"] == "083be9ecda5f"
    assert resolved["peer_radio_mac"] == "083be9ecda5f"
    assert resolved["peer_ap_mac"] == "083be9ecda40"
    assert resolved["peer_ap_name"] == "AP-01"
    assert resolved["peer_site"] == "S1"
    assert resolved["peer_radio_label"] == "radio2"


def test_mesh_peer_mapping_service_returns_serial_number_for_h3c_peer_mac(tmp_path):
    paths = PathResolver(tmp_path)
    service = MeshPeerMappingService("demo", paths)
    service._resolver = TracksideApBssidResolver(
        [{"ap_name": "bc5a-3457-cbe0", "ap_mac": "bc5a-3457-cbe0", "station": "03镇驼站", "serial_number": "TEST-SN-001"}]
    )

    resolved = service.resolve("bc5a-3457-cbef")

    assert resolved is not None
    assert resolved["peer_ap_name"] == "bc5a-3457-cbe0"
    assert resolved["peer_ap_mac"] == "bc5a3457cbe0"
    assert resolved["peer_radio_mac"] == "bc5a3457cbef"
    assert resolved["peer_site"] == "03镇驼站"
    assert resolved["peer_serial_number"] == "TEST-SN-001"
    assert resolved["serial_number"] == "TEST-SN-001"
    assert resolved["peer_radio_label"] == "radio1"


def test_multiple_source_files_can_filter_links_and_charts(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    first = tmp_path / "first-meshlog.log"
    second = tmp_path / "second-meshlog.log"
    first.write_text("[1] 2025/12/03 10:00:00.000\n" + LINE_A + "\n", encoding="utf-8")
    second.write_text("[1] 2025/12/03 10:00:01.000\n" + LINE_A + "\n", encoding="utf-8")

    MeshImportService("demo", paths).import_files(profile, [first, second])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    sources = repo.list_source_files()
    assert len(sources) == 2

    first_id = int(sources[0]["id"])
    second_id = int(sources[1]["id"])
    total_all, all_links = repo.query_links(100, 0)
    total_first, first_links = repo.query_links(100, 0, {"source_file_id": first_id})
    total_second, second_links = repo.query_links(100, 0, {"source_file_id": second_id})

    assert total_all == 2
    assert total_first == len(first_links) == 1
    assert total_second == len(second_links) == 1
    assert int(first_links[0]["source_file_id"]) == first_id
    assert int(second_links[0]["source_file_id"]) == second_id

    chart_first = repo.query_peer_chart_segments(int(first_links[0]["id"]), source_file_id=first_id)
    chart_all = repo.query_peer_chart_segments(int(first_links[0]["id"]))
    assert [row["sample_time"] for row in chart_first["run_segment"]["rows"]] == ["2025-12-03 10:00:00.000"]
    assert chart_all["run_segment"]["rows"] == []
    assert "source_file_id" in chart_all["message"]

    first_db = Path(sources[0]["parsed_db_path"])
    second_db = Path(sources[1]["parsed_db_path"])
    conn = sqlite3.connect(first_db)
    try:
        conn.execute(
            """
            INSERT INTO switch_events (
                event_type, event_time, radio, previous_sample_time, current_sample_time,
                observed_window_ms, from_peer_mac, to_peer_mac, details_json, source_file_id, source_line_number
            ) VALUES
                ('ACTIVE_SWITCH', '2025-12-03 10:00:00.000', 1, NULL, '2025-12-03 10:00:00.000', NULL, NULL, NULL, '{}', 1, 2)
            """,
        )
        conn.commit()
    finally:
        conn.close()
    conn = sqlite3.connect(second_db)
    try:
        conn.execute(
            """
            INSERT INTO parse_issues (source_file_id, source_file, line_number, severity, issue_type, field_name, message, raw_line_start, raw_line_end)
            VALUES (1, 'second.log', 9, 'ERROR', 'x', 'x', 'second', 9, 9)
            """,
        )
        conn.commit()
    finally:
        conn.close()

    event_total, events = repo.query_events(100, 0, first_id)
    issue_total, issues = repo.query_issues(100, 0, second_id)
    assert event_total == len(events) == 1
    assert int(events[0]["source_file_id"]) == first_id
    assert issue_total == len(issues) == 1
    assert int(issues[0]["source_file_id"]) == second_id

    result = repo.delete_parsed_data_by_source_file(first_id)
    assert result.ok
    assert result.deleted_links == 1
    assert repo.query_links(100, 0, {"source_file_id": first_id})[0] == 0
    assert repo.query_links(100, 0, {"source_file_id": second_id})[0] == 1
    assert repo.query_events(100, 0, first_id)[0] == 0
    assert repo.query_issues(100, 0, first_id)[0] == 0
    first_status = next(source for source in repo.list_source_files() if int(source["id"]) == first_id)
    assert first_status["file_status"] == "parsed_deleted"

    second_archive = Path(str(next(source for source in repo.list_source_files() if int(source["id"]) == second_id)["archived_path"]))
    second_archive.unlink()
    repo.mark_source_file_deleted(second_id)
    assert repo.query_links(100, 0, {"source_file_id": second_id})[0] == 1
    second_status = next(source for source in repo.list_source_files() if int(source["id"]) == second_id)
    assert second_status["file_status"] == "deleted"


def test_list_source_files_uses_cached_file_status_without_path_exists(tmp_path, monkeypatch):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.579\n" + LINE_A + "\n", encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))

    monkeypatch.setattr(Path, "exists", lambda _path: (_ for _ in ()).throw(AssertionError("Path.exists should not be called")))

    rows = repo.list_source_files()

    assert len(rows) == 1
    assert rows[0]["file_status"] == "ok"
    assert rows[0]["file_exists"] == 1


def test_counter_reset_generates_event_without_negative_delta(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    line_high = LINE_A.replace("2/297", "100/200")
    line_low = LINE_A.replace("2/297", "1/2")
    source = tmp_path / "meshlog.log"
    source.write_text(
        "\n".join(["[1] 2025/12/03 10:12:33.000", line_high, "[1] 2025/12/03 10:12:34.000", line_low]),
        encoding="utf-8",
    )
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    _, events = repo.query_events(100, 0)
    _, links = repo.query_links(100, 0)
    assert any(event["event_type"] == "COUNTER_RESET" for event in events)
    assert all("-" not in str(link["deltas_json"]) for link in links)


def test_same_peer_different_establish_time_creates_sessions(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    second_session = LINE_A.replace("2025/12/03 10:12:30", "2025/12/03 10:13:00")
    source = tmp_path / "meshlog.log"
    source.write_text(
        "\n".join(["[1] 2025/12/03 10:12:33.000", LINE_A, "[1] 2025/12/03 10:13:33.000", second_session]),
        encoding="utf-8",
    )
    MeshImportService("demo", paths).import_files(profile, [source])
    sessions = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name)).export_rows("mesh_sessions")
    assert len(sessions) == 2


def test_import_hash_once_and_duplicate_does_not_parse(tmp_path, monkeypatch):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.579\n" + LINE_A + "\n", encoding="utf-8")
    hash_calls = 0
    original_hash = mesh_log_parser.sha256_file
    original_parse = MeshLogParser.parse_file

    def counting_hash(path):
        nonlocal hash_calls
        hash_calls += 1
        return original_hash(path)

    parse_calls = 0

    def counting_parse(self, *args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(self, *args, **kwargs)

    monkeypatch.setattr("netconsole.services.mesh_import_service.sha256_file", counting_hash)
    monkeypatch.setattr(MeshLogParser, "parse_file", counting_parse)
    service = MeshImportService("demo", paths)
    service.import_files(profile, [source])
    service.import_files(profile, [source])
    assert hash_calls == 2
    assert parse_calls == 1


def test_query_links_returns_stable_sample_group_index(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text(
        "\n".join(
            [
                "[1] 2025/12/03 10:12:33.000",
                LINE_A,
                LINE_STANDBY,
                "[1] 2025/12/03 10:12:34.000",
                LINE_B,
                LINE_STANDBY.replace("30f5-277a-5a4f", "30f5-277a-5a5f"),
            ]
        ),
        encoding="utf-8",
    )
    MeshImportService("demo", paths).import_files(profile, [source])
    _, rows = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name)).query_links(10, 0)
    groups_by_time = {}
    for row in rows:
        groups_by_time.setdefault(row["sample_time"], set()).add(row["sample_group_index"])
    assert all(len(groups) == 1 for groups in groups_by_time.values())
    assert len({next(iter(groups)) for groups in groups_by_time.values()}) == 2


def test_mesh_import_resolves_peer_ap_name_site_and_radio(tmp_path):
    paths = PathResolver(tmp_path)
    site_db = Database(paths.site_db_path("demo"))
    site_db.initialize()
    with site_db.connect() as conn:
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO ac_fit_ap_resources (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, site, collected_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("ac-1", "ap-1", "AP-01", "30f5-277a-5a10", "Ningbo Station", now, now),
        )
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.000\n" + LINE_A + "\n", encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    _, rows = repo.query_links(10, 0, {"peer": "AP-01"})
    assert len(rows) == 1
    assert rows[0]["peer_ap_name"] == "AP-01"
    assert rows[0]["peer_site"] == "Ningbo Station"
    assert rows[0]["peer_radio"] == "radio2"
    assert rows[0]["peer_radio_label"] == "radio2"
    assert rows[0]["peer_radio_mac"] == "30f5277a5a2f"
    assert rows[0]["peer_ap_mac"] == "30f5277a5a10"
    assert rows[0]["peer_resolve_source"] == "h3c_radio_2_ap_mac_nibble_plus_1"
    cache_rows = repo.export_rows("mesh_peer_resolve_cache")
    assert cache_rows[0]["peer_mac"] == "30f5277a5a2f"
    assert cache_rows[0]["peer_ap_name"] == "AP-01"


def test_mesh_repository_builds_downsampled_link_aggregates(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text(
        "\n".join(
            [
                "[1] 2025/12/03 10:12:33.000",
                LINE_A,
                "[1] 2025/12/03 10:12:34.000",
                LINE_A.replace("36/43", "38/45"),
            ]
        ),
        encoding="utf-8",
    )
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    rows = repo.query_link_aggregates(bucket_seconds=10)
    assert rows == []
    detail_path = Path(repo.list_source_files()[0]["parsed_db_path"])
    with sqlite3.connect(detail_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'mesh_link_aggregates'").fetchone()[0] == 0
















def test_active_build_order_uses_source_snapshot_before_site_fallback_and_temp_override(tmp_path):
    repo = MeshMrRepository(tmp_path / "sample.mesh.sqlite")
    _insert_mesh_samples(repo.path, first_count=2, second_count=0)
    snapshot = mesh_analysis_params_to_json(
        {
            "main_link_switch_time_ms": 2500,
            "short_link_tolerance_ms": 500,
            "merge_same_physical_ap_dual_radio": True,
        }
    )
    with sqlite3.connect(repo.path) as conn:
        conn.execute("UPDATE source_files SET analysis_params_json = ?", (snapshot,))

    rows = repo.query_active_link_build_order(
        fallback_analysis_params={"main_link_switch_time_ms": 5000, "short_link_tolerance_ms": 500}
    )
    assert rows[0]["main_link_switch_time_ms"] == 2500
    assert rows[0]["short_link_tolerance_ms"] == 500
    assert rows[0]["build_result"] == "normal"
    assert "容差范围" in rows[0]["judge_reason"]

    override_rows = repo.query_active_link_build_order(
        analysis_params={"main_link_switch_time_ms": 3000, "short_link_tolerance_ms": 500}
    )
    assert override_rows[0]["main_link_switch_time_ms"] == 3000
    assert override_rows[0]["build_result"] == "short"


def test_active_build_order_marks_ap_pingpong_by_physical_ap_sequence():
    from netconsole.repositories.mesh_mr_repository import _active_build_order_rows_from_points

    rows = [
        _active_point("2025-12-03 10:00:00.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"),
        _active_point("2025-12-03 10:00:01.000", "30f5277a5a3f", "bbbb-0000-0001", "AP-B", "radio1"),
        _active_point("2025-12-03 10:00:02.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"),
    ]
    result = _active_build_order_rows_from_points(rows, {"main_link_switch_time_ms": 2500, "pingpong_tolerance_ms": 500})

    middle = result[1]
    assert middle["is_ap_return_event"] is True
    assert middle["is_pingpong_abnormal"] is True
    assert middle["pingpong_type"] == "AP乒乓切换异常"
    assert middle["middle_ap_dwell_ms"] == 1000
    assert "明显小于配置切换时间 2500ms" in middle["pingpong_judgment_reason"]


def test_active_build_order_rssi_stats_use_same_valid_samples():
    from netconsole.repositories.mesh_mr_repository import _active_build_order_rows_from_points

    rows = [
        {**_active_point("2025-12-03 10:00:00.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"), "local_rssi_db": 0},
        {**_active_point("2025-12-03 10:00:01.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"), "local_rssi_db": 40},
        {**_active_point("2025-12-03 10:00:02.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"), "local_rssi_db": 50},
    ]
    result = _active_build_order_rows_from_points(rows, {"main_link_switch_time_ms": 2500, "pingpong_tolerance_ms": 500})

    segment = result[0]
    assert segment["avg_mr_rssi"] == 30
    assert segment["min_mr_rssi"] == 0
    assert segment["max_mr_rssi"] == 50
    assert segment["min_mr_rssi"] <= segment["avg_mr_rssi"] <= segment["max_mr_rssi"]


def test_active_build_order_separates_critical_and_normal_return_events():
    from netconsole.repositories.mesh_mr_repository import _active_build_order_rows_from_points

    critical_rows = [
        _active_point("2025-12-03 10:00:00.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"),
        _active_point("2025-12-03 10:00:01.000", "30f5277a5a3f", "bbbb-0000-0001", "AP-B", "radio1"),
        _active_point("2025-12-03 10:00:02.000", "30f5277a5a3f", "bbbb-0000-0001", "AP-B", "radio1"),
        _active_point("2025-12-03 10:00:03.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"),
    ]
    normal_rows = [
        _active_point("2025-12-03 10:10:00.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"),
        _active_point("2025-12-03 10:10:01.000", "30f5277a5a3f", "bbbb-0000-0001", "AP-B", "radio1"),
        _active_point("2025-12-03 10:10:02.000", "30f5277a5a3f", "bbbb-0000-0001", "AP-B", "radio1"),
        _active_point("2025-12-03 10:10:03.000", "30f5277a5a3f", "bbbb-0000-0001", "AP-B", "radio1"),
        _active_point("2025-12-03 10:10:04.000", "30f5277a5a3f", "bbbb-0000-0001", "AP-B", "radio1"),
        _active_point("2025-12-03 10:10:05.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"),
    ]

    critical = _active_build_order_rows_from_points(critical_rows, {"main_link_switch_time_ms": 2500, "pingpong_tolerance_ms": 500})[1]
    normal = _active_build_order_rows_from_points(normal_rows, {"main_link_switch_time_ms": 2500, "pingpong_tolerance_ms": 500})[1]

    assert critical["pingpong_type"] == "临界回切"
    assert critical["is_pingpong_abnormal"] is False
    assert normal["pingpong_type"] == "普通回切事件"
    assert normal["is_pingpong_abnormal"] is False


def test_active_build_order_marks_same_physical_ap_radio_roundtrip_not_ap_pingpong():
    from netconsole.repositories.mesh_mr_repository import _active_build_order_rows_from_points

    rows = [
        _active_point("2025-12-03 10:00:00.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"),
        _active_point("2025-12-03 10:00:01.000", "30f5277a5a3f", "aaaa-0000-0001", "AP-A", "radio2"),
        _active_point("2025-12-03 10:00:02.000", "30f5277a5a2f", "aaaa-0000-0001", "AP-A", "radio1"),
    ]
    result = _active_build_order_rows_from_points(rows, {"main_link_switch_time_ms": 2500, "pingpong_tolerance_ms": 500})

    middle = result[1]
    assert middle["pingpong_type"] == "同AP射频往返"
    assert middle["is_ap_return_event"] is False
    assert middle["is_pingpong_abnormal"] is False


def test_peer_chart_run_context_includes_same_time_standby_from_other_session(tmp_path):
    from netconsole.services.mesh_chart_payload import build_chart_payload

    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.000\n" + LINE_A + "\n" + LINE_STANDBY + "\n", encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    total, rows = repo.query_links(10, 0, {"state": "ACTIVE"})
    assert total == 1
    anchor = rows[0]

    segments = repo.query_peer_chart_initial_segments(int(anchor["id"]), source_file_id=anchor["source_file_id"])
    run_rows = segments["run_segment"]["rows"]
    assert {row["link_state"] for row in run_rows} == {"ACTIVE", "STANDBY"}

    payload = build_chart_payload(segments["peer_segment"], segments["run_segment"])
    backups = [items for items in payload["backup_links_by_index"] if items]
    assert backups
    assert backups[0][0]["peer_mac"] == "30f5277a5a4f"
    assert payload["main_links_by_index"][0]["peer_mac"] == "30f5277a5a2f"














def test_peer_context_segment_splits_same_peer_after_gap(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text(
        "\n".join(
            [
                "[1] 2025/12/03 10:00:00.000",
                LINE_A,
                "[1] 2025/12/03 10:00:01.000",
                LINE_A.replace("60/72060", "61/72061"),
                "[1] 2025/12/03 10:30:00.000",
                LINE_A.replace("60/72060", "62/72062"),
            ]
        ),
        encoding="utf-8",
    )
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    _, rows = repo.query_links(100, 0)
    first_anchor = next(row for row in rows if str(row["sample_time"]).endswith("10:00:00.000"))
    late_anchor = next(row for row in rows if str(row["sample_time"]).endswith("10:30:00.000"))
    first_segment = repo.query_peer_context_segment(int(first_anchor["id"]))
    late_segment = repo.query_peer_context_segment(int(late_anchor["id"]))
    assert [row["sample_time"] for row in first_segment["rows"]] == ["2025-12-03 10:00:00.000", "2025-12-03 10:00:01.000"]
    assert [row["sample_time"] for row in late_segment["rows"]] == ["2025-12-03 10:30:00.000"]




def test_run_segment_query_uses_anchor_boundaries_not_second_run(tmp_path):
    repo = MeshMrRepository(tmp_path / "sample.mesh.sqlite")
    _insert_mesh_samples(repo.path, first_count=10000, second_count=10000)
    segment = repo.query_run_context_segment(5000)
    sample_times = {row["sample_time"] for row in segment["rows"]}
    assert len(sample_times) == 10000
    assert "2025-12-03 10:00:00.000" in sample_times
    assert "2025-12-03 13:16:40.000" not in sample_times


def test_full_active_chart_query_loads_beyond_link_detail_page_size(tmp_path):
    from netconsole.services.mesh_chart_payload import build_chart_payload

    repo = MeshMrRepository(tmp_path / "sample.mesh.sqlite")
    _insert_mesh_samples(repo.path, first_count=1005, second_count=0)

    segment = repo.query_active_link_chart_segments()
    payload = build_chart_payload(segment["peer_segment"], segment["run_segment"])

    assert len(segment["run_segment"]["rows"]) == 1005
    assert segment["run_segment"]["query_active_count"] == 1005
    assert payload["metadata"]["sample_count"] == 1005
    assert payload["metadata"]["query_active_count"] == 1005
    assert payload["metadata"]["full_active_payload"] is True














































def test_chart_payload_does_not_load_removed_chart_series(tmp_path):
    from netconsole.services.mesh_chart_payload import build_chart_payload

    row = _chart_row(1, "2025-12-03 10:00:00.000")
    row["duration_seconds"] = 3
    row["expected_duration_seconds"] = 4
    row["duration_deviation_seconds"] = -1
    row["deltas"] = {"delta_local_retry": 1, "delta_peer_retry": 2, "delta_local_err": 3, "delta_peer_err": 4}
    payload = build_chart_payload({"anchor": row, "rows": [row]}, {"anchor": row, "rows": [row], "events": []})
    peer_series = payload["peer_series"]
    for key in ("duration", "expected_duration", "delta_local_retry", "delta_peer_retry", "delta_local_err", "delta_peer_err", "local_rate", "peer_rate"):
        assert key not in peer_series
    for key in ("active_peer_rssi", "next_peer_rssi", "active_peer_tx_busy", "active_peer_rx_busy", "next_peer_tx_busy", "next_peer_rx_busy"):
        assert key not in payload["active_series"]
    assert "peer_duration_deviation" not in payload
    assert row["duration_seconds"] == 3
    assert row["deltas"]["delta_local_err"] == 3


def test_active_channel_load_payload_does_not_include_next_or_peer_side_metrics():
    from netconsole.services.mesh_chart_payload import build_chart_payload

    rows = [
        _payload_row(1, "2025-12-03 10:00:01.000", "30f5-277a-5a2f", "ACTIVE", 30, 50, 1, 2),
        _payload_row(2, "2025-12-03 10:00:01.000", "30f5-277a-5a3f", "STANDBY", 40, 60, 10, 20),
        _payload_row(3, "2025-12-03 10:00:02.000", "30f5-277a-5a2f", "ACTIVE", 31, 51, 3, 4),
        _payload_row(4, "2025-12-03 10:00:02.000", "30f5-277a-5a3f", "STANDBY", 42, 62, 12, 22),
        _payload_row(5, "2025-12-03 10:00:03.000", "30f5-277a-5a2f", "ACTIVE", 32, 52, 5, 6),
        _payload_row(6, "2025-12-03 10:00:03.000", "30f5-277a-5a3f", "STANDBY", 45, 65, 15, 24),
        _payload_row(7, "2025-12-03 10:00:04.000", "30f5-277a-5a3f", "ACTIVE", 46, 66, 16, 26),
    ]
    payload = build_chart_payload({"anchor": rows[0], "rows": rows}, {"anchor": rows[0], "rows": rows, "events": []})
    assert payload["active_series"]["active_local_tx_busy"][:3].tolist() == [1, 3, 5]
    assert payload["active_series"]["active_local_rx_busy"][:3].tolist() == [2, 4, 6]
    for key in ("next_local_tx_busy", "next_local_rx_busy", "active_peer_tx_busy", "active_peer_rx_busy", "next_peer_tx_busy", "next_peer_rx_busy"):
        assert key not in payload["active_series"]


def test_chart_payload_uses_compact_v2_scalar_metrics_without_json_payload():
    from netconsole.services.mesh_chart_payload import build_chart_payload

    rows = [
        {
            "id": 1,
            "sample_time": "2025-12-03 10:00:01.000",
            "link_state": "ACTIVE",
            "peer_mac_normalized": "30f5277a5a2f",
            "peer_ap_name": "AP-01",
            "peer_site": "Station-01",
            "peer_radio": "radio1",
            "local_rssi_db": 36,
            "peer_rssi_db": 43,
            "local_tx_busy": 3,
            "local_rx_busy": 5,
        },
        {
            "id": 2,
            "sample_time": "2025-12-03 10:00:02.000",
            "link_state": "ACTIVE",
            "peer_mac_normalized": "30f5277a5a2f",
            "peer_ap_name": "AP-01",
            "peer_site": "Station-01",
            "peer_radio": "radio1",
            "local_rssi_db": 37,
            "peer_rssi_db": 44,
            "local_tx_busy": 4,
            "local_rx_busy": 6,
        },
    ]
    payload = build_chart_payload({"anchor": rows[0], "rows": rows}, {"anchor": rows[0], "rows": rows, "events": []})
    assert payload["peer_series"]["local_rssi"].tolist() == [36, 37]
    assert payload["active_series"]["active_local_rssi"].tolist() == [36, 37]
    assert payload["active_series"]["active_local_tx_busy"].tolist() == [3, 4]
    assert payload["active_series"]["active_local_rx_busy"].tolist() == [5, 6]


def test_current_active_payload_excludes_next_active_fields():
    from netconsole.services.mesh_chart_payload import build_chart_payload

    rows = [
        _payload_row(1, "2025-12-03 10:00:01.000", "30f5-277a-5a2f", "ACTIVE", 24, 34),
        _payload_row(2, "2025-12-03 10:00:02.000", "30f5-277a-5a2f", "ACTIVE", 25, 35),
        _payload_row(3, "2025-12-03 10:00:02.000", "30f5-277a-5a3f", "STANDBY", 45, 47),
        _payload_row(4, "2025-12-03 10:00:03.000", "30f5-277a-5a3f", "ACTIVE", 44, 46),
    ]
    payload = build_chart_payload({"anchor": rows[0], "rows": rows[:2]}, {"anchor": rows[0], "rows": rows, "events": []})
    assert "next_peer_macs" not in payload
    assert "next_peer_change_indices" not in payload
    assert "next_local_rssi" not in payload["active_series"]


def test_current_active_payload_uses_canonical_mac_formats_for_runs():
    from netconsole.services.mesh_chart_payload import build_chart_payload

    rows = [
        _payload_row(1, "2025-12-03 10:00:01.000", "30f5-277a-5a2f", "ACTIVE", 24, 34),
        _payload_row(2, "2025-12-03 10:00:02.000", "30F5277A5A3F", "ACTIVE", 44, 46),
    ]
    rows[1]["peer_mac_normalized"] = ""
    payload = build_chart_payload({"anchor": rows[0], "rows": [rows[0]]}, {"anchor": rows[0], "rows": rows, "events": []})
    assert [run["peer_mac"] for run in payload["active_runs"]] == ["30f5277a5a2f", "30f5277a5a3f"]




def test_active_payload_backup_links_require_exact_source_time_tag_and_radio():
    from netconsole.services.mesh_chart_payload import build_chart_payload

    active = _payload_row(1, "2025-12-03 10:00:00.000", "30f5-277a-5a2f", "ACTIVE", 45, 53, source_file_id=1)
    same_source = _payload_row(2, "2025-12-03 10:00:00.600", "30f5-277a-5a3f", "STANDBY", 27, 37, source_file_id=1)
    other_source = _payload_row(3, "2025-12-03 10:00:00.000", "30f5-277a-5a4f", "STANDBY", 31, 39, source_file_id=2)
    exact = _payload_row(4, "2025-12-03 10:00:00.000", "30f5-277a-5a5f", "STANDBY", 29, 38, source_file_id=1)
    other_tag = _payload_row(5, "2025-12-03 10:00:00.000", "30f5-277a-5a6f", "STANDBY", 28, 36, source_file_id=1)
    other_tag["timestamp_tag"] = "(2)"
    other_radio = _payload_row(6, "2025-12-03 10:00:00.000", "30f5-277a-5a7f", "STANDBY", 26, 35, source_file_id=1)
    other_radio["radio"] = 2
    payload = build_chart_payload(
        {"anchor": active, "rows": [active]},
        {
            "anchor": active,
            "rows": [active, same_source, other_source, exact, other_tag, other_radio],
            "events": [],
        },
    )

    backups = payload["standby_links_by_index"][0]
    assert [item["peer_mac"] for item in backups] == ["30f5277a5a5f"]
    assert backups[0]["source_file_id"] == 1


def test_aba_active_switch_preserves_three_runs_and_rapid_flap():
    from netconsole.services.mesh_chart_payload import build_chart_payload

    rows = [
        _payload_row(1, "2025-12-03 10:00:01.000", "30f5-277a-5a2f", "ACTIVE", 24, 34),
        _payload_row(2, "2025-12-03 10:00:01.000", "30f5-277a-5a3f", "STANDBY", 40, 42),
        _payload_row(3, "2025-12-03 10:00:02.000", "30f5-277a-5a2f", "ACTIVE", 25, 35),
        _payload_row(4, "2025-12-03 10:00:02.000", "30f5-277a-5a3f", "STANDBY", 41, 43),
        _payload_row(5, "2025-12-03 10:00:03.000", "30f5-277a-5a2f", "STANDBY", 26, 36),
        _payload_row(6, "2025-12-03 10:00:03.000", "30f5-277a-5a3f", "ACTIVE", 42, 44),
        _payload_row(7, "2025-12-03 10:00:04.000", "30f5-277a-5a2f", "ACTIVE", 27, 37),
        _payload_row(8, "2025-12-03 10:00:04.000", "30f5-277a-5a3f", "STANDBY", 43, 45),
    ]
    events = [
        {"event_type": EVENT_ACTIVE_SWITCH, "event_time": "2025-12-03 10:00:03.000"},
        {"event_type": EVENT_ACTIVE_SWITCH, "event_time": "2025-12-03 10:00:04.000", "is_rapid_flap": True},
    ]
    payload = build_chart_payload({"anchor": rows[0], "rows": rows}, {"anchor": rows[0], "rows": rows, "events": events, "estimated_interval_seconds": 1.0})
    assert [run["peer_mac"] for run in payload["active_runs"]] == ["30f5277a5a2f", "30f5277a5a3f", "30f5277a5a2f"]
    assert payload["switch_indices"].tolist() == [2, 3]
    assert "next_peer_macs" not in payload
    assert payload["rapid_flap_indices"].tolist() == [3]
    assert payload["rapid_flaps"][0]["is_rapid_flap"] is True


def test_chart_switch_event_nearest_point_respects_sampling_tolerance():
    from netconsole.services.mesh_chart_payload import build_chart_payload

    rows = [
        _payload_row(1, "2025-12-03 10:00:01.000", "30f5-277a-5a2f", "ACTIVE", 24, 34),
        _payload_row(2, "2025-12-03 10:00:02.000", "30f5-277a-5a3f", "ACTIVE", 25, 35),
    ]
    events = [
        {"id": 1, "event_type": EVENT_ACTIVE_SWITCH, "event_time": "2025-12-03 10:00:02.400"},
        {"id": 2, "event_type": EVENT_ACTIVE_SWITCH, "event_time": "2025-12-03 10:00:20.000"},
    ]

    payload = build_chart_payload(
        {"anchor": rows[0], "rows": rows},
        {"anchor": rows[0], "rows": rows, "events": events, "estimated_interval_seconds": 1.0},
    )

    mapped_ids = [item["id"] for values in payload["events_by_index"].values() for item in values]
    assert mapped_ids == [1]

    without_interval = build_chart_payload(
        {"anchor": rows[0], "rows": rows},
        {"anchor": rows[0], "rows": rows, "events": [events[0]]},
    )
    assert without_interval["events_by_index"] == {}




def test_no_active_and_multi_active_do_not_generate_active_series():
    from netconsole.services.mesh_chart_payload import build_chart_payload

    rows = [
        _payload_row(1, "2025-12-03 10:00:01.000", "30f5-277a-5a2f", "STANDBY", 24, 34),
        _payload_row(2, "2025-12-03 10:00:02.000", "30f5-277a-5a2f", "ACTIVE", 25, 35),
        _payload_row(3, "2025-12-03 10:00:02.000", "30f5-277a-5a3f", "ACTIVE", 45, 47),
    ]
    payload = build_chart_payload({"anchor": rows[0], "rows": rows}, {"anchor": rows[0], "rows": rows, "events": []})
    assert payload["no_active_indices"].tolist() == [0]
    assert payload["multi_active_indices"].tolist() == [1]
    assert np.isnan(payload["active_series"]["active_local_rssi"][0])
    assert np.isnan(payload["active_series"]["active_local_rssi"][1])
















def test_active_switch_event_uses_raw_positive_rssi(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    first = LINE_A.replace("36/43", "24/34")
    second = LINE_B.replace("37/44", "44/46")
    source = tmp_path / "meshlog.log"
    source.write_text("\n".join(["[1] 2025/12/03 10:00:01.000", first, "[1] 2025/12/03 10:00:02.000", second]), encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    _, events = repo.query_events(100, 0)
    switch = next(event for event in events if event["event_type"] == EVENT_ACTIVE_SWITCH)
    details = json.loads(str(switch["details_json"]))
    assert details["from_local_rssi"] == 24
    assert details["to_local_rssi"] == 44
    assert details["from_peer_rssi"] == 34
    assert details["to_peer_rssi"] == 46
    assert details["from_local_signal_dbm"] < 0
    assert details["to_local_signal_dbm"] < 0


def test_aba_active_switch_events_are_not_merged_and_return_is_rapid_flap(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    source = tmp_path / "meshlog.log"
    source.write_text(
        "\n".join(
            [
                "[1] 2025/12/03 10:00:01.000",
                LINE_A,
                "[1] 2025/12/03 10:00:02.000",
                LINE_B,
                "[1] 2025/12/03 10:00:03.000",
                LINE_A,
            ]
        ),
        encoding="utf-8",
    )
    MeshImportService("demo", paths).import_files(profile, [source])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    _, events = repo.query_events(100, 0)
    switches = [event for event in events if event["event_type"] == EVENT_ACTIVE_SWITCH]
    assert [event["event_time"] for event in switches] == ["2025-12-03 10:00:02.000", "2025-12-03 10:00:03.000"]
    assert switches[0]["from_peer_mac"] == "30f5-277a-5a2f"
    assert switches[0]["to_peer_mac"] == "30f5-277a-5a3f"
    assert switches[1]["from_peer_mac"] == "30f5-277a-5a3f"
    assert switches[1]["to_peer_mac"] == "30f5-277a-5a2f"
    details = json.loads(str(switches[1]["details_json"]))
    assert details["is_rapid_flap"] is True
    assert details["rapid_flap_middle_peer"] == "30f5277a5a3f"


def test_mesh_repository_lists_pages_in_record_sequence_order(tmp_path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("14CW-01")
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    first.write_text("[1] 2025/12/03 10:00:01.000\n" + LINE_A + "\n", encoding="utf-8")
    second.write_text("[1] 2025/12/03 10:00:03.000\n" + LINE_B + "\n", encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [second, first])
    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    _, links = repo.query_links(1, 0)
    assert links[0]["sample_time"] == "2025-12-03 10:00:03.000"
    assert links[0]["source_file_order"] == 1
    _, events = repo.query_events(10, 0)
    assert [event["event_time"] for event in events if event["event_type"] == EVENT_ACTIVE_SWITCH] == []
    sources = repo.list_source_files()
    assert [source["first_sample_time"] for source in sources] == ["2025-12-03 10:00:01.000", "2025-12-03 10:00:03.000"]
    first_detail = Path(sources[0]["parsed_db_path"])
    with sqlite3.connect(first_detail) as conn:
        conn.execute(
            """
            INSERT INTO parse_issues (source_file_id, source_file, line_number, severity, issue_type, field_name, message, raw_line_start, raw_line_end)
            VALUES (1, 'z.log', 9, 'ERROR', 'x', 'x', 'x', 9, 9), (1, 'a.log', 2, 'ERROR', 'x', 'x', 'x', 2, 2)
            """
        )
    _, issues = repo.query_issues(10, 0)
    assert [(issue["source_file"], issue["line_number"]) for issue in issues] == [("a.log", 2), ("z.log", 9)]






















def _insert_mesh_samples(db_path, first_count: int, second_count: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO source_files (
                mr_id, original_path, archived_path, original_filename, archived_filename, sha256,
                file_size, file_mtime, imported_at, parser_version, parse_status
            ) VALUES ('mr', 'a.log', 'a.log', 'a.log', 'a.log', 'sha', 1, NULL, '2025-12-03 00:00:00.000', 'test', 'ok')
            """
        )
        rows = []
        links = []
        link_id = 1
        first_start = datetime(2025, 12, 3, 10, 0, 0)
        second_start = datetime.fromtimestamp(first_start.timestamp() + first_count + 1800)
        for run_start, count in ((first_start, first_count), (second_start, second_count)):
            for index in range(count):
                sample_time = run_start.timestamp() + index
                dt = datetime.fromtimestamp(sample_time).strftime("%Y-%m-%d %H:%M:%S.000")
                rows.append((link_id, 1, 1, dt, int(sample_time * 1000), ""))
                links.append(
                        (
                            link_id,
                            link_id,
                            1,
                            1,
                            link_id,
                            1,
                        1,
                        dt,
                        "Active",
                        "ACTIVE",
                        "30f5-277a-5a2f",
                        "30f5277a5a2f",
                        "2025-12-03 09:59:00.000",
                        "0d 00h 00m 01s",
                        1,
                        "s1",
                        36,
                        43,
                        f"fp-{link_id}",
                    )
                )
                link_id += 1
        conn.executemany("INSERT INTO samples(id, source_file_id, radio, sample_time, sample_time_epoch_ms, timestamp_tag) VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.executemany(
            """
                INSERT INTO mesh_links (
                    id, sample_id, source_file_id, source_file_order, record_seq, source_line_number, radio, sample_time,
                    link_state_raw, link_state, peer_mac_raw, peer_mac_normalized, establish_time,
                    duration_text, duration_seconds, session_id, local_rssi_db, peer_rssi_db, record_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
            links,
        )
    MeshMrRepository(db_path).rebuild_derived_analysis()


def _active_point(sample_time: str, peer: str, ap_mac: str, ap_name: str, peer_radio: str) -> dict[str, object]:
    normalized = "".join(character for character in peer.lower() if character in "0123456789abcdef")
    return {
        "id": int(datetime.fromisoformat(sample_time).timestamp() * 1000),
        "source_file_id": 1,
        "radio": 1,
        "sample_time": sample_time,
        "peer_mac_raw": peer,
        "peer_mac_normalized": normalized,
        "peer_mac": normalized,
        "peer_ap_name": ap_name,
        "peer_site": "03横溪站",
        "peer_radio": peer_radio,
        "peer_radio_label": peer_radio,
        "peer_ap_mac": ap_mac,
        "peer_radio_mac": peer,
        "duration_seconds": 1,
        "local_rssi_db": 35,
        "peer_rssi_db": 38,
        "local_tx_busy": 1,
        "local_rx_busy": 3,
        "peer_tx_busy": 1,
        "peer_rx_busy": 3,
        "source_file": "mesh.log",
    }


def _chart_row(link_id: int, sample_time: str) -> dict[str, object]:
    return {
        "id": link_id,
        "sample_time": sample_time,
        "peer_mac_normalized": "30f5277a5a2f",
        "peer_mac_raw": "30f5-277a-5a2f",
        "link_state": "ACTIVE",
        "metrics_json": '{"local_rssi_db": 36, "peer_rssi_db": 43, "local_tx_busy": 3, "peer_tx_busy": 4, "local_rx_busy": 5, "peer_rx_busy": 6}',
        "deltas_json": "{}",
        "metrics": {"local_rssi_db": 36, "peer_rssi_db": 43, "local_tx_busy": 3, "peer_tx_busy": 4, "local_rx_busy": 5, "peer_rx_busy": 6},
        "deltas": {},
    }


def _payload_row(
    link_id: int,
    sample_time: str,
    peer_mac: str,
    state: str,
    local_rssi: int | None,
    peer_rssi: int | None,
    local_tx_busy: int = 3,
    local_rx_busy: int = 5,
    source_file_id: int = 1,
    radio: int = 1,
) -> dict[str, object]:
    normalized = "".join(character for character in peer_mac.lower() if character in "0123456789abcdef")
    return {
        "id": link_id,
        "source_file_id": source_file_id,
        "radio": radio,
        "sample_time": sample_time,
        "peer_mac_normalized": normalized,
        "peer_mac_raw": peer_mac,
        "link_state": state,
        "metrics_json": json.dumps({"local_rssi_db": local_rssi, "peer_rssi_db": peer_rssi, "local_tx_busy": local_tx_busy, "local_rx_busy": local_rx_busy}),
        "deltas_json": "{}",
        "metrics": {
            "local_rssi_db": local_rssi,
            "peer_rssi_db": peer_rssi,
            "local_tx_busy": local_tx_busy,
            "peer_tx_busy": 4,
            "local_rx_busy": local_rx_busy,
            "peer_rx_busy": 6,
        },
        "deltas": {},
    }


def _chart_payload(count: int, anchor_index: int) -> dict[str, object]:
    timestamps = [datetime.fromtimestamp(datetime(2025, 12, 3, 10, 0, 0).timestamp() + index) for index in range(count)]
    labels = [value.strftime("%Y-%m-%d %H:%M:%S.000") for value in timestamps]
    numeric = np.asarray([date2num(value) for value in timestamps], dtype=np.float64)
    peer = {
        "local_rssi": np.linspace(30, 60, count, dtype=np.float32),
        "peer_rssi": np.linspace(40, 70, count, dtype=np.float32),
        "local_noise": np.full(count, 88, dtype=np.float32),
        "peer_noise": np.full(count, 105, dtype=np.float32),
        "local_tx_busy": np.full(count, 3, dtype=np.float32),
        "peer_tx_busy": np.full(count, 4, dtype=np.float32),
        "local_rx_busy": np.full(count, 5, dtype=np.float32),
        "peer_rx_busy": np.full(count, 6, dtype=np.float32),
        "state": np.ones(count, dtype=np.int8),
    }
    active = {
        "active_local_rssi": peer["local_rssi"].copy(),
        "active_local_tx_busy": peer["local_tx_busy"].copy(),
        "active_local_rx_busy": peer["local_rx_busy"].copy(),
    }
    return {
        "metadata": {
            "anchor": {"peer_mac_normalized": "30f5277a5a2f"},
            "anchor_index": anchor_index,
            "anchor_sample_time": labels[anchor_index],
            "segment_start": labels[0],
            "segment_end": labels[-1],
            "estimated_interval_seconds": 1.0,
            "sample_count": count,
            "peer_sample_count": count,
            "backend": "matplotlib-cpu",
        },
        "timestamps": timestamps,
        "timestamp_labels": labels,
        "timestamp_numeric": numeric,
        "peer_series": peer,
        "active_series": active,
        "active_peer_macs": ["30f5277a5a2f"] * count,
        "peer_macs": ["30f5277a5a2f"] * count,
        "peer_link_states": ["ACTIVE"] * count,
        "peer_establish_times": ["2025-12-03 09:59:00.000"] * count,
        "peer_session_ids": ["s1"] * count,
        "session_options": [{"session_id": "s1", "first_sample_time": labels[0], "last_sample_time": labels[-1]}],
        "events_by_index": {},
        "switch_indices": np.asarray([anchor_index], dtype=np.int32),
        "no_active_indices": np.asarray([], dtype=np.int32),
        "multi_active_indices": np.asarray([], dtype=np.int32),
        "peer_change_indices": np.asarray([], dtype=np.int32),
        "important_indices": np.asarray([anchor_index], dtype=np.int32),
    }


def _chart_payload_from_labels(labels: list[str], anchor_index: int) -> dict[str, object]:
    payload = _chart_payload(len(labels), anchor_index)
    timestamps = [datetime.fromisoformat(label) for label in labels]
    payload["timestamps"] = timestamps
    payload["timestamp_labels"] = labels
    payload["timestamp_numeric"] = np.asarray([date2num(value) for value in timestamps], dtype=np.float64)
    payload["metadata"]["anchor_sample_time"] = labels[anchor_index]
    payload["metadata"]["segment_start"] = labels[0]
    payload["metadata"]["segment_end"] = labels[-1]
    return payload
