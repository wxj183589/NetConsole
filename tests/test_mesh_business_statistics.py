from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta

import pytest
from openpyxl import load_workbook

from netconsole.models.mesh_analysis_params import normalize_mesh_analysis_params
from netconsole.services.mesh_analysis_params_service import resolve_mesh_task_params
from netconsole.services.mesh_analysis_excel_report import (
    MeshAnalysisExcelReportExporter,
)
from netconsole.services.mesh_analysis_report import (
    MeshAnalysisReportModel,
    MeshReportOptions,
)
from netconsole.services.mesh_business_statistics import (
    build_mesh_business_statistics,
    business_sort_key,
    effective_business_rules,
    iter_business_links,
    statistics_page,
)
from netconsole.services.mesh_link_detail_export import (
    AP_SIGNAL_COLUMNS,
    BUSINESS_LINK_COLUMNS,
    LINK_DETAIL_EXPORT_COLUMNS,
    MeshLinkDetailExportCancelled,
    export_mesh_link_details_xlsx,
)
from netconsole.services.mesh_quality_analysis import MeshQualityRules
from netconsole.services.rail_transit.mesh_ap_location_service import (
    MeshApLocation,
    MeshApLocationSnapshot,
)


AP = "0011-2233-4400"
PEER = "001122334401"
OTHER = "001122335501"


def row(second=0, *, radio=1, source=1, peer=PEER, state="ACTIVE", rssi=40, **extra):
    return {
        "id": second * 10 + radio,
        "sample_id": second + 1,
        "sample_time": (datetime(2026, 1, 1) + timedelta(seconds=second)).isoformat(
            sep=" "
        ),
        "source_file_id": source,
        "radio": radio,
        "peer_mac_raw": peer,
        "peer_mac_normalized": peer,
        "link_state": state,
        "local_rssi_db": rssi,
        "source_line_number": second + 100,
        "link_count": 2,
        **extra,
    }


def snapshot():
    return MeshApLocationSnapshot(
        [
            MeshApLocation(
                mac=AP,
                alias_mac=PEER,
                name="同名AP",
                station="站一",
                section="区间一",
                identity_status="matched",
            ),
            MeshApLocation(
                mac=AP,
                alias_mac="001122334402",
                name="不同名字",
                station="站一",
                identity_status="matched",
            ),
            MeshApLocation(
                mac="0011-2233-5500",
                alias_mac=OTHER,
                name="同名AP",
                station="站二",
                identity_status="matched",
            ),
        ]
    )


def stats(rows, *, rules=None, locations=None, minimum=2, **kwargs):
    return build_mesh_business_statistics(
        sorted(rows, key=business_sort_key),
        rules or MeshQualityRules(),
        locations or snapshot(),
        minimum_samples=minimum,
        **kwargs,
    )


def test_physical_identity_merges_radios_and_names_but_never_same_name_devices():
    result = stats([row(), row(1, radio=2, peer="001122334402"), row(2, peer=OTHER)])
    assert result["summary"]["ap_total"] == 2
    first = next(ap for ap in result["aps"] if ap["peer_ap_mac"] == AP)
    assert first["valid_sample_count"] == 2
    assert first["signal_grade"] == "GOOD"
    assert result["summary"]["grades"]["INSUFFICIENT"] == 1


@pytest.mark.parametrize("value", [None, "", "bad", 0, -1, float("nan"), float("inf")])
def test_invalid_active_rssi_is_not_a_sample_and_peer_rssi_cannot_replace_it(value):
    ap = stats([row(rssi=value, peer_rssi_db=60)])["aps"][0]
    assert ap["valid_sample_count"] == 0
    assert ap["avg_rssi"] is None
    assert ap["signal_grade"] == "INSUFFICIENT"


