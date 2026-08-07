from __future__ import annotations

import io
import json
from pathlib import Path
import urllib.error

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.wps_sync import TRACKSIDE_AP_WPS_BUSINESS_KEY, WpsSyncTarget, WpsTargetType
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
    WPS_SYNC_TASK_TYPE,
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

    dto = workbook_dto_from_xlsx(path)
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


def test_standard_airscript_restores_formatting_and_reorders_sheets() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "tools"
        / "wps_airscript"
        / "trackside_ap_standard_spreadsheet_sync.js"
    )
    script = script_path.read_text(encoding="utf-8")

    assert 'const SCRIPT_VERSION = "2.3.0-standard";' in script
    assert 'const DEPLOYMENT_ID = "trackside-ap-standard-2.3.0";' in script
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
    assert "sheet.Move({ Before: first.Id, After: null })" in script
    assert 'name.startsWith("_NetConsole")' in script
    assert 'status: publicWarnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS"' in script
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
            "binding_id": target.target_id,
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
    assert updated["binding_status"] == "UNKNOWN"
    assert updated["runtime_probe_script_id"] == ""
    assert updated["expected_script_id"] == "script-new"


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
