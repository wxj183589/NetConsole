from __future__ import annotations

import io
import json
from pathlib import Path
import sqlite3
import urllib.error

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.wps_sync import (
    TRACKSIDE_AP_WPS_BUSINESS_KEY,
    WpsSyncTarget,
    WpsTargetType,
    build_wps_binding_id,
)
from netconsole.repositories.wps_sync_repository import WpsSyncRepository
from netconsole.services.wps_trackside_ap_sync import (
    SMART_TARGET_CODE,
    STANDARD_TARGET_CODE,
    TracksideApWpsSyncService,
    WpsAirScriptClient,
    WpsHttpResponse,
    WpsStandardSpreadsheetAdapter,
    WpsSyncError,
    WPS_DEPLOYMENT_IDS,
    WPS_SCRIPT_VERSIONS,
    WPS_STANDARD_FORMAT_MIRROR_EXPERIMENTAL,
    WPS_SYNC_TASK_TYPE,
    _assert_standard_sync_readiness,
    workbook_dto_from_xlsx,
)


def _protect(data: bytes, entropy: bytes) -> bytes:
    return bytes(value ^ entropy[index % len(entropy)] for index, value in enumerate(data))


def _wps_target() -> WpsSyncTarget:
    return WpsSyncTarget(
        target_id="target-1",
        site_id="demo",
        business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
        target_code=STANDARD_TARGET_CODE,
        target_type=WpsTargetType.STANDARD_SPREADSHEET,
        credential_id="credential-1",
        target_name="普通表格",
        document_open_url="https://www.kdocs.cn/l/document",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/document/script/test/sync_task",
        expected_document_id="document",
    )


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


def test_wps_binding_id_is_stable_across_independent_data_roots(tmp_path: Path) -> None:
    targets = []
    for root in (tmp_path / "first", tmp_path / "restored"):
        repository = WpsSyncRepository(
            PathResolver(data_root=root), "hzl10", protect=_protect, unprotect=_protect
        )
        targets.append(
            repository.upsert_target(
                business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
                target_code=STANDARD_TARGET_CODE,
                target_type=WpsTargetType.STANDARD_SPREADSHEET,
                target_name="普通表格",
                document_open_url="https://example.test/standard",
                webhook_url="https://example.test/standard-hook",
                expected_document_id="standard",
            )
        )

    assert targets[0].target_id != targets[1].target_id
    assert targets[0].binding_id == targets[1].binding_id
    assert targets[0].binding_id == build_wps_binding_id(
        "hzl10", TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE
    )
    assert build_wps_binding_id(
        "other-site", TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE
    ) != targets[0].binding_id


def test_wps_binding_id_migration_is_additive_repeatable_and_preserves_rows(
    tmp_path: Path,
) -> None:
    repository = WpsSyncRepository(
        PathResolver(tmp_path), "hzl10", protect=_protect, unprotect=_protect
    )
    original = repository.upsert_target(
        business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
        target_code=STANDARD_TARGET_CODE,
        target_type=WpsTargetType.STANDARD_SPREADSHEET,
        target_name="保留的普通表格",
        document_open_url="https://example.test/standard",
        webhook_url="https://example.test/standard-hook",
        expected_document_id="standard",
        token="preserved-token",
    )
    with sqlite3.connect(repository.path) as connection:
        connection.execute("ALTER TABLE wps_sync_targets DROP COLUMN binding_id")
        connection.commit()

    repository.initialize()
    repository.initialize()

    migrated = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    with sqlite3.connect(repository.path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(wps_sync_targets)")
        }
        row_count = connection.execute(
            "SELECT COUNT(*) FROM wps_sync_targets WHERE target_id = ?",
            (original.target_id,),
        ).fetchone()[0]
    assert "binding_id" in columns
    assert row_count == 1
    assert migrated.target_id == original.target_id
    assert migrated.target_name == "保留的普通表格"
    assert migrated.binding_id == build_wps_binding_id(
        "hzl10", TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE
    )
    assert repository.resolve_token(migrated) == "preserved-token"


def test_wps_target_configuration_rejects_non_kdocs_webhook(tmp_path: Path) -> None:
    service = TracksideApWpsSyncService(PathResolver(tmp_path))
    with pytest.raises(WpsSyncError, match="kdocs.cn"):
        service.configure_target(
            "hangzhou10",
            STANDARD_TARGET_CODE,
            webhook_url="https://localhost/api/sync_task",
        )


def test_wps_public_targets_expose_deployment_identity_and_disable_smart_by_default(
    tmp_path: Path,
) -> None:
    targets = TracksideApWpsSyncService(PathResolver(tmp_path)).list_targets("hangzhou10")
    by_code = {target["target_code"]: target for target in targets}

    assert by_code[SMART_TARGET_CODE]["enabled"] is False
    assert by_code[SMART_TARGET_CODE]["runtime_capability"] == "RUNTIME_UNVERIFIED"
    assert by_code[STANDARD_TARGET_CODE]["expected_script_version"] == WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE]
    assert by_code[STANDARD_TARGET_CODE]["expected_deployment_id"] == WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE]


def test_wps_public_target_does_not_trust_stale_bound_state_after_stable_id_migration(
    tmp_path: Path,
) -> None:
    service = TracksideApWpsSyncService(PathResolver(tmp_path))
    service.list_targets("hzl10")
    repository = service._repository("hzl10")
    target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    repository.update_target_remote_state(
        target.target_id,
        binding_status="BOUND",
        result={
            "remote_binding_id": f"wst_{'a' * 32}",
            "remote_site_id": target.site_id,
            "remote_business_key": target.business_key,
        },
        persist_runtime_identity=False,
    )

    refreshed = {item["target_code"]: item for item in service.list_targets("hzl10")}

    assert refreshed[STANDARD_TARGET_CODE]["binding_status"] == "UNKNOWN"
    assert refreshed[STANDARD_TARGET_CODE]["remote_binding_id"].startswith("wst_")