def test_exact_p10_full_samples_standby_excluded_and_threshold_changes():
    rows = [row(i, rssi=20 + i) for i in range(10)]
    rows += [row(i, peer=OTHER, state="STANDBY", rssi=100) for i in range(10)]
    ap = stats(rows)["aps"][0]
    assert (ap["p10_rssi"], ap["avg_rssi"], ap["min_rssi"], ap["max_rssi"]) == (
        20.9,
        24.5,
        20,
        29,
    )
    assert (ap["valid_sample_count"], ap["weak_sample_count"], ap["weak_ratio"]) == (
        10,
        10,
        1,
    )
    assert ap["signal_grade"] == "BAD"
    rules = effective_business_rules(
        normalize_mesh_analysis_params(
            {"rssi_good_threshold": 20, "rssi_warning_threshold": 15}
        ),
        MeshQualityRules(),
    )
    assert stats(rows, rules=rules)["aps"][0]["signal_grade"] == "GOOD"
    assert MeshQualityRules().rssi_good_threshold == 30


def test_unresolved_and_ambiguous_identity_stay_out_of_physical_total():
    unresolved = stats([row(peer="aabbccddeeff")])
    assert unresolved["summary"]["ap_total"] == 0
    assert unresolved["aps"][0]["peer_mac_raw"] == "aabbccddeeff"
    ambiguous = MeshApLocationSnapshot(
        [
            MeshApLocation(mac=AP, alias_mac=PEER, identity_status="matched"),
            MeshApLocation(
                mac="0011-2233-5500", alias_mac=PEER, identity_status="matched"
            ),
        ]
    )
    result = stats([row(peer_ap_mac=AP)], locations=ambiguous)
    assert result["summary"]["grades"]["UNRECOGNIZED"] == 1


@pytest.mark.parametrize(
    ("backup", "peer_rssi", "expected"),
    [
        (None, None, "MISSING_STANDBY_RSSI"),
        (20, 90, "WEAK_STANDBY"),
        (0, 90, "WEAK_STANDBY"),
        (30, None, None),
        (None, 40, None),
    ],
)
def test_backup_reuses_core_rssi_fallback_and_ignores_linkcnt(
    backup, peer_rssi, expected
):
    rows = [
        row(),
        row(peer=OTHER, state="STANDBY", rssi=backup, peer_rssi_db=peer_rssi),
    ]
    result = stats(rows)
    assert len(result["single_links"]) == int(expected is not None)
    if expected:
        assert result["single_links"][0]["risk_type"] == expected
    assert result["aps"][0]["valid_sample_count"] == 1


def test_intervals_split_at_source_radio_physical_ap_risk_kind_and_gap():
    rows = [row(i) for i in range(7)]
    rows += [row(7, peer="001122334402"), row(8, peer=OTHER), row(12, peer=OTHER)]
    rows += [row(12, peer=PEER, state="STANDBY", rssi=10)]
    rows += [row(13, peer=OTHER), row(0, radio=2), row(0, source=2)]
    result = stats(rows)
    intervals = result["single_links"]
    continuous = next(item for item in intervals if item["duration_seconds"] == 7)
    assert continuous["sample_count"] == 8
    assert continuous["source_line_number_start"] == 100
    assert continuous["source_line_number_end"] == 107
    assert continuous["qualifies_no_backup_event"] is True
    assert len(intervals) == 6
    assert result["summary"]["single_link_seconds"] == 7
    assert set(result["summary"]["single_link_radios"]) == {1, 2}


def test_same_second_tag_isolation_multi_active_and_gap_boundary():
    first = row(sample_id=None, timestamp_tag="2")
    second = row(peer=OTHER, sample_id=None, timestamp_tag="4")
    assert len(stats([first, second])["aps"]) == 2
    assert not stats([row(), row(peer=OTHER)])["aps"]


