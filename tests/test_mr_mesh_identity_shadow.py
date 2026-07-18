from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from netconsole.services.ap_identity import ApMatchResult, ApMatchStatus
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.mesh_import_service import MeshImportResult
from netconsole.services.mr_mesh_identity_shadow import MrMeshIdentityShadowService
from netconsole.services.rail_transit.online_mr_diagnosis_parser import (
    OnlineMrParseSummary,
)
from netconsole.services.vehicle_mr_online import VehicleMrTrainMapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resource(
    ap_uuid: str,
    ap_name: str,
    ap_mac: str,
    *,
    ac_uuid: str = "ac-1",
    **extra: object,
) -> dict[str, object]:
    return {
        "ap_uuid": ap_uuid,
        "ap_name": ap_name,
        "ap_mac": ap_mac,
        "ac_device_uuid": ac_uuid,
        **extra,
    }


def _candidates(*rows: dict[str, object]):
    return MrMeshIdentityShadowService().build_candidates(rows)


def test_candidate_snapshot_is_read_only_deduplicated_and_accepts_h3c_mac() -> None:
    fit_rows = [_resource("ap-1", "AP-01", "0011-2233-4455")]
    entity_rows = [_resource("ap-1", "AP-01", "00:11:22:33:44:55")]
    extension_rows = [{"ap_name": "AP-02", "ap_mac_display": "0066-7788-99aa"}]
    before = deepcopy((fit_rows, entity_rows, extension_rows))

    candidates = MrMeshIdentityShadowService().build_candidates(
        fit_rows, entity_rows, extension_rows
    )

    assert (fit_rows, entity_rows, extension_rows) == before
    assert len(candidates) == 2
    assert {candidate.identity.ap_mac for candidate in candidates} == {
        "00:11:22:33:44:55",
        "00:66:77:88:99:aa",
    }


def test_peer_mac_is_observation_and_does_not_default_to_ap_mac() -> None:
    service = MrMeshIdentityShadowService()
    candidates = service.build_candidates(
        [_resource("ap-1", "AP-01", "0011-2233-4455")]
    )
    result = {"parsed_record_count": 1}
    before = deepcopy(result)

    report = service.shadow_mesh_import_result(
        result,
        candidates,
        [{"peer_mac": "0011-2233-4455", "source_ref": "mesh:1"}],
    )

    assert result == before
    assert report.unresolved == 1
    assert report.matched == 0
    assert report.items[0].old_ap_key is None
    assert any("仅命中 AP MAC" in warning for warning in report.items[0].warnings)


def test_explicit_radio_mapping_matches_and_duplicate_peer_fields_only_warn() -> None:
    service = MrMeshIdentityShadowService()
    candidates = service.build_candidates(
        [_resource("ap-1", "AP-01", "0011-2233-4455", radio1_mac="0011-2233-4466")]
    )
    rows = [{"peer_mac": "0011-2233-4466", "peer_radio_mac": "00:11:22:33:44:66"}]
    before = deepcopy(rows)

    report = service.shadow_mesh_import_result({}, candidates, rows)

    assert rows == before
    assert report.matched == 1
    assert report.identity_changed == 1
    assert report.peer_mac_equals_peer_radio_mac == 1
    assert report.duplicate_mac_field_records == 1
    assert "peer_mac 与 peer_radio_mac" in " ".join(report.items[0].warnings)


def test_radio_or_bssid_without_explicit_candidate_mapping_is_unresolved() -> None:
    service = MrMeshIdentityShadowService()
    candidates = service.build_candidates(
        [_resource("ap-1", "AP-01", "0011-2233-4455")]
    )

    report = service.shadow_online_mr_parse_result(
        {},
        candidates,
        [{"bssid": "0011-2233-4466", "source_ref": "online:1"}],
    )

    assert report.unresolved == 1
    assert report.radio_or_bssid_only_records == 1


def test_same_mac_on_different_acs_remains_ambiguous_without_scope() -> None:
    service = MrMeshIdentityShadowService()
    candidates = service.build_candidates(
        [
            _resource("ap-1", "AP-01", "0011-2233-4455", ac_uuid="ac-1"),
            _resource("ap-2", "AP-02", "0011-2233-4455", ac_uuid="ac-2"),
        ]
    )

    report = service.shadow_mesh_import_result(
        {},
        candidates,
        [{"peer_ap_mac": "0011-2233-4455"}],
    )

    assert len(candidates) == 2
    assert report.ambiguous == 1
    assert report.missing_ac_scope == 1