def test_wps_default_target_name_uses_site_display_name_and_preserves_custom_name(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    manager.create_site("hzl10", display_name="杭州地铁10号线")
    manager.create_site("nbl12", display_name="宁波地铁12号线")
    service = TracksideApWpsSyncService(paths)

    hzl10 = {item["target_code"]: item for item in service.list_targets("hzl10")}
    nbl12 = {item["target_code"]: item for item in service.list_targets("nbl12")}
    assert hzl10[STANDARD_TARGET_CODE]["target_name"] == "杭州地铁10号线轨旁AP业务-普通在线表格"
    assert nbl12[STANDARD_TARGET_CODE]["target_name"] == "宁波地铁12号线轨旁AP业务-普通在线表格"

    service.configure_target("hzl10", STANDARD_TARGET_CODE, document_open_url="https://www.kdocs.cn/l/custom")
    repository = service._repository("hzl10")
    target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    repository.upsert_target(
        business_key=target.business_key,
        target_code=target.target_code,
        target_type=target.target_type,
        target_name="用户自定义 WPS 文档",
        document_open_url=target.document_open_url,
        webhook_url=target.webhook_url,
        expected_document_id=target.expected_document_id,
        credential_id=target.credential_id,
    )
    refreshed = {item["target_code"]: item for item in service.list_targets("hzl10")}
    assert refreshed[STANDARD_TARGET_CODE]["target_name"] == "用户自定义 WPS 文档"


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ({"script_version": "old-standard"}, "WPS_SCRIPT_VERSION_MISMATCH"),
        ({"deployment_id": "stale-deployment"}, "WPS_DEPLOYMENT_ID_MISMATCH"),
        ({"target_code": SMART_TARGET_CODE}, "WPS_TARGET_CODE_MISMATCH"),
    ],
)
def test_wps_connection_test_rejects_stale_or_cross_target_script_identity(
    override: dict[str, str],
    expected_code: str,
) -> None:
    body = {
        "success": True,
        "protocol_version": 2,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_code": STANDARD_TARGET_CODE,
        "document_id": "document",
        "runtime_capability": "DEPLOYMENT_PENDING",
        **override,
    }

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(status_code=200, body=body)

    with pytest.raises(WpsSyncError) as captured:
        WpsStandardSpreadsheetAdapter(FakeClient()).connection_test(
            _wps_target(), "test-only-token"
        )

    assert captured.value.code == expected_code
    assert captured.value.details["phase"] == "PROTOCOL_HANDSHAKE"


@pytest.mark.parametrize(
    "body",
    [
        {
            "status": "finished",
            "error": "",
            "data": {
                "result": json.dumps({
                    "success": True,
                    "protocol_version": 2,
                    "target_type": "WPS_STANDARD_SPREADSHEET",
                    "document_id": "document",
                }),
            },
        },
        {
            "status": "finished",
            "error": "",
            "data": {
                "result": {
                    "success": True,
                    "protocol_version": 2,
                    "target_type": "WPS_STANDARD_SPREADSHEET",
                    "document_id": "document",
                },
            },
        },
    ],
)
def test_wps_connection_test_unwraps_official_sync_task_envelope(body: dict[str, object]) -> None:
    class FakeClient:
        def post(self, target, *, token, argv):
            assert token == "test-only-token"
            return WpsHttpResponse(status_code=200, body=body)

    result = WpsStandardSpreadsheetAdapter(FakeClient()).connection_test(_wps_target(), "test-only-token")
    assert result["phase"] == "SUCCESS"
    assert result["document_id"] == "document"


def test_wps_connection_test_classifies_only_old_random_binding_as_legacy() -> None:
    target = _wps_target()
    legacy_binding_id = f"wst_{'a' * 32}"

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(
                status_code=200,
                body={
                    "success": True,
                    "protocol_version": 2,
                    "target_type": target.target_type.value,
                    "target_code": target.target_code,
                    "document_id": target.expected_document_id,
                    "binding_id": legacy_binding_id,
                    "site_id": target.site_id,
                    "business_key": target.business_key,
                },
            )

    result = WpsStandardSpreadsheetAdapter(FakeClient()).connection_test(
        target, "test-only-token"
    )

    assert result["binding_status"] == "LEGACY_BINDING_ID_MISMATCH"
    assert result["local_binding_id"] == target.binding_id
    assert result["remote_binding_id"] == legacy_binding_id
    assert result["binding_id_match"] is False
    assert result["document_match"] is True
    assert result["document_identity_match"] is True
    assert result["site_match"] is True
    assert result["site_identity_match"] is True
    assert result["business_match"] is True
    assert result["business_identity_match"] is True
    assert result["target_match"] is True


def test_wps_connection_test_rejects_nonlegacy_binding_or_business_identity_as_mismatch() -> None:
    target = _wps_target()

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(
                status_code=200,
                body={
                    "success": True,
                    "protocol_version": 2,
                    "target_type": target.target_type.value,
                    "target_code": target.target_code,
                    "document_id": target.expected_document_id,
                    "binding_id": "not-a-legacy-random-id",
                    "site_id": "other-site",
                    "business_key": target.business_key,
                },
            )

    result = WpsStandardSpreadsheetAdapter(FakeClient()).connection_test(
        target, "test-only-token"
    )

    assert result["binding_status"] == "MISMATCH"
    assert result["site_match"] is False


def test_wps_legacy_binding_migration_accepts_already_migrated_result() -> None:
    target = _wps_target()
    legacy_binding_id = f"wst_{'c' * 32}"

    class FakeClient:
        def post(self, actual_target, *, token, argv):
            assert actual_target is target
            assert argv["operation"] == "migrate_legacy_binding"
            assert argv["document_id"] == target.expected_document_id
            assert argv["expected_old_binding_id"] == legacy_binding_id
            assert argv["new_binding_id"] == target.binding_id
            return WpsHttpResponse(
                status_code=200,
                body={
                    "success": True,
                    "protocol_version": 2,
                    "target_type": target.target_type.value,
                    "target_code": target.target_code,
                    "document_id": target.expected_document_id,
                    "binding_status": "BOUND",
                    "binding_id": target.binding_id,
                    "remote_binding_id": target.binding_id,
                    "remote_document_id": target.expected_document_id,
                    "remote_site_id": target.site_id,
                    "remote_business_key": target.business_key,
                    "remote_target_code": target.target_code,
                    "remote_target_type": target.target_type.value,
                    "migrated": False,
                    "already_migrated": True,
                },
            )

    result = WpsStandardSpreadsheetAdapter(FakeClient()).migrate_legacy_binding(
        target,
        "test-only-token",
        expected_old_binding_id=legacy_binding_id,
    )

    assert result["binding_status"] == "BOUND"
    assert result["binding_id_match"] is True
    assert result["already_migrated"] is True


