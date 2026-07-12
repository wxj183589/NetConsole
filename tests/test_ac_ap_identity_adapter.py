from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ac.ac_identity_adapter import AcApIdentityAdapter
from netconsole.services.ap_identity import ApMatchStatus
from netconsole.services.job_center.handlers import ac_jobs, legacy_tasks
from netconsole.services.job_center.job_context import JobContext


def make_repository(tmp_path: Path) -> AcRepository:
    database = Database(tmp_path / "site.db")
    database.initialize()
    return AcRepository(database)


def make_context(tmp_path: Path, task_type: str, params: dict[str, object]) -> JobContext:
    return JobContext(
        job_id=f"job-{task_type}",
        task_type=task_type,
        params=params,
        progress_callback=None,
        should_cancel=None,
        paths=PathResolver(app_root=tmp_path, data_root=tmp_path / "data"),
    )


def fit_ap_row(
    ap_uuid: str,
    ap_mac: str,
    ap_name: str,
    ac_uuid: str = "ac-1",
    apid: str = "1",
    **extra,
) -> dict[str, object]:
    return {
        "ap_uuid": ap_uuid,
        "ap_mac": ap_mac,
        "ap_name": ap_name,
        "ac_device_uuid": ac_uuid,
        "apid": apid,
        **extra,
    }


def test_build_fit_ap_candidates_preserves_identity_radio_and_input():
    row = fit_ap_row(
        "ap-1",
        "AA-BB-CC-DD-EE-FF",
        "AP-01",
        apid="7",
        rid1_bbssid="00-11-22-33-44-55",
    )
    original = dict(row)

    result = AcApIdentityAdapter().build_fit_ap_candidates([row])

    assert row == original
    assert len(result) == 1
    assert result[0].identity.ap_uuid == "ap-1"
    assert result[0].identity.ac_uuid == "ac-1"
    assert result[0].identity.ap_id == "7"
    assert result[0].identity.ap_mac == "aa:bb:cc:dd:ee:ff"
    assert result[0].identity.ap_name == "AP-01"
    assert result[0].radios[0].radio_id == 1
    assert result[0].radios[0].bbssid == "00:11:22:33:44:55"


def test_build_extension_observations_preserves_name_location_and_input():
    rows = [
        {
            "ap_name": "AA-BB-CC-DD-EE-FF",
            "section_name": "A-B",
            "station_name": "",
            "mileage_text": "!Z!D!K1+020",
            "line_side": "左线",
            "direction": "下行",
        },
        {"ap_name": "AP-02", "ap_mac_display": "00-11-22-33-44-55"},
    ]
    original = [dict(row) for row in rows]

    observations = AcApIdentityAdapter().build_extension_observations(rows)

    assert rows == original
    assert observations[0].ap_name == "AA-BB-CC-DD-EE-FF"
    assert observations[0].ap_mac is None
    assert observations[0].station is None
    assert observations[0].section == "A-B"
    assert observations[0].mileage == "ZDK1+020"
    assert observations[1].ap_mac == "00:11:22:33:44:55"


def test_shadow_old_and_new_match_same_identity():
    resources = [fit_ap_row("ap-1", "AA-BB-CC-DD-EE-FF", "AP-01")]
    report = AcApIdentityAdapter().shadow_compare_extension_match(
        [{"id": 1, "ap_name": "AP-01", "ap_mac_display": "aabb.ccdd.eeff"}],
        resources,
    )

    assert report.total == 1
    assert report.matched == 1
    assert report.identity_unchanged == 1
    assert report.identity_changed == 0
    assert report.items[0].old_status == "matched_by_mac"
    assert report.items[0].new_candidate_key == "uuid:ap-1"
    json.dumps(report.to_payload(), ensure_ascii=False)


def test_shadow_old_match_new_unresolved_is_reported_without_blocking():
    resources = [fit_ap_row("ap-1", "", "unknown")]

    report = AcApIdentityAdapter().shadow_compare_extension_match([{"ap_name": "unknown"}], resources)

    assert report.unresolved == 1
    assert report.identity_changed == 1
    assert report.name_only_matches == 1
    assert report.items[0].old_status == "matched_by_name"
    assert "旧逻辑已匹配，新 resolver 未解析" in report.items[0].warnings


def test_shadow_old_match_new_ambiguous_is_reported():
    resources = [
        fit_ap_row("ap-1", "AA-BB-CC-DD-EE-FF", "AP-01", "ac-1"),
        fit_ap_row("ap-2", "AA-BB-CC-DD-EE-FF", "AP-02", "ac-2"),
    ]

    report = AcApIdentityAdapter().shadow_compare_extension_match(
        [{"ap_mac_display": "aa:bb:cc:dd:ee:ff"}],
        resources,
    )

    assert report.ambiguous == 1
    assert report.identity_changed == 1
    assert "旧逻辑已匹配，新 resolver 返回歧义" in report.items[0].warnings