def test_old_mapping_to_different_candidate_is_identity_changed() -> None:
    service = MrMeshIdentityShadowService()
    candidates = service.build_candidates(
        [
            _resource("ap-1", "AP-01", "0011-2233-4455"),
            _resource("ap-2", "AP-02", "0011-2233-4466"),
        ]
    )

    report = service.shadow_mesh_import_result(
        {},
        candidates,
        [{"peer_ap_mac": "0011-2233-4455"}],
    )

    assert report.matched == 1
    assert report.identity_changed == 0
    assert report.identity_unchanged == 1

    changed_service = MrMeshIdentityShadowService(
        SimpleNamespace(
            resolve=lambda _observation, _candidates: ApMatchResult(
                status=ApMatchStatus.MATCHED,
                candidate=candidates[1],
                candidates=(candidates[1],),
            )
        )
    )
    changed = changed_service.shadow_mesh_import_result(
        {},
        candidates,
        [{"peer_ap_name": "AP-01"}],
    )
    assert changed.identity_unchanged == 0
    assert changed.identity_changed == 1


def test_online_section_is_evidence_only_and_does_not_disambiguate_names() -> None:
    service = MrMeshIdentityShadowService()
    candidates = service.build_candidates(
        [
            _resource("ap-1", "AP-01", "0011-2233-4455", ac_uuid="ac-1", section="A-B"),
            _resource("ap-2", "AP-01", "0011-2233-4466", ac_uuid="ac-2", section="C-D"),
        ]
    )
    old_result = {"mesh_samples": 1, "issues": 0}
    before = deepcopy(old_result)

    report = service.shadow_online_mr_parse_result(
        old_result,
        candidates,
        [{"peer_name": "AP-01", "section": "A-B"}],
    )

    assert old_result == before
    assert report.ambiguous == 1
    assert report.missing_ac_scope == 1


def test_online_observation_ignores_old_resolved_name_and_other_derived_fields() -> (
    None
):
    service = MrMeshIdentityShadowService()

    observation = service.build_observation_from_online_mr_summary(
        {
            "resolved_peer_name": "AP-01",
            "interface_name": "WLAN-MESH1/0/1",
            "belonging_source": "old-mapping",
        }
    )

    assert observation.ap_name is None
    assert observation.interface_name is None
    assert observation.raw == {}


def test_online_duplicate_ap_and_radio_mac_fields_are_diagnostic_only() -> None:
    service = MrMeshIdentityShadowService()
    candidates = service.build_candidates(
        [_resource("ap-1", "AP-01", "0011-2233-4455", radio1_mac="0011-2233-4455")]
    )
    rows = [
        {
            "peer_mac": "0011-2233-4455",
            "peer_radio_mac": "0011-2233-4455",
            "peer_ap_mac": "0011-2233-4455",
        }
    ]

    report = service.shadow_online_mr_parse_result({}, candidates, rows)

    assert report.peer_mac_equals_peer_radio_mac == 1
    assert report.peer_mac_equals_ap_mac == 1
    assert report.duplicate_mac_field_records == 1
    assert rows[0]["peer_mac"] == "0011-2233-4455"


def test_vehicle_mapping_is_preserved_and_name_only_is_counted() -> None:
    service = MrMeshIdentityShadowService()
    candidates = service.build_candidates(
        [_resource("ap-1", "TRAIN-01-CT", "0011-2233-4455")]
    )
    old_result = {
        "mappings": [
            {"train_id": "01", "tc1_peer_name": "TRAIN-01-CT", "tc2_peer_name": ""}
        ],
        "count": 1,
    }
    before = deepcopy(old_result)

    report = service.shadow_vehicle_mr_mapping_result(old_result, candidates)

    assert old_result == before
    assert report.total == 1
    assert report.matched == 1
    assert report.name_only_matches == 1
    assert report.missing_ac_scope == 1
    assert "车端映射字段" in " ".join(report.items[0].warnings)