def test_wps_formal_sync_preserves_remote_business_error_before_success_identity_checks() -> None:
    target = _wps_target()

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(
                status_code=200,
                body={
                    "success": False,
                    "protocol_version": 2,
                    "target_type": target.target_type.value,
                    "document_id": target.expected_document_id,
                    "error_code": "WPS_DOCUMENT_BINDING_MISMATCH",
                    "message": "远端文档绑定与当前请求不一致",
                    "binding_status": "MISMATCH",
                    "failed_sheet": "_NetConsoleSyncMeta",
                    "failed_operation": "ASSERT_BINDING",
                },
            )

    with pytest.raises(WpsSyncError) as captured:
        WpsStandardSpreadsheetAdapter(FakeClient()).sync(
            target,
            "test-only-token",
            {
                "target_batch_id": "batch-expected",
                "site_id": target.site_id,
                "business_key": target.business_key,
                "snapshot_revision": "revision-1",
                "snapshot_sha256": "sha-1",
            },
        )

    assert captured.value.code == "WPS_DOCUMENT_BINDING_MISMATCH"
    assert captured.value.code != "WPS_RESPONSE_IDENTITY_MISMATCH"
    assert captured.value.details["binding_status"] == "MISMATCH"
    assert captured.value.details["failed_operation"] == "ASSERT_BINDING"


def test_wps_success_identity_mismatch_reports_expected_and_remote_values() -> None:
    target = _wps_target()

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(
                status_code=200,
                body={
                    "success": True,
                    "protocol_version": 2,
                    "target_type": target.target_type.value,
                    "document_id": target.expected_document_id,
                    "target_batch_id": "batch-remote",
                    "site_id": target.site_id,
                    "business_key": target.business_key,
                    "snapshot_revision": "revision-remote",
                    "snapshot_sha256": "sha-remote",
                },
            )

    with pytest.raises(WpsSyncError) as captured:
        WpsStandardSpreadsheetAdapter(FakeClient()).sync(
            target,
            "test-only-token",
            {
                "target_batch_id": "batch-expected",
                "site_id": target.site_id,
                "business_key": target.business_key,
                "snapshot_revision": "revision-expected",
                "snapshot_sha256": "sha-expected",
            },
        )

    assert captured.value.code == "WPS_RESPONSE_IDENTITY_MISMATCH"
    assert captured.value.details["expected_target_batch_id"] == "batch-expected"
    assert captured.value.details["remote_target_batch_id"] == "batch-remote"
    assert captured.value.details["expected_revision"] == "revision-expected"
    assert captured.value.details["remote_revision"] == "revision-remote"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"status": "finished", "error": "", "data": {"result": None}}, "WPS_SCRIPT_RESULT_EMPTY"),
        ({"status": "finished", "error": "", "data": {"result": "not-json"}}, "WPS_SCRIPT_RESULT_INVALID"),
        ({"status": "running", "error": "", "data": {}}, "WPS_SCRIPT_STATUS_INVALID"),
        ({"status": "finished", "error": "permission denied", "error_details": {"name": "Forbidden"}}, "WPS_SCRIPT_EXECUTION_FAILED"),
    ],
)
def test_wps_connection_test_reports_envelope_failures(body: dict[str, object], code: str) -> None:
    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(status_code=200, body=body)

    with pytest.raises(WpsSyncError) as captured:
        WpsStandardSpreadsheetAdapter(FakeClient()).connection_test(_wps_target(), "test-only-token")
    assert captured.value.code == code
    assert captured.value.details["phase"] == "SCRIPT_EXECUTION"


