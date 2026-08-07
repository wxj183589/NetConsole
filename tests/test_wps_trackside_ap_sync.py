from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.wps_sync import TRACKSIDE_AP_WPS_BUSINESS_KEY, WpsTargetType
from netconsole.repositories.wps_sync_repository import WpsSyncRepository
from netconsole.services.wps_trackside_ap_sync import (
    SMART_TARGET_CODE,
    STANDARD_TARGET_CODE,
    TracksideApWpsSyncService,
    WPS_SYNC_TASK_TYPE,
    workbook_dto_from_xlsx,
)


def _protect(data: bytes, entropy: bytes) -> bytes:
    return bytes(value ^ entropy[index % len(entropy)] for index, value in enumerate(data))


def test_wps_targets_keep_independent_encrypted_credentials(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    repository = WpsSyncRepository(paths, "hangzhou10", protect=_protect, unprotect=_protect)
    standard = repository.upsert_target(
        business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
        target_code=STANDARD_TARGET_CODE,
        target_type=WpsTargetType.STANDARD_SPREADSHEET,
        target_name="普通表格",
        document_open_url="https://example.test/standard",
        webhook_url="https://example.test/standard-hook",
        expected_document_id="standard",
        token="secret-token",
        credential_id="shared",
    )
    smart = repository.upsert_target(
        business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
        target_code=SMART_TARGET_CODE,
        target_type=WpsTargetType.SMART_SHEET,
        target_name="智能表格",
        document_open_url="https://example.test/smart",
        webhook_url="https://example.test/smart-hook",
        expected_document_id="smart",
        token="smart-token",
        credential_id="smart-credential",
    )
    assert standard.target_code != smart.target_code
    assert standard.credential_id == "shared"
    assert smart.credential_id == "smart-credential"
    assert repository.resolve_token(standard) == "secret-token"
    assert repository.resolve_token(smart) == "smart-token"
    public = standard.public_dict()
    assert public["webhook_url"] == "https://example.test/standard-hook"
    assert "secret-token" not in str(public)


def test_wps_target_configuration_rejects_non_kdocs_webhook(tmp_path: Path) -> None:
    from netconsole.services.wps_trackside_ap_sync import WpsSyncError

    service = TracksideApWpsSyncService(PathResolver(tmp_path))
    with pytest.raises(WpsSyncError, match="kdocs.cn"):
        service.configure_target(
            "hangzhou10",
            STANDARD_TARGET_CODE,
            webhook_url="https://localhost/api/sync_task",
        )


def test_workbook_dto_uses_append_mode_for_overview(tmp_path: Path) -> None:
    path = tmp_path / "sample.xlsx"
    workbook = Workbook()
    workbook.active.title = "轨旁AP业务"
    workbook.active.append(["站点", "AP"])
    workbook.active.append(["A", "AP-1"])
    overview = workbook.create_sheet("AP上线情况概览")
    overview.append(["同步时间", "上线率"])
    overview.append(["2026-08-07 10:00:00", 1])
    workbook.save(path)
    workbook.close()

    dto = workbook_dto_from_xlsx(path)
    assert [sheet.sheet_name for sheet in dto.sheets] == ["轨旁AP业务", "AP上线情况概览"]
    assert dto.sheets[0].sync_mode.value == "FULL_REPLACE"
    assert dto.sheets[1].sync_mode.value == "APPEND_SNAPSHOT"
    assert dto.sheets[1].row_count == 2


def test_default_target_initialization_splits_legacy_shared_credential(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    repository = WpsSyncRepository(paths, "hangzhou10", protect=_protect, unprotect=_protect)
    for code, target_type in (
        (STANDARD_TARGET_CODE, WpsTargetType.STANDARD_SPREADSHEET),
        (SMART_TARGET_CODE, WpsTargetType.SMART_SHEET),
    ):
        repository.upsert_target(
            business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
            target_code=code,
            target_type=target_type,
            target_name=code,
            document_open_url=f"https://www.kdocs.cn/l/{code}",
            webhook_url=f"https://www.kdocs.cn/api/{code}/sync_task",
            expected_document_id=code,
            token="legacy-token" if code == STANDARD_TARGET_CODE else None,
            credential_id="legacy-shared",
        )

    TracksideApWpsSyncService(paths)._ensure_default_targets(repository)

    targets = repository.list_targets(TRACKSIDE_AP_WPS_BUSINESS_KEY)
    assert len({target.credential_id for target in targets}) == 2
    assert {repository.resolve_token(target) for target in targets} == {"legacy-token"}


def test_dual_sync_reuses_one_snapshot_for_both_adapters(monkeypatch, tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def post(self, target, *, token, argv):
            assert token == "test-token"
            self.payloads.append(dict(argv))
            return type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "body": {
                        "success": True,
                        "protocol_version": 2,
                        "script_version": "test",
                        "target_type": target.target_type.value,
                        "document_id": target.expected_document_id,
                        "target_batch_id": argv.get("target_batch_id"),
                        "site_id": argv.get("site_id"),
                        "business_key": argv.get("business_key"),
                        "snapshot_revision": argv.get("snapshot_revision"),
                        "snapshot_sha256": argv.get("snapshot_sha256"),
                    },
                },
            )

    fake = FakeClient()
    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=fake)
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/test/sync_task",
    )
    service.configure_target(
        "hzl10",
        SMART_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/smart",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/smart/script/test/sync_task",
    )
    monkeypatch.setenv("NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN", "test-token")
    monkeypatch.setenv("NETCONSOLE_WPS_SMART_AIRSCRIPT_TOKEN", "test-token")
    monkeypatch.setattr(
        service,
        "_build_snapshot",
        lambda site_id: {
            "business_revision": "revision-1",
            "created_at": "2026-08-07T10:00:00+08:00",
        },
    )
    from netconsole.models.wps_sync import WorkbookDTO

    monkeypatch.setattr(
        service,
        "_build_workbook_dto",
        lambda site_id, batch_id, snapshot: (WorkbookDTO(sheets=()), "sha-1", 10),
    )
    result = service.sync("hzl10")
    assert result["status"] == "SUCCESS"
    assert [payload["snapshot_revision"] for payload in fake.payloads] == ["revision-1", "revision-1"]
    assert [payload["snapshot_sha256"] for payload in fake.payloads] == ["sha-1", "sha-1"]
    assert fake.payloads[0]["target_batch_id"] != fake.payloads[1]["target_batch_id"]


def test_wps_sync_is_registered_as_a_job_center_handler() -> None:
    from netconsole.services.job_center.job_registry import registered_task_types

    assert WPS_SYNC_TASK_TYPE in registered_task_types()