def test_shadow_marks_different_old_and_new_candidates():
    resources = [
        fit_ap_row("ap-uuid", "00-11-22-33-44-55", "AP-UUID"),
        fit_ap_row("ap-mac", "AA-BB-CC-DD-EE-FF", "AP-MAC"),
    ]

    report = AcApIdentityAdapter().shadow_compare_extension_match(
        [{"ap_uuid": "ap-uuid", "ap_mac_display": "aa-bb-cc-dd-ee-ff"}],
        resources,
    )

    item = report.items[0]
    assert item.old_match_key == "mac:aa:bb:cc:dd:ee:ff"
    assert item.new_candidate_key == "uuid:ap-uuid"
    assert item.identity_changed
    assert "候选 identity 不一致" in item.warnings[-1]


def test_shadow_old_unresolved_new_matched_is_diagnostic_only():
    resources = [fit_ap_row("ap-1", "AA-BB-CC-DD-EE-FF", "AP-01")]

    report = AcApIdentityAdapter().shadow_compare_extension_match([{"ap_uuid": "ap-1"}], resources)

    assert report.matched == 1
    assert report.identity_changed == 1
    assert report.items[0].old_status == "unbound_no_mac"
    assert "仅记录，不改变写入" in report.items[0].warnings[-1]


def test_ac_scope_controls_apid_and_duplicate_mac_resolution():
    adapter = AcApIdentityAdapter()
    resources = [
        fit_ap_row("ap-1", "AA-BB-CC-DD-EE-FF", "AP-01", "ac-1", "7"),
        fit_ap_row("ap-2", "AA-BB-CC-DD-EE-FF", "AP-02", "ac-2", "7"),
    ]
    candidates = adapter.build_fit_ap_candidates(resources)

    unscoped_apid = adapter.resolve_extension_to_fit_ap({"apid": "7"}, candidates)
    scoped_apid = adapter.resolve_extension_to_fit_ap({"apid": "7", "ac_device_uuid": "ac-2"}, candidates)
    unscoped_mac = adapter.resolve_extension_to_fit_ap({"ap_mac_display": "AA-BB-CC-DD-EE-FF"}, candidates)
    scoped_mac = adapter.resolve_extension_to_fit_ap(
        {"ap_mac_display": "AA-BB-CC-DD-EE-FF", "ac_device_uuid": "ac-1"},
        candidates,
    )

    assert unscoped_apid.status is ApMatchStatus.UNRESOLVED
    assert scoped_apid.candidate is candidates[1]
    assert unscoped_mac.status is ApMatchStatus.AMBIGUOUS
    assert scoped_mac.candidate is candidates[0]


def test_location_radio_bssid_and_peer_protection_rules():
    adapter = AcApIdentityAdapter()
    resources = [fit_ap_row("ap-1", "AA-BB-CC-DD-EE-FF", "AP-01")]
    candidates = adapter.build_fit_ap_candidates(resources)

    assert adapter.resolve_extension_to_fit_ap(
        {"station_name": "Station-A", "section_name": "A-B", "mileage_text": "ZDK1+020"},
        candidates,
    ).status is ApMatchStatus.UNRESOLVED
    assert adapter.resolve_extension_to_fit_ap({"radio_mac": "AA-BB-CC-DD-EE-FF"}, candidates).status is ApMatchStatus.UNRESOLVED
    assert adapter.resolve_extension_to_fit_ap({"bssid": "AA-BB-CC-DD-EE-FF"}, candidates).status is ApMatchStatus.UNRESOLVED
    assert adapter.resolve_extension_to_fit_ap({"peer_mac": "AA-BB-CC-DD-EE-FF"}, candidates).status is ApMatchStatus.UNRESOLVED


def test_explicit_fit_ap_radio_mapping_can_resolve_extension_radio():
    adapter = AcApIdentityAdapter()
    resources = [
        fit_ap_row(
            "ap-1",
            "00-11-22-33-44-55",
            "AP-01",
            radio1_mac="AA-BB-CC-DD-EE-01",
            rid1_bbssid="AA-BB-CC-DD-EE-02",
        )
    ]
    candidates = adapter.build_fit_ap_candidates(resources)

    radio_result = adapter.resolve_extension_to_fit_ap({"radio_mac": "AA-BB-CC-DD-EE-01"}, candidates)
    bssid_result = adapter.resolve_extension_to_fit_ap({"rid1_bbssid": "AA-BB-CC-DD-EE-02"}, candidates)

    assert radio_result.status is ApMatchStatus.MATCHED
    assert bssid_result.status is ApMatchStatus.MATCHED