@pytest.mark.parametrize(
    ("status", "body", "expected_code"),
    [
        (403, b'{"code":"DOCUMENT_PERMISSION_DENIED","message":"no access"}', "WPS_DOCUMENT_PERMISSION_DENIED"),
        (403, b"token expired", "WPS_TOKEN_INVALID"),
        (403, b"script is nil", "WPS_SCRIPT_NOT_AVAILABLE"),
        (403, b"<html><title>Forbidden</title></html>", "WPS_REMOTE_FORBIDDEN"),
        (401, b'{"error_code":"TOKEN_INVALID","msg":"invalid token"}', "WPS_TOKEN_INVALID"),
        (404, b"not found", "WPS_WEBHOOK_NOT_FOUND"),
        (429, b"rate limited", "WPS_REMOTE_RATE_LIMITED"),
    ],
)
def test_wps_http_errors_keep_safe_remote_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    body: bytes,
    expected_code: str,
) -> None:
    token = "test-only-token"

    def raise_http_error(request, *, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "remote failure",
            {"Content-Type": "application/json"},
            io.BytesIO(body),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    with pytest.raises(WpsSyncError) as captured:
        WpsAirScriptClient().post(_wps_target(), token=token, argv={"operation": "connection_test"})

    error = captured.value
    assert error.code == expected_code
    assert error.details["phase"] == "HTTP_AUTH"
    assert error.details["http_status"] == status
    assert token not in str(error)
    assert token not in str(error.details)
    if status == 403:
        assert "HTTP 403" in str(error)
        assert "建议" in str(error)


def test_wps_http_response_and_request_headers_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _wps_target()
    observed: dict[str, str] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            observed["read_size"] = str(size)
            return json.dumps({"success": True}).encode("utf-8")

    def open_request(request, *, timeout):
        observed.update({key.lower(): value for key, value in request.headers.items()})
        observed["timeout"] = str(timeout)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    response = WpsAirScriptClient().post(target, token="test-only-token", argv={})
    assert response.status_code == 200
    assert observed["content-type"] == "application/json"
    assert observed["accept"] == "application/json"
    assert observed["user-agent"].startswith("NetConsole/")
    assert int(observed["read_size"]) == 20 * 1024 * 1024 + 1


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
    assert [sheet.sheet_order for sheet in dto.sheets] == [0, 1]


def test_workbook_dto_preserves_sheet_order_and_compresses_format_runs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "styled.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "轨旁AP业务"
    sheet.append(["站点", "上线率", "备注"])
    sheet.append(["A", 0.5, "第一行"])
    sheet.append(["B", 0.75, "第二行"])
    header_fill = PatternFill(fill_type="solid", fgColor="4472C4")
    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for cell in sheet[1]:
        cell.font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    for row in sheet.iter_rows(min_row=2, max_row=3, min_col=1, max_col=3):
        for cell in row:
            cell.font = Font(name="Microsoft YaHei", size=10)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border
    for row in (2, 3):
        sheet.cell(row=row, column=2).number_format = "0.00%"
    sheet.merge_cells("A4:C4")
    sheet["A4"] = "合并说明"
    sheet.column_dimensions["A"].width = 18
    sheet.row_dimensions[1].height = 24
    sheet.freeze_panes = "A2"
    sheet.sheet_properties.tabColor = "70AD47"
    hidden = workbook.create_sheet("隐藏业务页")
    hidden.sheet_state = "hidden"
    workbook.save(path)
    workbook.close()

    dto = workbook_dto_from_xlsx(path, include_format_mirror=True)
    first, second = dto.sheets
    assert first.sheet_order == 0
    assert second.sheet_order == 1
    assert first.sheet_visible is True
    assert second.sheet_visible is False
    assert first.tab_color == "#70AD47"
    assert first.merges == ["A4:C4"]
    assert first.column_widths["A"] == 18
    assert first.row_heights["1"] == 24
    assert first.freeze_panes == "A2"
    runs = {run.range: run for run in first.format_runs}
    assert runs["A1:C1"].font == {
        "name": "Microsoft YaHei",
        "size": 11.0,
        "bold": True,
        "italic": False,
        "underline": "",
        "strike": False,
        "color": "#FFFFFF",
    }
    assert runs["A1:C1"].fill["fg_color"] == "#4472C4"
    assert runs["A1:C1"].alignment["wrap_text"] is True
    assert runs["B2:B3"].number_format == "0.00%"
    assert runs["B2:B3"].border["left"] == {
        "style": "thin",
        "color": "#D1D5DB",
    }
    assert len(first.format_runs) < first.row_count * first.column_count
    serialized = first.to_dict()
    assert "format_runs" in serialized
    assert "fonts" not in serialized
    assert "borders" not in serialized


def test_workbook_dto_omits_format_mirror_by_default() -> None:
    assert WPS_STANDARD_FORMAT_MIRROR_EXPERIMENTAL is False



def test_standard_airscript_keeps_format_mirror_disabled_behind_explicit_gate() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "tools"
        / "wps_airscript"
        / "trackside_ap_standard_spreadsheet_sync.js"
    )
    script = script_path.read_text(encoding="utf-8")

    assert 'const SCRIPT_VERSION = "2.3.0-standard";' in script
    assert 'const DEPLOYMENT_ID = "trackside-ap-standard-2.3.0";' in script
    assert "const FORMAT_MIRROR_EXPERIMENTAL = false;" in script
    assert "function writeStableSheet(sheetDto)" in script
    assert "if (used && used.ClearContents) used.ClearContents();" in script
    assert "FORMAT_MIRROR_EXPERIMENTAL && args.format_mirror_experimental === true" in script
    assert "sheetOrderVerification = reorderBusinessSheets(sheets);" in script
    assert "const sheet = sheets.Add();" in script
    assert "sheets.Add(null" not in script
    assert "used.UnMerge()" in script
    assert "used.Clear()" in script
    assert 'attemptFormat(warnings, sheet.Name, "append_clear_values_and_formats"' in script
    assert "sheetDto.format_runs" in script
    assert 'attemptFormat(warnings, sheet.Name, "format_range"' in script
    assert "range.Interior.Color" in script
    assert "range.Font.Bold" in script
    assert "range.NumberFormat" in script
    assert "range.HorizontalAlignment" in script
    assert "range.VerticalAlignment" in script
    assert "range.WrapText" in script
    assert "range.Borders.Item" in script
    assert "sheet.Range(merge).Merge()" in script
    assert "sheet.Move(first)" in script
    assert "sheet.Move(null, last)" in script
    assert "sheet.Move({" not in script
    assert 'error_code: "WPS_SHEET_ORDER_VERIFY_FAILED"' in script
    assert 'if (args.operation === "sheet_order_probe") return sheetOrderProbe(args);' in script
    assert '.startsWith("_NetConsole")' in script
    assert 'status: publicWarnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS"' in script
    assert 'if (args.operation === "migrate_legacy_binding") return migrateLegacyBinding(args);' in script
    assert "function updateBindingIdOnly(newBindingId)" in script
    assert 'sheet.Range(`B${index + 1}`).Value2 = String(newBindingId || "");' in script
    assert "LEGACY_BINDING_ID_MISMATCH" in script
    migration_block = script.split("function migrateLegacyBinding(args)", 1)[1].split(
        "function addFormatWarning", 1
    )[0]
    assert "updateBindingIdOnly(newBindingId)" in migration_block
    assert "expected_old_binding_id" in migration_block
    assert "new_binding_id" in migration_block
    assert "ensureSheet(" not in migration_block
    assert "writeStableSheet(" not in migration_block
    assert "args.workbook" not in migration_block
    assert script.rstrip().endswith("return main();")


def test_standard_probe_and_sync_scripts_share_deployment_identity() -> None:
    root = Path(__file__).parents[1] / "tools" / "wps_airscript"
    sync_script = (root / "trackside_ap_standard_spreadsheet_sync.js").read_text(
        encoding="utf-8"
    )
    probe_script = (
        root / "trackside_ap_standard_spreadsheet_connection_probe.js"
    ).read_text(encoding="utf-8")
    for expected in (
        WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
    ):
        assert expected in sync_script
        assert expected in probe_script
    assert sync_script.rstrip().endswith("return main();")
    assert probe_script.rstrip().endswith("return main();")
    assert "LEGACY_BINDING_ID_MISMATCH" in sync_script
    assert "LEGACY_BINDING_ID_MISMATCH" in probe_script
    assert "WPS_BINDING_MIGRATION_REQUIRES_SYNC_SCRIPT" in probe_script
    assert ".Worksheets.Add" not in probe_script
    assert "ensureSheet(" not in probe_script


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
    repository = service._repository("hzl10")
    for target in repository.list_targets(TRACKSIDE_AP_WPS_BUSINESS_KEY):
        repository.set_runtime_capability(target.target_id, "VERIFIED")
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