def test_legacy_sqlite_metrics_cursor_is_readonly_and_source_scoped(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE mesh_links (id INTEGER, source_file_id INTEGER, sample_time TEXT, radio INTEGER, peer_mac_raw TEXT, link_state TEXT, metrics_json TEXT)"
        )
        conn.executemany(
            "INSERT INTO mesh_links VALUES (?, ?, ?, 1, ?, 'ACTIVE', ?)",
            [
                (1, 1, "2026-01-01 00:00:00.100", PEER, '{"local_rssi_db":40}'),
                (2, 2, "2026-01-01 00:00:00.100", OTHER, '{"local_rssi_db":5}'),
            ],
        )
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        result = stats(iter_business_links(conn, 1))
    finally:
        conn.close()
    assert result["aps"][0]["avg_rssi"] == 40
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_sqlite_page_search_station_grade_sort_and_nulls():
    rows = [
        dict(peer_ap_name="同名AP", station="站一", signal_grade="BAD", avg_rssi=value)
        for value in [20, 10, None]
    ]
    page, total = statistics_page(
        rows,
        page=2,
        page_size=1,
        query="同名",
        station="站一",
        grade="BAD",
        sort_by="avg_rssi",
        descending=True,
    )
    assert total == 3
    assert page[0]["avg_rssi"] == 10
    assert statistics_page(rows, page=1, page_size=10, station="站")[1] == 0


def test_recognized_page_matches_physical_ap_total():
    result = stats([row(), row(1, peer=OTHER), row(2, peer="aabbccddeeff")])
    page, total = statistics_page(
        result["aps"], page=1, page_size=10, grade="RECOGNIZED"
    )
    assert total == result["summary"]["ap_total"] == 2
    assert all(item["peer_ap_mac"] for item in page)


def test_query_maps_invalid_effective_params_to_422():
    from fastapi import HTTPException
    from netconsole.backend.api.mesh_analysis_router import _query
    from netconsole.services.mesh_business_statistics import MeshBusinessParamsError

    def invalid():
        raise MeshBusinessParamsError("invalid thresholds")

    with pytest.raises(HTTPException) as error:
        _query(invalid)
    assert error.value.status_code == 422


def test_query_recomputes_after_wal_threshold_and_identity_changes(tmp_path, monkeypatch):
    from contextlib import closing
    from types import SimpleNamespace

    from netconsole.core.paths import PathResolver
    from netconsole.services.rail_transit import mesh_analysis_query_service as query

    database = tmp_path / "business.sqlite"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "CREATE TABLE mesh_links (id INTEGER, sample_id INTEGER, source_file_id INTEGER, "
            "sample_time TEXT, radio INTEGER, link_state TEXT, peer_mac_normalized TEXT, local_rssi_db REAL)"
        )
        writer.executemany(
            "INSERT INTO mesh_links VALUES (?, ?, 1, ?, 1, 'ACTIVE', ?, 40)",
            [(i, i, f"2026-01-01 00:00:0{i}", PEER) for i in (1, 2)],
        )
        writer.commit()
        service = query.MeshAnalysisQueryService(
            PathResolver(app_root=tmp_path, data_root=tmp_path), schedule_catalog_index=False
        )
        monkeypatch.setattr(service, "_context", lambda *_: SimpleNamespace(detail_db=database, detail_source_id=1))
        monkeypatch.setattr(service, "_ap_map", lambda *_: snapshot())
        params = {"ap_minimum_samples": 2}
        monkeypatch.setattr(query, "load_site_mesh_analysis_params", lambda *_: normalize_mesh_analysis_params(params))
        assert service.business_statistics("site", "session")["summary"]["grades"]["GOOD"] == 1
        writer.execute("UPDATE mesh_links SET local_rssi_db = 26")
        writer.commit()
        assert service.business_statistics("site", "session")["aps"][0]["avg_rssi"] == 26
        params["rssi_warning_threshold"] = 27
        assert service.business_statistics("site", "session")["summary"]["grades"]["BAD"] == 1
        monkeypatch.setattr(service, "_ap_map", lambda *_: MeshApLocationSnapshot([]))
        summary = service.business_statistics("site", "session")["summary"]
        assert summary["ap_total"] == 0
        assert summary["grades"]["UNRECOGNIZED"] == 1


def test_partial_export_dto_preserves_site_inheritance():
    from netconsole.models.api.mesh_analysis import MeshLinkDetailExportRequestDTO

    payload = MeshLinkDetailExportRequestDTO(
        source_file_id=1,
        analysis_params_override={"backup_available_threshold": 38}
    )
    override = payload.analysis_params_override.model_dump(
        mode="python", exclude_unset=True
    )
    assert override == {"backup_available_threshold": 38}
    assert (
        resolve_mesh_task_params(
            {"ap_minimum_samples": 22}, override
        ).ap_minimum_samples
        == 22
    )