def test_online_shadow_rows_open_parsed_database_read_only(tmp_path: Path) -> None:
    db_path = tmp_path / "online_diagnosis.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE main_link_samples (
                session_id TEXT, radio INTEGER, peer_name TEXT, peer_mac TEXT,
                peer_mac_normalized TEXT, resolved_peer_name TEXT, bssid TEXT,
                mesh_interface TEXT, belong_station TEXT, belong_section TEXT,
                belong_type TEXT, belonging_source TEXT, raw_file TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO main_link_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "session-1",
                1,
                "AP-01",
                "0011-2233-4455",
                "001122334455",
                "AP-01",
                "",
                "WLAN-MESH1",
                "A站",
                "",
                "station",
                "fit_ap",
                "raw/mesh.log",
            ),
        )
    before = db_path.read_bytes()

    rows = legacy_tasks._online_mr_shadow_rows(db_path)

    assert rows[0]["peer_name"] == "AP-01"
    assert rows[0]["station"] == "A站"
    assert rows[0]["source_ref"].startswith("online-mr:session-1:")
    assert db_path.read_bytes() == before


def test_three_job_results_append_shadow_without_changing_old_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidates = _candidates(_resource("ap-1", "AP-01", "0011-2233-4455"))
    monkeypatch.setattr(
        legacy_tasks, "_mr_mesh_shadow_candidates", lambda *_args: candidates
    )
    monkeypatch.setattr(
        legacy_tasks,
        "_offline_mesh_shadow_rows",
        lambda *_args: [{"peer_ap_name": "AP-01", "peer_ap_mac": "0011-2233-4455"}],
    )
    monkeypatch.setattr(
        legacy_tasks,
        "_online_mr_shadow_rows",
        lambda *_args: [{"peer_name": "AP-01", "belonging_source": "ap_name"}],
    )

    from netconsole.services import mesh_import_service
    from netconsole.services import vehicle_mr_online
    from netconsole.services.rail_transit import online_mr_diagnosis_parser

    monkeypatch.setattr(
        mesh_import_service.MeshImportService,
        "import_files",
        lambda *_args, **_kwargs: MeshImportResult(
            files=[object()], imported_count=1, parsed_record_count=1
        ),
    )

    class FakeParser:
        def __init__(self, session_dir: Path) -> None:
            self.session_dir = session_dir
            self.db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
            self.meta = SimpleNamespace(site="demo")

        def parse(self, **_kwargs) -> OnlineMrParseSummary:
            return OnlineMrParseSummary(mesh_samples=1, active_segments=1)

    monkeypatch.setattr(
        online_mr_diagnosis_parser, "OnlineMrDiagnosisParser", FakeParser
    )
    monkeypatch.setattr(
        vehicle_mr_online.VehicleMrOnlineStore,
        "list_mappings",
        lambda _self: [VehicleMrTrainMapping(train_id="01", tc1_peer_name="AP-01")],
    )

    mesh = run_job(
        BackgroundJob(
            job_id="mesh-shadow",
            task_type="mesh_log_import",
            params={
                "site_name": "demo",
                "app_root": str(tmp_path),
                "data_root": str(tmp_path),
                "profile": {
                    "mr_id": "mr-1",
                    "display_name": "MR-1",
                    "safe_folder_name": "mr-1",
                    "relative_folder_path": "mr-1",
                },
                "files": [],
            },
        )
    )
    online = run_job(
        BackgroundJob(
            job_id="online-shadow",
            task_type="online_mr_parse",
            params={
                "session_dir": str(tmp_path / "session"),
                "data_root": str(tmp_path),
            },
        )
    )
    vehicle = run_job(
        BackgroundJob(
            job_id="vehicle-shadow",
            task_type="vehicle_mr_mapping_load",
            params={"site_name": "demo", "data_root": str(tmp_path)},
        )
    )

    assert mesh.ok is True
    assert {
        key: mesh.result[key]
        for key in (
            "imported_count",
            "duplicate_count",
            "parsed_record_count",
            "issue_count",
            "file_count",
        )
    } == {
        "imported_count": 1,
        "duplicate_count": 0,
        "parsed_record_count": 1,
        "issue_count": 0,
        "file_count": 1,
    }
    assert mesh.result["identity_shadow"]["available"] is True
    assert online.ok is True
    assert online.result["mesh_samples"] == 1
    assert online.result["active_segments"] == 1
    assert online.result["identity_shadow"]["available"] is True
    assert vehicle.ok is True
    assert vehicle.result["count"] == 1
    assert vehicle.result["mappings"][0]["tc1_peer_name"] == "AP-01"
    assert vehicle.result["identity_shadow"]["available"] is True