def test_wps_sync_aggregates_noncritical_format_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(
                status_code=200,
                body={
                    "success": True,
                    "protocol_version": 2,
                    "target_type": target.target_type.value,
                    "document_id": target.expected_document_id,
                    "target_batch_id": argv.get("target_batch_id"),
                    "site_id": argv.get("site_id"),
                    "business_key": argv.get("business_key"),
                    "snapshot_revision": argv.get("snapshot_revision"),
                    "snapshot_sha256": argv.get("snapshot_sha256"),
                    "format_warning_count": 1,
                    "format_warnings": [
                        {
                            "sheet_name": "轨旁AP业务",
                            "feature": "freeze_panes",
                            "reason": "runtime unsupported",
                        }
                    ],
                },
            )

    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=FakeClient())
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/test/sync_task",
    )
    monkeypatch.setenv("NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN", "test-token")
    repository = service._repository("hzl10")
    target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    repository.set_runtime_capability(target.target_id, "VERIFIED")
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

    result = service.sync("hzl10", target_codes=[STANDARD_TARGET_CODE])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["success_count"] == 1
    assert result["failed_count"] == 0
    assert result["warning_count"] == 1
    assert result["targets"][0]["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["targets"][0]["format_warnings"][0]["feature"] == "freeze_panes"


def test_wps_sync_is_registered_as_a_job_center_handler() -> None:
    from netconsole.services.job_center.job_registry import registered_task_types

    assert WPS_SYNC_TASK_TYPE in registered_task_types()


def test_wps_runtime_probe_identity_is_persisted_and_invalidated_by_webhook_change(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    service = TracksideApWpsSyncService(paths)
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-old/sync_task",
    )
    repository = service._repository("hzl10")
    target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    repository.update_target_remote_state(
        target.target_id,
        binding_status="BOUND",
        runtime_capability="VERIFIED",
        result={
            "document_id": "standard",
            "script_id": "script-old",
            "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
            "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
            "binding_id": target.binding_id,
            "site_id": "hzl10",
            "business_key": TRACKSIDE_AP_WPS_BUSINESS_KEY,
        },
    )

    verified = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    assert verified.runtime_probe_document_id == "standard"
    assert verified.runtime_probe_script_id == "script-old"
    assert verified.runtime_capability == "VERIFIED"
    assert verified.binding_status == "BOUND"

    updated = service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-new/sync_task",
    )
    assert updated["runtime_capability"] == "DEPLOYMENT_PENDING"
    assert updated["binding_status"] == "BOUND"
    assert updated["runtime_probe_script_id"] == ""
    assert updated["expected_script_id"] == "script-new"


def _seed_verified_wps_target(
    service: TracksideApWpsSyncService,
    *,
    script_id: str = "script-one",
) -> tuple[WpsSyncRepository, WpsSyncTarget]:
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url=(
            "https://www.kdocs.cn/api/v3/ide/file/standard/"
            f"script/{script_id}/sync_task"
        ),
        token="seed-token",
        enabled=True,
    )
    repository = service._repository("hzl10")
    target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    identity = {
        "document_id": "standard",
        "script_id": script_id,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "binding_id": target.binding_id,
        "site_id": "hzl10",
        "business_key": TRACKSIDE_AP_WPS_BUSINESS_KEY,
    }
    repository.update_target_remote_identity(target.target_id, result=identity)
    repository.update_target_remote_state(
        target.target_id,
        binding_status="BOUND",
        result=identity,
        runtime_capability="VERIFIED",
    )
    for operation in (
        "connection_test",
        "runtime_write_probe",
        "sync_test_sheet",
        "sheet_order_probe",
    ):
        repository.update_target_diagnostic(
            target.target_id,
            operation=operation,
            diagnostic={
                "executed_at": "2026-08-07T10:00:00+08:00",
                "status": "SUCCESS",
                "script_version": identity["script_version"],
                "deployment_id": identity["deployment_id"],
                "script_id": identity["script_id"],
                "document_id": identity["document_id"],
                "operation": operation,
                "message": "ok",
            },
        )
    return repository, repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)


@pytest.mark.parametrize(
    "update",
    [
        {"document_open_url": "https://www.kdocs.cn/l/standard"},
        {"webhook_url": "https://www.kdocs.cn/api/v3/ide/file/standard/script/script-one/sync_task"},
        {"timeout_seconds": 60},
        {"enabled": False},
        {"token": "rotated-token"},
    ],
)
def test_wps_target_configuration_noop_and_non_identity_changes_keep_deployment(
    tmp_path: Path,
    update: dict[str, object],
) -> None:
    service = TracksideApWpsSyncService(PathResolver(tmp_path))
    repository, target = _seed_verified_wps_target(service)

    service.configure_target("hzl10", STANDARD_TARGET_CODE, **update)

    refreshed = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    assert refreshed.runtime_capability == "VERIFIED"
    assert refreshed.binding_status == "BOUND"
    assert refreshed.runtime_probe_script_id == "script-one"
    assert refreshed.remote_script_id == "script-one"
    assert refreshed.remote_deployment_id == WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE]
    assert refreshed.sheet_order_probe_diagnostic["status"] == "SUCCESS"
    if "token" in update:
        assert repository.resolve_token(target) == "rotated-token"