def test_task_site_resource_precedence_and_invalid_combination():
    params = resolve_mesh_task_params(
        {
            "rssi_good_threshold": 45,
            "rssi_warning_threshold": 35,
            "ap_minimum_samples": 22,
        },
        {"backup_available_threshold": 38},
    )
    assert (
        params.rssi_good_threshold,
        params.backup_available_threshold,
        params.ap_minimum_samples,
    ) == (45, 38, 22)
    assert (
        resolve_mesh_task_params(
            params.to_dict(), {"rssi_good_threshold": None}
        ).rssi_good_threshold
        == 45
    )
    with pytest.raises(ValueError, match="关注阈值"):
        resolve_mesh_task_params({}, {"rssi_good_threshold": 20})


@pytest.mark.parametrize("mode", ["business", "diagnostic"])
@pytest.mark.parametrize("empty", [True, False])
def test_detail_xlsx_modes_counts_styles_and_statistics(tmp_path, mode, empty):
    rows = [] if empty else [row(i, rssi=25) for i in range(3)]
    business = stats(rows)
    path = tmp_path / f"{mode}.xlsx"
    export_mesh_link_details_xlsx(
        path,
        iter(rows),
        [],
        total_rows=len(rows),
        export_mode=mode,
        business_statistics=business,
    )
    book = load_workbook(path)
    detail = book["链路明细"]
    columns = (
        BUSINESS_LINK_COLUMNS if mode == "business" else LINK_DETAIL_EXPORT_COLUMNS
    )
    assert [cell.value for cell in detail[1]] == [label for label, _ in columns]
    assert detail.freeze_panes == "A2"
    assert detail.auto_filter.ref
    quality = book["AP 信号质量"]
    assert [cell.value for cell in quality[1]] == [
        label for label, _ in AP_SIGNAL_COLUMNS
    ]
    if rows:
        assert detail.max_row == 4
        weak = next(
            i for i, (_, key) in enumerate(AP_SIGNAL_COLUMNS) if key == "weak_ratio"
        )
        assert quality[2][weak].number_format == "0.00%"
        assert quality["B2"].value == AP
    book.close()


def test_report_business_default_and_percent_format_without_mutating_intervals(
    tmp_path,
):
    business = stats([row(i, rssi=25) for i in range(3)])
    model = MeshAnalysisReportModel(
        mr_name="fixture",
        report_name="fixture",
        generated_at=datetime.now(),
        options=MeshReportOptions(),
        ap_signal_quality=business["aps"],
        single_link_intervals=business["single_links"],
    )
    book = load_workbook(
        MeshAnalysisExcelReportExporter().export(model, tmp_path / "report.xlsx")
    )
    assert book["主链路建链顺序"].max_column == 16
    field = next(
        i for i, (_, key) in enumerate(AP_SIGNAL_COLUMNS) if key == "weak_ratio"
    )
    assert book["AP 信号质量"][2][field].number_format == "0.00%"
    assert "sequence" not in business["single_links"][0]
    book.close()


def test_business_aggregation_cancellation():
    with pytest.raises(MeshLinkDetailExportCancelled):
        stats([row()], should_cancel=lambda: True)


@pytest.mark.parametrize("mode", ["business", "diagnostic"])
def test_detail_xlsx_supports_zip64_sheet_members(tmp_path, monkeypatch, mode):
    import zipfile

    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 1024)
    path = tmp_path / "zip64.xlsx"
    export_mesh_link_details_xlsx(path, [row(i) for i in range(20)], [], total_rows=20, export_mode=mode)
    with zipfile.ZipFile(path) as archive:
        assert any(member.extract_version == 45 for member in archive.infolist())
    book = load_workbook(path, read_only=True)
    assert len(list(book["链路明细"].rows)) == 21
    book.close()