def test_preview_job_keeps_existing_fields_and_adds_shadow(monkeypatch, tmp_path):
    repository = make_repository(tmp_path)
    repository.replace_fit_ap_resources("ac-1", [fit_ap_row("ap-1", "AA-BB-CC-DD-EE-FF", "AP-01")])
    preview = SimpleNamespace(
        file_name="preview.xlsx",
        template_type="standard_template",
        confidence_score=100,
        sheets=[object()],
        summary={"total_rows": 1},
        low_confidence=False,
        standard_rows=[{"ap_name": "AP-01", "ap_mac_display": "AA-BB-CC-DD-EE-FF"}],
    )
    monkeypatch.setattr(ac_jobs.FitApImportExportService, "preview_ap_extension_import", lambda *_args, **_kwargs: preview)
    context = make_context(
        tmp_path,
        "fit_ap_extension_preview",
        {"db_path": str(repository.database.path), "path": "preview.xlsx", "import_mode": "standard_template"},
    )

    result = ac_jobs.fit_ap_extension_preview(context)

    assert result["file_name"] == "preview.xlsx"
    assert result["summary"] == {"total_rows": 1}
    assert result["low_confidence"] is False
    assert result["identity_shadow"]["matched"] == 1


def test_commit_job_uses_existing_commit_path_and_adds_shadow(monkeypatch, tmp_path):
    repository = make_repository(tmp_path)
    repository.replace_fit_ap_resources("ac-1", [fit_ap_row("ap-1", "AA-BB-CC-DD-EE-FF", "AP-01")])
    preview = SimpleNamespace(
        standard_rows=[{"ap_name": "AP-01", "ap_mac_display": "AA-BB-CC-DD-EE-FF"}],
    )
    calls: list[str] = []
    monkeypatch.setattr(ac_jobs.FitApImportExportService, "preview_ap_extension_import", lambda *_args, **_kwargs: preview)

    def fake_commit(_self, received_preview, duplicate_strategy="update_by_priority"):
        assert received_preview is preview
        calls.append(duplicate_strategy)
        return {"success_rows": 1, "updated_rows": 0, "skipped_rows": 0, "error_rows": 0}

    monkeypatch.setattr(ac_jobs.FitApImportExportService, "commit_ap_extension_import", fake_commit)
    context = make_context(
        tmp_path,
        "fit_ap_extension_commit",
        {"db_path": str(repository.database.path), "path": "preview.xlsx", "duplicate_strategy": "skip_existing"},
    )

    result = ac_jobs.fit_ap_extension_commit(context)

    assert calls == ["skip_existing"]
    assert result["success_rows"] == 1
    assert result["identity_shadow"]["matched"] == 1


def test_shadow_failure_does_not_block_existing_commit_path(monkeypatch, tmp_path):
    repository = make_repository(tmp_path)
    preview = SimpleNamespace(standard_rows=[{"ap_name": "AP-01"}])
    calls: list[bool] = []
    monkeypatch.setattr(ac_jobs.FitApImportExportService, "preview_ap_extension_import", lambda *_args, **_kwargs: preview)
    monkeypatch.setattr(
        ac_jobs.FitApImportExportService,
        "commit_ap_extension_import",
        lambda *_args, **_kwargs: calls.append(True) or {"success_rows": 1},
    )

    def fail_shadow(_self):
        raise RuntimeError("shadow failed")

    monkeypatch.setattr(ac_jobs.AcRepository, "list_all_fit_ap_resources_with_metadata", fail_shadow)
    context = make_context(
        tmp_path,
        "fit_ap_extension_commit",
        {"db_path": str(repository.database.path), "path": "preview.xlsx"},
    )

    result = ac_jobs.fit_ap_extension_commit(context)

    assert calls == [True]
    assert result["success_rows"] == 1
    assert result["identity_shadow"]["available"] is False
    assert "shadow failed" in result["identity_shadow"]["warnings"][0]


def test_save_job_calls_legacy_writer_and_shadow_does_not_replace_result(monkeypatch, tmp_path):
    repository = make_repository(tmp_path)
    repository.replace_fit_ap_resources("ac-1", [fit_ap_row("ap-1", "AA-BB-CC-DD-EE-FF", "AP-01")])
    calls: list[dict[str, object]] = []

    def fake_legacy(params, _progress, _cancel):
        calls.append(dict(params))
        return {"row": {"id": 9, **dict(params.get("row") or {})}}

    monkeypatch.setattr(legacy_tasks, "_ac_ap_extension_save", fake_legacy)
    params = {
        "db_path": str(repository.database.path),
        "row": {"ap_name": "AP-01", "ap_mac_display": "AA-BB-CC-DD-EE-FF"},
    }

    result = ac_jobs.ac_ap_extension_save(make_context(tmp_path, "ac_ap_extension_save", params))

    assert calls == [params]
    assert result["row"]["id"] == 9
    assert result["identity_shadow"]["matched"] == 1


def test_ac_identity_adapter_has_no_ui_database_or_repository_dependency():
    path = Path(__file__).parents[1] / "src" / "netconsole" / "services" / "ac" / "ac_identity_adapter.py"
    text = path.read_text(encoding="utf-8")

    assert "PySide6" not in text
    assert "netconsole.ui" not in text
    assert "netconsole.repositories" not in text
    assert "Database(" not in text