def test_wps_target_configuration_document_identity_change_clears_all_runtime_state(
    tmp_path: Path,
) -> None:
    service = TracksideApWpsSyncService(PathResolver(tmp_path))
    repository, target = _seed_verified_wps_target(service)

    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/other-document/script/script-one/sync_task",
    )

    refreshed = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    assert refreshed.expected_document_id == "other-document"
    assert refreshed.runtime_capability == "DEPLOYMENT_PENDING"
    assert refreshed.binding_status == "BOUND"
    assert refreshed.remote_script_id == ""
    assert refreshed.connection_diagnostic == {}
    assert refreshed.runtime_probe_diagnostic == {}
    assert refreshed.sync_test_diagnostic == {}
    assert refreshed.sheet_order_probe_diagnostic == {}
    assert refreshed.remote_identity_verified_at == ""
    assert target.remote_script_id == "script-one"


def test_wps_expected_deployment_change_downgrades_verification_but_keeps_binding(
    tmp_path: Path,
) -> None:
    service = TracksideApWpsSyncService(PathResolver(tmp_path))
    repository, target = _seed_verified_wps_target(service)
    repository.update_target_remote_state(
        target.target_id,
        binding_status="BOUND",
        runtime_capability="VERIFIED",
        result={
            "document_id": "standard",
            "script_id": "script-one",
            "script_version": "9.9.9-standard",
            "deployment_id": "stale-deployment",
        },
    )

    listed = {
        item["target_code"]: item
        for item in service.list_targets("hzl10")
    }[STANDARD_TARGET_CODE]
    assert listed["runtime_capability"] == "DEPLOYMENT_PENDING"
    assert listed["binding_status"] == "BOUND"
    assert listed["runtime_probe_deployment_id"] == ""
    assert listed["connection_diagnostic"] == {}


def test_wps_operation_diagnostics_keep_old_connection_failure_separate_from_new_probe(
    tmp_path: Path,
) -> None:
    old_result = {
        "success": True,
        "protocol_version": 2,
        "script_version": "2.1.0-standard",
        "deployment_id": "trackside-ap-standard-2.1.0",
        "script_id": "script-one",
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_code": STANDARD_TARGET_CODE,
        "document_id": "standard",
        "runtime_capability": "DEPLOYMENT_PENDING",
    }
    current_result = {
        **old_result,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "runtime_capability": "VERIFIED",
        "binding_status": "BOUND",
    }

    class FakeClient:
        def post(self, target, *, token, argv):
            if argv["operation"] == "connection_test":
                return WpsHttpResponse(status_code=200, body=old_result)
            return WpsHttpResponse(status_code=200, body=current_result)

    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=FakeClient())
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-one/sync_task",
        token="test-token",
    )
    with pytest.raises(WpsSyncError) as failure:
        service.connection_test("hzl10", STANDARD_TARGET_CODE)
    assert failure.value.code == "WPS_SCRIPT_VERSION_MISMATCH"
    service.runtime_write_probe("hzl10", STANDARD_TARGET_CODE)
    repository = service._repository("hzl10")
    target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    assert target.connection_diagnostic["status"] == "FAILED"
    assert target.connection_diagnostic["script_version"] == "2.1.0-standard"
    assert target.runtime_probe_diagnostic["status"] == "SUCCESS"
    assert target.runtime_probe_diagnostic["script_version"] == WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE]
    assert target.remote_script_version == ""


def test_wps_runtime_probe_visibility_warning_keeps_core_verified_and_diagnostic(
    tmp_path: Path,
) -> None:
    capabilities = {
        "worksheet_enum": True,
        "worksheet_item": True,
        "worksheet_create": True,
        "scalar_value2": True,
        "matrix_value2": True,
        "used_range": True,
        "clear_contents": True,
        "entire_row_insert": True,
        "sheet_visibility": False,
    }
    body = {
        "success": True,
        "status": "SUCCESS_WITH_WARNINGS",
        "protocol_version": 2,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "script_id": "script-one",
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_code": STANDARD_TARGET_CODE,
        "document_id": "standard",
        "binding_status": "BOUND",
        "runtime_capability": "VERIFIED",
        "core_verified": True,
        "full_replace_ready": True,
        "prepend_snapshot_ready": True,
        "capabilities": capabilities,
        "core_capabilities": {
            key: value for key, value in capabilities.items() if key != "sheet_visibility"
        },
        "optional_capabilities": {"sheet_visibility": False},
        "warnings": [
            {
                "capability": "sheet_visibility",
                "message": "WPS 当前运行时无法确认系统 Sheet 隐藏状态",
            }
        ],
    }

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(status_code=200, body=body)

    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=FakeClient())
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-one/sync_task",
        token="test-token",
    )

    result = service.runtime_write_probe("hzl10", STANDARD_TARGET_CODE)
    target = service._repository("hzl10").get_target(
        TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE
    )

    assert result["runtime_capability"] == "VERIFIED"
    assert target.runtime_capability == "VERIFIED"
    assert target.runtime_probe_diagnostic["status"] == "SUCCESS_WITH_WARNINGS"
    assert target.runtime_probe_diagnostic["core_verified"] is True
    assert target.runtime_probe_diagnostic["core_capabilities"]["matrix_value2"] is True
    assert target.runtime_probe_diagnostic["optional_capabilities"]["sheet_visibility"] is False
    assert target.runtime_probe_diagnostic["warnings"][0]["capability"] == "sheet_visibility"