def test_shadow_failure_keeps_all_three_jobs_finished(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidates = _candidates(_resource("ap-1", "AP-01", "0011-2233-4455"))
    monkeypatch.setattr(
        legacy_tasks, "_mr_mesh_shadow_candidates", lambda *_args: candidates
    )
    monkeypatch.setattr(
        legacy_tasks,
        "_offline_mesh_shadow_rows",
        lambda *_args: [{"peer_mac": "0011-2233-4455"}],
    )
    monkeypatch.setattr(
        legacy_tasks,
        "_online_mr_shadow_rows",
        lambda *_args: [{"peer_mac": "0011-2233-4455"}],
    )

    from netconsole.services import mesh_import_service
    from netconsole.services import vehicle_mr_online
    from netconsole.services.mr_mesh_identity_shadow import MrMeshIdentityShadowService
    from netconsole.services.rail_transit import online_mr_diagnosis_parser

    monkeypatch.setattr(
        mesh_import_service.MeshImportService,
        "import_files",
        lambda *_args, **_kwargs: MeshImportResult(
            imported_count=1, parsed_record_count=2
        ),
    )
    monkeypatch.setattr(
        vehicle_mr_online.VehicleMrOnlineStore,
        "list_mappings",
        lambda _self: [VehicleMrTrainMapping(train_id="01", tc1_peer_name="AP-01")],
    )

    class FakeParser:
        def __init__(self, session_dir: Path) -> None:
            self.db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
            self.meta = SimpleNamespace(site="demo")

        def parse(self, **_kwargs) -> OnlineMrParseSummary:
            return OnlineMrParseSummary(mesh_samples=3)

    monkeypatch.setattr(
        online_mr_diagnosis_parser, "OnlineMrDiagnosisParser", FakeParser
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("shadow 诊断失败")

    monkeypatch.setattr(MrMeshIdentityShadowService, "shadow_mesh_import_result", fail)
    monkeypatch.setattr(
        MrMeshIdentityShadowService, "shadow_online_mr_parse_result", fail
    )
    monkeypatch.setattr(
        MrMeshIdentityShadowService, "shadow_vehicle_mr_mapping_result", fail
    )

    jobs = [
        BackgroundJob(
            job_id="mesh-shadow-failed",
            task_type="mesh_log_import",
            params={
                "site_name": "demo",
                "data_root": str(tmp_path),
                "profile": {
                    "mr_id": "mr-1",
                    "display_name": "MR-1",
                    "safe_folder_name": "mr-1",
                },
                "files": [],
            },
        ),
        BackgroundJob(
            job_id="online-shadow-failed",
            task_type="online_mr_parse",
            params={
                "session_dir": str(tmp_path / "session"),
                "data_root": str(tmp_path),
            },
        ),
        BackgroundJob(
            job_id="vehicle-shadow-failed",
            task_type="vehicle_mr_mapping_load",
            params={"site_name": "demo", "data_root": str(tmp_path)},
        ),
    ]

    results = [run_job(job) for job in jobs]

    assert all(result.ok is True for result in results)
    assert [result.result["identity_shadow"]["available"] for result in results] == [
        False,
        False,
        False,
    ]
    assert all(
        "shadow 诊断失败" in result.result["identity_shadow"]["warnings"][0]
        for result in results
    )
    assert results[0].result["parsed_record_count"] == 2
    assert results[1].result["mesh_samples"] == 3
    assert results[2].result["mappings"][0]["tc1_peer_name"] == "AP-01"


def test_shadow_static_boundaries_and_production_consumers_remain_unaware() -> None:
    shadow_source = (
        PROJECT_ROOT / "src" / "netconsole" / "services" / "mr_mesh_identity_shadow.py"
    ).read_text(encoding="utf-8")
    forbidden_consumers = (
        PROJECT_ROOT / "src" / "netconsole" / "parsers" / "mesh_log_parser.py",
        PROJECT_ROOT
        / "src"
        / "netconsole"
        / "services"
        / "rail_transit"
        / "online_mr_diagnosis_parser.py",
        PROJECT_ROOT
        / "src"
        / "netconsole"
        / "services"
        / "mesh_peer_mapping_service.py",
        PROJECT_ROOT / "src" / "netconsole" / "services" / "mesh_link_detail_export.py",
    )

    for forbidden in (
        "PySide6",
        "netconsole.ui",
        "repositories",
        "Database",
        "sqlite3",
        "subprocess",
        "netmiko",
        "socket",
    ):
        assert forbidden not in shadow_source
    for path in forbidden_consumers:
        assert "mr_mesh_identity_shadow" not in path.read_text(encoding="utf-8")