def test_wps_sheet_order_probe_is_independent_and_persists_verification(
    tmp_path: Path,
) -> None:
    operations: list[str] = []
    body = {
        "success": True,
        "status": "SUCCESS_WITH_WARNINGS",
        "protocol_version": 2,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "script_id": "script-one",
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_code": STANDARD_TARGET_CODE,
        "document_id": "standard",
        "binding_status": "BOUND",
        "runtime_capability": "VERIFIED",
        "sheet_order_verified": True,
        "sheet_move_before_verified": True,
        "sheet_move_after_verified": True,
        "expected_sheet_order": ["_NetConsoleRuntimeProbe", "_NetConsoleSyncTest"],
        "actual_sheet_order": ["_NetConsoleRuntimeProbe", "_NetConsoleSyncTest"],
        "warnings": [
            {
                "sheet_name": "_NetConsoleSyncMeta",
                "feature": "system_sheet_visibility",
                "reason": "visibility unsupported",
            }
        ],
        "message": "Sheet.Move 排序探针通过",
    }

    class FakeClient:
        def post(self, target, *, token, argv):
            operations.append(str(argv["operation"]))
            return WpsHttpResponse(status_code=200, body=body)

    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=FakeClient())
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-one/sync_task",
        token="test-token",
    )

    result = service.sheet_order_probe("hzl10", STANDARD_TARGET_CODE)
    target = service._repository("hzl10").get_target(
        TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE
    )

    assert operations == ["sheet_order_probe"]
    assert result["sheet_order_verified"] is True
    assert target.sheet_order_probe_diagnostic["status"] == "SUCCESS_WITH_WARNINGS"
    assert target.sheet_order_probe_diagnostic["sheet_move_before_verified"] is True
    assert target.sheet_order_probe_diagnostic["actual_sheet_order"] == body["actual_sheet_order"]
    assert target.runtime_capability == "DEPLOYMENT_PENDING"
    assert target.runtime_probe_diagnostic == {}
    assert target.sync_test_diagnostic == {}
    assert target.binding_status == "UNKNOWN"


def test_wps_runtime_probe_core_failure_persists_each_capability(
    tmp_path: Path,
) -> None:
    body = {
        "success": False,
        "status": "FAILED",
        "protocol_version": 2,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "script_id": "script-one",
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_code": STANDARD_TARGET_CODE,
        "document_id": "standard",
        "binding_status": "BOUND",
        "runtime_capability": "DEPLOYMENT_PENDING",
        "core_verified": False,
        "full_replace_ready": True,
        "prepend_snapshot_ready": False,
        "capabilities": {"matrix_value2": True, "entire_row_insert": False},
        "core_capabilities": {"matrix_value2": True, "entire_row_insert": False},
        "optional_capabilities": {"sheet_visibility": True},
        "capability_failures": [
            {"capability": "entire_row_insert", "message": "能力验证结果为未通过"}
        ],
        "error_code": "WPS_RUNTIME_PROBE_VERIFY_FAILED",
        "message": "运行时核心能力探针未通过：entire_row_insert",
    }

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(status_code=200, body=body)

    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=FakeClient())
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-one/sync_task",
        token="test-token",
    )

    with pytest.raises(WpsSyncError) as failure:
        service.runtime_write_probe("hzl10", STANDARD_TARGET_CODE)

    assert failure.value.code == "WPS_RUNTIME_PROBE_VERIFY_FAILED"
    target = service._repository("hzl10").get_target(
        TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE
    )
    assert target.runtime_probe_diagnostic["status"] == "FAILED"
    assert target.runtime_probe_diagnostic["full_replace_ready"] is True
    assert target.runtime_probe_diagnostic["prepend_snapshot_ready"] is False
    assert target.runtime_probe_diagnostic["core_capabilities"]["entire_row_insert"] is False


def test_wps_successful_connection_test_persists_identity_and_diagnostic_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    body = {
        "success": True,
        "protocol_version": 2,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "script_id": "script-one",
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_code": STANDARD_TARGET_CODE,
        "document_id": "standard",
        "binding_status": "BOUND",
        "binding_id": "binding-one",
        "site_id": "hzl10",
        "site_name": "杭州地铁10号线",
        "business_key": TRACKSIDE_AP_WPS_BUSINESS_KEY,
        "runtime_capability": "DEPLOYMENT_PENDING",
    }

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(status_code=200, body=body)

    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=FakeClient())
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-one/sync_task",
        token="test-token",
    )
    calls: list[str] = []
    original = WpsSyncRepository._update_target

    def observe(self, target_id, assignment, values):
        calls.append(str(assignment))
        return original(self, target_id, assignment, values)

    monkeypatch.setattr(WpsSyncRepository, "_update_target", observe)
    service.connection_test("hzl10", STANDARD_TARGET_CODE)

    connection_updates = [item for item in calls if "connection_diagnostic" in item]
    assert len(connection_updates) == 1
    assert "remote_script_version" in connection_updates[0]
    assert "remote_deployment_id" in connection_updates[0]
    assert "remote_script_id" in connection_updates[0]
    assert "remote_identity_verified_at" in connection_updates[0]
    target = service._repository("hzl10").get_target(
        TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE
    )
    assert target.last_test_status == "SUCCESS"
    assert target.remote_script_id == "script-one"
    assert target.connection_diagnostic["status"] == "SUCCESS"


def test_wps_revalidate_deployment_runs_all_probes_and_restores_verified(
    tmp_path: Path,
) -> None:
    operations: list[str] = []
    identity = {
        "protocol_version": 2,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "script_id": "script-one",
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_code": STANDARD_TARGET_CODE,
        "document_id": "standard",
        "binding_status": "BOUND",
        "binding_id": "binding-one",
        "site_id": "hzl10",
        "site_name": "杭州地铁10号线",
        "business_key": TRACKSIDE_AP_WPS_BUSINESS_KEY,
        "runtime_capability": "VERIFIED",
    }

    class FakeClient:
        def post(self, target, *, token, argv):
            operations.append(str(argv["operation"]))
            return WpsHttpResponse(
                status_code=200,
                body={
                    **identity,
                    "success": True,
                    "message": f"{argv['operation']} ok",
                },
            )

    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=FakeClient())
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-one/sync_task",
        token="test-token",
    )
    result = service.revalidate_deployment("hzl10", STANDARD_TARGET_CODE)
    assert operations == ["connection_test", "runtime_write_probe", "sync_test_sheet"]
    assert result["runtime_capability"] == "VERIFIED"
    target = service._repository("hzl10").get_target(
        TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE
    )
    assert target.runtime_capability == "VERIFIED"
    assert target.binding_status == "BOUND"
    assert target.remote_script_id == "script-one"
    assert target.connection_diagnostic["status"] == "SUCCESS"
    assert target.runtime_probe_diagnostic["status"] == "SUCCESS"
    assert target.sync_test_diagnostic["status"] == "SUCCESS"


def test_wps_formal_sync_gate_treats_operation_diagnostics_as_evidence_only(
    tmp_path: Path,
) -> None:
    service = TracksideApWpsSyncService(PathResolver(tmp_path))
    repository, target = _seed_verified_wps_target(service)
    _assert_standard_sync_readiness(target)

    stale = dict(target.sync_test_diagnostic)
    stale["deployment_id"] = "trackside-ap-standard-2.2"
    repository.update_target_diagnostic(
        target.target_id,
        operation="sync_test_sheet",
        diagnostic=stale,
    )
    _assert_standard_sync_readiness(
        repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    )


def test_wps_sync_rejects_unknown_and_unconfirmed_unbound_binding(tmp_path: Path) -> None:
    service = TracksideApWpsSyncService(PathResolver(tmp_path))
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/script-one/sync_task",
        enabled=True,
    )
    repository = service._repository("hzl10")
    target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    repository.set_runtime_capability(target.target_id, "VERIFIED")

    with pytest.raises(WpsSyncError) as unknown:
        service.sync("hzl10", target_codes=[STANDARD_TARGET_CODE])
    assert unknown.value.code == "WPS_BINDING_STATUS_UNKNOWN"

    repository.update_target_remote_state(
        target.target_id,
        binding_status="UNBOUND",
        result={
            "document_id": "standard",
            "script_id": "script-one",
            "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
            "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        },
    )
    with pytest.raises(WpsSyncError) as unbound:
        service.sync("hzl10", target_codes=[STANDARD_TARGET_CODE])
    assert unbound.value.code == "WPS_DOCUMENT_UNBOUND"

    repository.update_target_remote_state(
        target.target_id,
        binding_status="LEGACY_BINDING_ID_MISMATCH",
        result={"remote_binding_id": f"wst_{'a' * 32}"},
        persist_runtime_identity=False,
    )
    with pytest.raises(WpsSyncError) as legacy:
        service.sync("hzl10", target_codes=[STANDARD_TARGET_CODE])
    assert legacy.value.code == "WPS_LEGACY_BINDING_ID_MISMATCH"


def test_wps_legacy_binding_migration_rechecks_identity_and_runs_verification_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operations: list[dict[str, object]] = []
    remote_binding_id = [f"wst_{'b' * 32}"]

    class FakeClient:
        def post(self, target, *, token, argv):
            operations.append(dict(argv))
            assert token == "test-token"
            operation = str(argv["operation"])
            base = {
                "success": True,
                "protocol_version": 2,
                "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
                "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
                "script_id": "test",
                "runtime_capability": "VERIFIED",
                "target_type": target.target_type.value,
                "target_code": target.target_code,
                "document_id": target.expected_document_id,
                "binding_status": (
                    "BOUND"
                    if remote_binding_id[0] == target.binding_id
                    else "LEGACY_BINDING_ID_MISMATCH"
                ),
                "local_binding_id": target.binding_id,
                "remote_binding_id": remote_binding_id[0],
                "remote_document_id": target.expected_document_id,
                "remote_site_id": target.site_id,
                "remote_business_key": target.business_key,
                "remote_target_code": target.target_code,
                "remote_target_type": target.target_type.value,
            }
            if operation == "migrate_legacy_binding":
                assert argv["document_id"] == target.expected_document_id
                assert argv["expected_old_binding_id"] == remote_binding_id[0]
                assert argv["new_binding_id"] == target.binding_id
                previous_binding_id = remote_binding_id[0]
                remote_binding_id[0] = target.binding_id
                base.update(
                    {
                        "binding_status": "BOUND",
                        "binding_id": target.binding_id,
                        "remote_binding_id": target.binding_id,
                        "binding_id_match": True,
                        "migrated": True,
                        "already_migrated": False,
                        "previous_binding_id": previous_binding_id,
                        "message": "旧版绑定标识已迁移",
                    }
                )
            return WpsHttpResponse(
                status_code=200,
                body=base,
            )

    service = TracksideApWpsSyncService(PathResolver(tmp_path), client=FakeClient())
    service.configure_target(
        "hzl10",
        STANDARD_TARGET_CODE,
        document_open_url="https://www.kdocs.cn/l/standard",
        webhook_url="https://www.kdocs.cn/api/v3/ide/file/standard/script/test/sync_task",
    )
    monkeypatch.setenv("NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN", "test-token")
    repository = service._repository("hzl10")
    target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    legacy_binding_id = remote_binding_id[0]
    repository.update_target_remote_state(
        target.target_id,
        binding_status="LEGACY_BINDING_ID_MISMATCH",
        result={
            "remote_binding_id": legacy_binding_id,
            "remote_site_id": target.site_id,
            "remote_business_key": target.business_key,
        },
        persist_runtime_identity=False,
    )

    result = service.migrate_legacy_binding("hzl10", STANDARD_TARGET_CODE)

    assert [item["operation"] for item in operations] == [
        "connection_test",
        "migrate_legacy_binding",
        "connection_test",
        "runtime_write_probe",
        "sync_test_sheet",
    ]
    assert result["migrated"] is True
    assert result["already_migrated"] is False
    assert result["previous_binding_id"] == legacy_binding_id
    assert result["verification"]["runtime_capability"] == "VERIFIED"
    refreshed = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, STANDARD_TARGET_CODE)
    assert refreshed.binding_status == "BOUND"
    assert refreshed.remote_binding_id == target.binding_id
    assert refreshed.connection_diagnostic["binding_id_match"] is True


def test_wps_connection_test_rejects_webhook_script_id_mismatch() -> None:
    body = {
        "success": True,
        "protocol_version": 2,
        "script_version": WPS_SCRIPT_VERSIONS[STANDARD_TARGET_CODE],
        "deployment_id": WPS_DEPLOYMENT_IDS[STANDARD_TARGET_CODE],
        "script_id": "other-script",
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_code": STANDARD_TARGET_CODE,
        "document_id": "document",
        "runtime_capability": "DEPLOYMENT_PENDING",
    }

    class FakeClient:
        def post(self, target, *, token, argv):
            return WpsHttpResponse(status_code=200, body=body)

    with pytest.raises(WpsSyncError) as captured:
        WpsStandardSpreadsheetAdapter(FakeClient()).connection_test(
            _wps_target(), "test-only-token"
        )
    assert captured.value.code == "WPS_SCRIPT_ID_MISMATCH"
