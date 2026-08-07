from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from openpyxl import load_workbook

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.core.version import APP_VERSION
from netconsole.models.wps_sync import (
    TRACKSIDE_AP_WPS_BUSINESS_KEY,
    WPS_SYNC_PROTOCOL_VERSION,
    WorkbookDTO,
    WorkbookSheetDTO,
    WpsSyncMode,
    WpsSyncTarget,
    WpsTargetType,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.wps_sync_repository import WpsSyncRepository
from netconsole.services.rail_transit.trackside_ap_business_snapshot import (
    canonical_json_bytes,
    content_sha256,
)
from netconsole.services.trackside_ap_export_service import (
    _render_trackside_ap_business_export,
    build_trackside_ap_business_export_snapshot,
)


STANDARD_TARGET_CODE = "wps_standard_spreadsheet"
SMART_TARGET_CODE = "wps_smart_sheet"
WPS_SYNC_TASK_TYPE = "trackside_ap_wps_sync"
WPS_SYNC_OWNER = "web_rail_transit"
_VALID_TARGET_CODES = {STANDARD_TARGET_CODE, SMART_TARGET_CODE}
_TARGET_TOKEN_ENV = {
    STANDARD_TARGET_CODE: "NETCONSOLE_WPS_STANDARD_AIRSCRIPT_TOKEN",
    SMART_TARGET_CODE: "NETCONSOLE_WPS_SMART_AIRSCRIPT_TOKEN",
}
_META_SHEET_NAMES = {"_netconsole_meta", "_NetConsoleSyncMeta", "_NetConsoleSyncRuns"}
_SAFE_ERROR_RE = re.compile(r"(?i)(airscript-token|authorization|token)\s*[:=]\s*\S+")
_MAX_PAYLOAD_BYTES = 20 * 1024 * 1024
_MAX_ERROR_BODY_BYTES = 64 * 1024
_MAX_ERROR_TEXT = 500

DEFAULT_TARGETS = (
    {
        "target_code": STANDARD_TARGET_CODE,
        "target_type": WpsTargetType.STANDARD_SPREADSHEET,
        "target_name": "杭州地铁10号线轨旁AP业务-普通在线表格",
        "document_open_url": "",
        "webhook_url": "",
        "expected_document_id": "",
    },
    {
        "target_code": SMART_TARGET_CODE,
        "target_type": WpsTargetType.SMART_SHEET,
        "target_name": "杭州地铁10号线轨旁AP业务-智能表格",
        "document_open_url": "",
        "webhook_url": "",
        "expected_document_id": "",
    },
)


class WpsSyncError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(_sanitize_error(message))
        self.code = code
        self.details = _sanitize_details(details or {})


@dataclass(frozen=True)
class WpsHttpResponse:
    status_code: int
    body: object


class WpsAirScriptClient:
    def post(
        self,
        target: WpsSyncTarget,
        *,
        token: str,
        argv: Mapping[str, object],
    ) -> WpsHttpResponse:
        if not token:
            raise WpsSyncError(
                "WPS_TOKEN_MISSING",
                "WPS 脚本凭据未配置",
                details=_target_error_details(target, phase="LOCAL_CONFIGURATION"),
            )
        body = json.dumps(
            {"Context": {"argv": dict(argv)}},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > _MAX_PAYLOAD_BYTES:
            raise WpsSyncError(
                "WPS_PAYLOAD_TOO_LARGE",
                f"WPS 同步请求超过 {_MAX_PAYLOAD_BYTES} 字节限制",
            )
        request = urllib.request.Request(
            target.webhook_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "AirScript-Token": token,
                "User-Agent": f"NetConsole/{APP_VERSION}",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=target.timeout_seconds,
            ) as response:
                raw = response.read(_MAX_PAYLOAD_BYTES + 1)
                status_code = int(response.status)
        except urllib.error.HTTPError as exc:
            raise _http_error_from_response(exc, target, token) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WpsSyncError(
                "WPS_CONNECTION_FAILED",
                f"WPS 连接失败：{_sanitize_error(str(exc))}",
            ) from None
        if len(raw) > _MAX_PAYLOAD_BYTES:
            raise WpsSyncError("WPS_RESPONSE_TOO_LARGE", "WPS 返回内容超过安全限制")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise WpsSyncError(
                "WPS_RESPONSE_INVALID",
                "WPS 返回了非 JSON 内容",
                details=_target_error_details(target, phase="SCRIPT_EXECUTION"),
            ) from None
        if not isinstance(decoded, dict):
            raise WpsSyncError(
                "WPS_RESPONSE_INVALID",
                "WPS 返回结构无效",
                details=_target_error_details(target, phase="SCRIPT_EXECUTION"),
            )
        return WpsHttpResponse(status_code=status_code, body=decoded)


class BaseWpsAdapter:
    def __init__(self, client: WpsAirScriptClient) -> None:
        self.client = client

    def connection_test(self, target: WpsSyncTarget, token: str) -> dict[str, Any]:
        response = self.client.post(
            target,
            token=token,
            argv={
                "protocol_version": WPS_SYNC_PROTOCOL_VERSION,
                "operation": "connection_test",
                "target_code": target.target_code,
                "target_type": target.target_type.value,
            },
        )
        result = _unwrap_wps_sync_task_response(response, target, token=token)
        self._validate_common(target, result)
        if not bool(result.get("success")):
            raise WpsSyncError(
                str(result.get("error_code") or "WPS_CONNECTION_TEST_FAILED"),
                _sanitize_error(str(result.get("message") or "WPS 远端连接测试失败").replace(token, "<redacted>")),
                details=_target_error_details(target, phase="SCRIPT_EXECUTION"),
            )
        return {"http_status": response.status_code, "phase": "SUCCESS", **result}

    def sync(
        self,
        target: WpsSyncTarget,
        token: str,
        payload: Mapping[str, object],
    ) -> dict[str, Any]:
        response = self.client.post(target, token=token, argv=payload)
        result = _unwrap_wps_sync_task_response(response, target, token=token)
        self._validate_common(target, result)
        for key in (
            "target_batch_id",
            "site_id",
            "business_key",
            "snapshot_revision",
            "snapshot_sha256",
        ):
            if str(result.get(key) or "") != str(payload.get(key) or ""):
                raise WpsSyncError(
                    "WPS_RESPONSE_IDENTITY_MISMATCH",
                    f"WPS 返回的 {key} 与本次同步不一致",
                    details=_target_error_details(target, phase="DOCUMENT_IDENTITY"),
                )
        if not bool(result.get("success")):
            raise WpsSyncError(
                str(result.get("error_code") or "WPS_REMOTE_FAILED"),
                _sanitize_error(str(result.get("message") or "WPS 远端同步失败").replace(token, "<redacted>")),
                details=_target_error_details(target, phase="SCRIPT_EXECUTION"),
            )
        return {"http_status": response.status_code, "phase": "SUCCESS", **result}

    @staticmethod
    def _validate_common(target: WpsSyncTarget, result: Mapping[str, object]) -> None:
        if int(result.get("protocol_version") or 0) != WPS_SYNC_PROTOCOL_VERSION:
            raise WpsSyncError(
                "WPS_PROTOCOL_MISMATCH",
                "WPS 脚本协议版本不兼容",
                details=_target_error_details(target, phase="PROTOCOL_HANDSHAKE"),
            )
        if str(result.get("target_type") or "") != target.target_type.value:
            raise WpsSyncError(
                "WPS_TARGET_TYPE_MISMATCH",
                "WPS 目标类型不匹配",
                details=_target_error_details(target, phase="PROTOCOL_HANDSHAKE"),
            )
        if str(result.get("document_id") or "") != target.expected_document_id:
            raise WpsSyncError(
                "WPS_DOCUMENT_ID_MISMATCH",
                "WPS 文档身份校验失败",
                details=_target_error_details(target, phase="DOCUMENT_IDENTITY"),
            )


class WpsStandardSpreadsheetAdapter(BaseWpsAdapter):
    pass


class WpsSmartSheetAdapter(BaseWpsAdapter):
    pass


class TracksideApWpsSyncService:
    def __init__(
        self,
        paths: PathResolver,
        *,
        client: WpsAirScriptClient | None = None,
    ) -> None:
        self.paths = paths
        self.client = client or WpsAirScriptClient()
        self.adapters = {
            WpsTargetType.STANDARD_SPREADSHEET: WpsStandardSpreadsheetAdapter(
                self.client
            ),
            WpsTargetType.SMART_SHEET: WpsSmartSheetAdapter(self.client),
        }

    def list_targets(self, site_id: str) -> list[dict[str, Any]]:
        repository = self._repository(site_id)
        self._ensure_default_targets(repository)
        return [
            self._public_target(
                target,
                env_token_configured=self._env_token(target.target_code) != "",
            )
            for target in repository.list_targets(TRACKSIDE_AP_WPS_BUSINESS_KEY)
        ]

    def configure_target(
        self,
        site_id: str,
        target_code: str,
        *,
        token: str | None = None,
        document_open_url: str | None = None,
        webhook_url: str | None = None,
        enabled: bool | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        repository = self._repository(site_id)
        self._ensure_default_targets(repository)
        target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, target_code)
        selected_document_url = (
            target.document_open_url
            if document_open_url is None
            else _validate_wps_url(document_open_url, kind="document")
        )
        selected_webhook_url = (
            target.webhook_url
            if webhook_url is None
            else _validate_wps_url(webhook_url, kind="webhook")
        )
        selected_document_id = (
            target.expected_document_id
            if webhook_url is None
            else _document_id_from_webhook(selected_webhook_url)
        )
        configured = repository.upsert_target(
            business_key=target.business_key,
            target_code=target.target_code,
            target_type=target.target_type,
            target_name=target.target_name,
            document_open_url=selected_document_url,
            webhook_url=selected_webhook_url,
            expected_document_id=selected_document_id,
            enabled=target.enabled if enabled is None else enabled,
            timeout_seconds=(
                target.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
            token=token,
            credential_id=target.credential_id,
        )
        return self._public_target(
            configured,
            env_token_configured=self._env_token(configured.target_code) != "",
        )

    def connection_test(self, site_id: str, target_code: str) -> dict[str, Any]:
        repository = self._repository(site_id)
        self._ensure_default_targets(repository)
        target = repository.get_target(TRACKSIDE_AP_WPS_BUSINESS_KEY, target_code)
        try:
            _validate_target_configuration(target)
            result = self.adapters[target.target_type].connection_test(
                target,
                self._token(repository, target),
            )
        except WpsSyncError as exc:
            if not exc.details:
                exc.details.update(_target_error_details(target, phase="LOCAL_CONFIGURATION"))
            repository.update_target_test(
                target.target_id,
                status="FAILED",
                message=str(exc),
            )
            raise
        repository.update_target_test(
            target.target_id,
            status="SUCCESS",
            message="连接测试通过",
        )
        return _sanitize_result(result)

    def sync(
        self,
        site_id: str,
        *,
        target_codes: Sequence[str] = (),
        expected_revision: str = "",
        progress: Callable[[str, int, int, str], None] | None = None,
        should_cancel: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        repository = self._repository(site_id)
        self._ensure_default_targets(repository)
        requested_codes = tuple(dict.fromkeys(target_codes or _VALID_TARGET_CODES))
        if not requested_codes or any(code not in _VALID_TARGET_CODES for code in requested_codes):
            raise WpsSyncError("WPS_TARGET_INVALID", "WPS 同步目标无效")
        targets_by_code = {
            target.target_code: target
            for target in repository.list_targets(TRACKSIDE_AP_WPS_BUSINESS_KEY)
        }
        targets = [targets_by_code[code] for code in requested_codes]
        disabled = [target.target_name for target in targets if not target.enabled]
        if disabled:
            raise WpsSyncError(
                "WPS_TARGET_DISABLED",
                f"WPS 目标未启用：{', '.join(disabled)}",
            )

        if should_cancel is not None:
            should_cancel()
        if progress is not None:
            progress("wps_snapshot", 5, 100, "正在冻结轨旁 AP 业务快照")
        snapshot = self._build_snapshot(site_id)
        revision = str(snapshot.get("business_revision") or "")
        if expected_revision and revision != expected_revision:
            raise WpsSyncError("TRACKSIDE_AP_SNAPSHOT_STALE", "轨旁 AP 数据已更新，请刷新后重试")
        batch_id = f"wps_{uuid4().hex}"
        workbook, snapshot_sha256, payload_size = self._build_workbook_dto(
            site_id,
            batch_id,
            snapshot,
        )
        if progress is not None:
            progress("wps_workbook", 30, 100, f"已生成统一工作簿数据集（{len(workbook.sheets)} 个 Sheet）")
        generated_at = str(snapshot.get("created_at") or _now())
        repository.create_batch(
            batch_id=batch_id,
            business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
            revision=revision,
            snapshot_sha256=snapshot_sha256,
            snapshot_generated_at=generated_at,
            target_count=len(targets),
        )
        results: list[dict[str, Any]] = []
        for target_index, target in enumerate(targets, start=1):
            if should_cancel is not None:
                should_cancel()
            target_batch_id = f"{batch_id}_{target.target_code}"
            repository.create_target_run(
                target_batch_id=target_batch_id,
                batch_id=batch_id,
                target=target,
            )
            request_payload = {
                "protocol_version": WPS_SYNC_PROTOCOL_VERSION,
                "operation": "sync_trackside_ap_business",
                "parent_batch_id": batch_id,
                "target_batch_id": target_batch_id,
                "target_type": target.target_type.value,
                "target_code": target.target_code,
                "binding_id": target.target_id,
                "initialize_binding": True,
                "site_id": site_id,
                "site_name": self._site_display_name(site_id),
                "business_key": TRACKSIDE_AP_WPS_BUSINESS_KEY,
                "snapshot_revision": revision,
                "snapshot_sha256": snapshot_sha256,
                "snapshot_generated_at": generated_at,
                "requested_at": _now(),
                "workbook": workbook.to_dict(),
            }
            try:
                _validate_target_configuration(target)
                if progress is not None:
                    progress(
                        "wps_target_sync",
                        30 + int((target_index - 1) * 65 / max(len(targets), 1)),
                        100,
                        f"正在同步 {target.target_name}",
                    )
                response = self.adapters[target.target_type].sync(
                    target,
                    self._token(repository, target),
                    request_payload,
                )
                public = {
                    "target_code": target.target_code,
                    "target_name": target.target_name,
                    "target_type": target.target_type.value,
                    "target_batch_id": target_batch_id,
                    "status": "SUCCESS",
                    **_sanitize_result(response),
                }
                repository.complete_target_run(
                    target_batch_id,
                    status="SUCCESS",
                    result=public,
                )
                repository.update_target_sync(
                    target.target_id,
                    status="SUCCESS",
                    revision=revision,
                )
            except WpsSyncError as exc:
                public = {
                    "target_code": target.target_code,
                    "target_name": target.target_name,
                    "target_type": target.target_type.value,
                    "target_batch_id": target_batch_id,
                    "status": "FAILED",
                    "error_code": exc.code,
                    "message": str(exc),
                }
                repository.complete_target_run(
                    target_batch_id,
                    status="FAILED",
                    result=public,
                    error_code=exc.code,
                    error_message=str(exc),
                )
                repository.update_target_sync(
                    target.target_id,
                    status="FAILED",
                    revision=revision,
                )
            results.append(public)
            if progress is not None:
                progress(
                    "wps_target_sync",
                    30 + int(target_index * 65 / max(len(targets), 1)),
                    100,
                    f"{target.target_name}同步完成：{public['status']}",
                )
        success_count = sum(result["status"] == "SUCCESS" for result in results)
        failed_count = len(results) - success_count
        status = (
            "SUCCESS"
            if failed_count == 0
            else "FAILED"
            if success_count == 0
            else "PARTIAL_SUCCESS"
        )
        summary = {
            "batch_id": batch_id,
            "site_id": site_id,
            "business_key": TRACKSIDE_AP_WPS_BUSINESS_KEY,
            "snapshot_revision": revision,
            "snapshot_sha256": snapshot_sha256,
            "snapshot_generated_at": generated_at,
            "payload_bytes": payload_size,
            "sheet_count": len(workbook.sheets),
            "status": status,
            "target_count": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "partial_success": status == "PARTIAL_SUCCESS",
            "targets": results,
        }
        repository.complete_batch(
            batch_id,
            status=status,
            success_count=success_count,
            failed_count=failed_count,
            summary=summary,
        )
        if progress is not None:
            progress("wps_complete", 100, 100, f"WPS 双目标同步完成：{status}")
        return summary

    def recent_batches(self, site_id: str, limit: int = 10) -> list[dict[str, object]]:
        repository = self._repository(site_id)
        self._ensure_default_targets(repository)
        return repository.recent_batches(TRACKSIDE_AP_WPS_BUSINESS_KEY, limit)

    def _build_snapshot(self, site_id: str) -> dict[str, object]:
        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        scope_context = {
            **metadata,
            "site_id": site_id,
            "site_display_name": self._site_display_name(site_id),
            "generated_at": _now(),
        }
        return build_trackside_ap_business_export_snapshot(
            DeviceRepository(Database(self.paths.site_db_path(site_id))),
            site_id,
            scope_context=scope_context,
        )

    def _build_workbook_dto(
        self,
        site_id: str,
        batch_id: str,
        snapshot: Mapping[str, object],
    ) -> tuple[WorkbookDTO, str, int]:
        root = (self.paths.temp_dir / "wps_trackside_ap" / site_id / batch_id).resolve()
        root.mkdir(parents=True, exist_ok=False)
        output = root / "trackside-ap-business.xlsx"
        tmp = root / "trackside-ap-business.xlsx.tmp"
        try:
            _render_trackside_ap_business_export(
                snapshot,
                output_path=output,
                tmp_path=tmp,
                language="zh_CN",
                progress_callback=None,
                should_cancel=None,
            )
            workbook = workbook_dto_from_xlsx(output)
            digest_payload = {
                "site_id": site_id,
                "business_key": TRACKSIDE_AP_WPS_BUSINESS_KEY,
                "snapshot_revision": str(snapshot.get("business_revision") or ""),
                "workbook": workbook.to_dict(),
            }
            serialized = canonical_json_bytes(digest_payload)
            if len(serialized) > _MAX_PAYLOAD_BYTES:
                raise WpsSyncError(
                    "WPS_PAYLOAD_TOO_LARGE",
                    "轨旁 AP 工作簿超过 WPS 单次同步安全大小",
                )
            return workbook, content_sha256(digest_payload), len(serialized)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _ensure_default_targets(self, repository: WpsSyncRepository) -> None:
        existing_targets = repository.list_targets(TRACKSIDE_AP_WPS_BUSINESS_KEY)
        existing = {target.target_code: target for target in existing_targets}
        credential_owners: dict[str, str] = {}
        for target in existing_targets:
            owner = credential_owners.setdefault(target.credential_id, target.target_code)
            if owner == target.target_code:
                continue
            token = repository.resolve_token(target)
            repository.upsert_target(
                business_key=target.business_key,
                target_code=target.target_code,
                target_type=target.target_type,
                target_name=target.target_name,
                document_open_url=target.document_open_url,
                webhook_url=target.webhook_url,
                expected_document_id=target.expected_document_id,
                enabled=target.enabled,
                timeout_seconds=target.timeout_seconds,
                token=token or None,
                credential_id=f"wsc_{uuid4().hex}",
            )
        for definition in DEFAULT_TARGETS:
            if definition["target_code"] in existing:
                continue
            repository.upsert_target(
                business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
                **definition,
                credential_id=f"wsc_{uuid4().hex}",
            )

    def _repository(self, site_id: str) -> WpsSyncRepository:
        selected = SiteManager(self.paths).validate_site_name(site_id)
        return WpsSyncRepository(self.paths, selected)

    def _site_display_name(self, site_id: str) -> str:
        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        return str(metadata.get("display_name") or site_id)

    @staticmethod
    def _env_token(target_code: str) -> str:
        name = _TARGET_TOKEN_ENV.get(target_code, "")
        return str(os.environ.get(name) or "").strip() if name else ""

    def _token(self, repository: WpsSyncRepository, target: WpsSyncTarget) -> str:
        return repository.resolve_token(target) or self._env_token(target.target_code)

    @staticmethod
    def _public_target(
        target: WpsSyncTarget,
        *,
        env_token_configured: bool,
    ) -> dict[str, Any]:
        result = target.public_dict()
        result["token_configured"] = bool(
            target.token_configured or env_token_configured
        )
        if env_token_configured and not target.token_configured:
            result["token_suffix"] = ""
        return result


def workbook_dto_from_xlsx(path: str | Path) -> WorkbookDTO:
    workbook = load_workbook(Path(path), data_only=False, read_only=False)
    try:
        sheets: list[WorkbookSheetDTO] = []
        for worksheet in workbook.worksheets:
            if worksheet.title in _META_SHEET_NAMES or worksheet.title.startswith("_NetConsole"):
                continue
            max_row = int(worksheet.max_row or 0)
            max_column = int(worksheet.max_column or 0)
            cells = [
                [worksheet.cell(row=row, column=column).value for column in range(1, max_column + 1)]
                for row in range(1, max_row + 1)
            ]
            number_formats: dict[str, str] = {}
            fills: dict[str, str] = {}
            fonts: dict[str, dict[str, Any]] = {}
            alignments: dict[str, dict[str, Any]] = {}
            for row in worksheet.iter_rows():
                for cell in row:
                    coordinate = cell.coordinate
                    if cell.number_format and cell.number_format != "General":
                        number_formats[coordinate] = cell.number_format
                    color = cell.fill.fgColor.rgb if cell.fill.fill_type else None
                    if color:
                        fills[coordinate] = str(color)
                    if cell.font.bold or cell.font.italic or cell.font.color:
                        fonts[coordinate] = {
                            "bold": bool(cell.font.bold),
                            "italic": bool(cell.font.italic),
                            "color": str(cell.font.color.rgb or "") if cell.font.color else "",
                        }
                    if cell.alignment.horizontal or cell.alignment.vertical:
                        alignments[coordinate] = {
                            "horizontal": str(cell.alignment.horizontal or ""),
                            "vertical": str(cell.alignment.vertical or ""),
                            "wrap_text": bool(cell.alignment.wrap_text),
                        }
            sync_mode = (
                WpsSyncMode.APPEND_SNAPSHOT
                if worksheet.title.replace(" ", "") == "AP上线情况概览"
                else WpsSyncMode.FULL_REPLACE
            )
            sheets.append(
                WorkbookSheetDTO(
                    logical_sheet_key=_logical_sheet_key(worksheet.title),
                    sheet_name=worksheet.title,
                    sync_mode=sync_mode,
                    cells=cells,
                    row_count=max_row,
                    column_count=max_column,
                    merges=[str(value) for value in worksheet.merged_cells.ranges],
                    row_heights={
                        str(index): float(dimension.height)
                        for index, dimension in worksheet.row_dimensions.items()
                        if dimension.height is not None
                    },
                    column_widths={
                        str(index): float(dimension.width)
                        for index, dimension in worksheet.column_dimensions.items()
                        if dimension.width is not None
                    },
                    number_formats=number_formats,
                    fills=fills,
                    fonts=fonts,
                    alignments=alignments,
                    freeze_panes=str(worksheet.freeze_panes or ""),
                )
            )
        return WorkbookDTO(sheets=tuple(sheets))
    finally:
        workbook.close()


def _logical_sheet_key(name: str) -> str:
    if name.replace(" ", "") == "AP上线情况概览":
        return "ap_online_overview"
    digest = content_sha256({"sheet_name": name})[:12]
    return f"sheet_{digest}"


def _sanitize_error(value: str) -> str:
    sanitized = _SAFE_ERROR_RE.sub("credential=<redacted>", str(value or ""))
    sanitized = re.sub(r"(?i)(cookie|set-cookie|x-api-key)\s*[:=]\s*\S+", "header=<redacted>", sanitized)
    sanitized = re.sub(r"<[^>]{0,200}>", " ", sanitized)
    return re.sub(r"\s+", " ", sanitized).strip()[:_MAX_ERROR_TEXT]


def _sanitize_details(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        key_text = str(key)
        if re.search(r"(?i)(token|authorization|cookie|header|webhook)", key_text):
            continue
        if isinstance(item, Mapping):
            result[key_text] = _sanitize_details(item)
        elif isinstance(item, list):
            result[key_text] = [
                _sanitize_error(str(entry)) if isinstance(entry, str) else entry
                for entry in item[:20]
            ]
        elif isinstance(item, str):
            result[key_text] = _sanitize_error(item)
        elif item is None or isinstance(item, (bool, int, float)):
            result[key_text] = item
    return result


def _target_error_details(target: WpsSyncTarget, *, phase: str) -> dict[str, object]:
    return {
        "phase": phase,
        "target_code": target.target_code,
        "document_id": target.expected_document_id,
    }


def _unwrap_wps_sync_task_response(
    response: WpsHttpResponse,
    target: WpsSyncTarget,
    *,
    token: str = "",
) -> dict[str, Any]:
    body = response.body
    if not isinstance(body, Mapping):
        raise WpsSyncError(
            "WPS_RESPONSE_INVALID",
            "WPS 返回结构无效",
            details=_target_error_details(target, phase="SCRIPT_EXECUTION"),
        )

    # Keep compatibility with existing direct protocol-object test doubles while
    # preferring the official sync_task execution envelope in production.
    if "protocol_version" in body and "data" not in body:
        return dict(body)

    status = str(body.get("status") or "").strip().casefold()
    details = _target_error_details(target, phase="SCRIPT_EXECUTION")
    if status not in {"finished", "success", "completed"}:
        details["execution_status"] = status or "missing"
        raise WpsSyncError(
            "WPS_SCRIPT_STATUS_INVALID",
            f"WPS 脚本执行状态未完成：{status or '未知'}",
            details=details,
        )

    outer_error = body.get("error")
    if outer_error:
        error_details = body.get("error_details")
        remote_message = _remote_error_message(outer_error, error_details)
        if token:
            remote_message = remote_message.replace(token, "<redacted>")
        raise WpsSyncError(
            "WPS_SCRIPT_EXECUTION_FAILED",
            f"WPS 脚本执行失败：{remote_message}",
            details={**details, "remote_message": remote_message},
        )

    data = body.get("data")
    if not isinstance(data, Mapping):
        raise WpsSyncError(
            "WPS_SCRIPT_RESULT_EMPTY",
            "WPS 脚本响应缺少 data.result",
            details=details,
        )
    raw_result = data.get("result")
    if raw_result is None:
        raise WpsSyncError(
            "WPS_SCRIPT_RESULT_EMPTY",
            "WPS 脚本返回结果为空",
            details=details,
        )
    if isinstance(raw_result, Mapping):
        return dict(raw_result)
    if not isinstance(raw_result, str) or not raw_result.strip():
        raise WpsSyncError(
            "WPS_SCRIPT_RESULT_INVALID",
            "WPS 脚本返回结果不是 JSON 对象",
            details=details,
        )
    try:
        decoded = json.loads(raw_result)
    except json.JSONDecodeError:
        raise WpsSyncError(
            "WPS_SCRIPT_RESULT_INVALID",
            "WPS 脚本返回结果不是有效 JSON",
            details=details,
        ) from None
    if not isinstance(decoded, Mapping):
        raise WpsSyncError(
            "WPS_SCRIPT_RESULT_INVALID",
            "WPS 脚本返回结果不是 JSON 对象",
            details=details,
        )
    return dict(decoded)


def _remote_error_message(value: object, details: object = None) -> str:
    values: list[str] = []
    if isinstance(value, Mapping):
        for key in ("message", "msg", "error_description", "error"):
            if value.get(key):
                values.append(str(value[key]))
    elif value:
        values.append(str(value))
    if isinstance(details, Mapping):
        for key in ("name", "message", "msg", "error_description"):
            if details.get(key):
                values.append(str(details[key]))
    return _sanitize_error("；".join(values) or "远端未提供具体原因")


def _http_error_from_response(
    exc: urllib.error.HTTPError,
    target: WpsSyncTarget,
    token: str,
) -> WpsSyncError:
    raw = b""
    try:
        raw = exc.read(_MAX_ERROR_BODY_BYTES + 1)
    except (OSError, ValueError):
        pass
    too_large = len(raw) > _MAX_ERROR_BODY_BYTES
    raw = raw[:_MAX_ERROR_BODY_BYTES]
    remote_code, remote_message, response_format, request_id = _extract_http_error(raw)
    if token:
        remote_code = remote_code.replace(token, "<redacted>")
        remote_message = remote_message.replace(token, "<redacted>")
        request_id = request_id.replace(token, "<redacted>")
    if too_large:
        remote_message = "WPS 错误响应正文超过安全限制"
        response_format = "oversized"
    code = _classify_http_error(int(exc.code), remote_code, remote_message)
    status_text = int(exc.code)
    fallback = {
        401: "WPS 令牌无效或已过期",
        403: "请检查脚本令牌、文档权限和文档共享脚本状态",
        404: "请检查 webhook 地址和脚本发布状态",
        429: "WPS 请求过于频繁，请稍后重试",
    }.get(status_text, "请检查 WPS 服务状态和网络连接")
    if code == "WPS_SCRIPT_NOT_AVAILABLE":
        fallback = "请在对应文档中发布文档共享脚本，并确认 webhook 与该脚本匹配"
    elif code == "WPS_DOCUMENT_PERMISSION_DENIED":
        fallback = "请确认当前令牌所属账号拥有该文档的访问和编辑权限"
    elif code == "WPS_SCRIPT_PERMISSION_DENIED":
        fallback = "请确认 webhook 对应脚本已发布且允许通过脚本令牌执行"
    elif code == "WPS_TOKEN_INVALID":
        fallback = "请在 WPS 重新生成令牌，并在对应目标配置中重新保存"
    message = (
        f"WPS 请求失败（HTTP {status_text}），错误码：{remote_code or code}，"
        f"原因：{remote_message or '远端未提供具体原因'}。建议：{fallback}"
    )
    details = {
        **_target_error_details(target, phase="HTTP_AUTH"),
        "http_status": status_text,
        "remote_error_code": remote_code,
        "remote_message": remote_message,
        "response_format": response_format,
        "request_id": request_id,
        "suggestion": fallback,
    }
    # Explicitly include the token in sanitization input without retaining it.
    safe_message = _sanitize_error(message.replace(token, "<redacted>")) if token else message
    return WpsSyncError(code, safe_message, details=details)


def _extract_http_error(raw: bytes) -> tuple[str, str, str, str]:
    if not raw:
        return "", "", "empty", ""
    text = _sanitize_error(raw.decode("utf-8", errors="replace"))
    try:
        decoded = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "", text, "text", ""
    if not isinstance(decoded, Mapping):
        return "", text, "json", ""
    nested = decoded.get("error_details")
    code = ""
    for key in ("code", "error_code"):
        if decoded.get(key):
            code = _sanitize_error(str(decoded[key]))
            break
    message = _remote_error_message(decoded, nested)
    request_id = ""
    for key in ("request_id", "trace_id"):
        if decoded.get(key):
            request_id = _sanitize_error(str(decoded[key]))
            break
    return code, message, "json", request_id


def _classify_http_error(status: int, remote_code: str, remote_message: str) -> str:
    haystack = f"{remote_code} {remote_message}".casefold()
    if status == 401 or re.search(r"token|api[_ -]?key|expired|过期|令牌", haystack):
        return "WPS_TOKEN_INVALID"
    if status == 403:
        if re.search(r"account|账号|user.*document|账户.*文档|不一致", haystack):
            return "WPS_ACCOUNT_DOCUMENT_MISMATCH"
        if re.search(r"script.*(permission|access)|脚本.*(权限|访问)", haystack):
            return "WPS_SCRIPT_PERMISSION_DENIED"
        if re.search(r"script.*(not found|unavailable|nil|empty)|脚本.*(不存在|不可用|为空)", haystack):
            return "WPS_SCRIPT_NOT_AVAILABLE"
        if re.search(r"document|file|sheet|文档|文件|表格", haystack):
            return "WPS_DOCUMENT_PERMISSION_DENIED"
        return "WPS_REMOTE_FORBIDDEN"
    if status == 404:
        return "WPS_WEBHOOK_NOT_FOUND"
    if status == 429:
        return "WPS_REMOTE_RATE_LIMITED"
    if status >= 500:
        return "WPS_REMOTE_UNAVAILABLE"
    return f"WPS_HTTP_{status}"


def _validate_wps_url(value: str, *, kind: str) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        raise WpsSyncError("WPS_URL_INVALID", "WPS 地址格式无效") from None
    hostname = str(parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme.casefold() != "https" or not hostname:
        raise WpsSyncError("WPS_URL_INVALID", "WPS 地址必须使用 HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WpsSyncError("WPS_URL_INVALID", "WPS 地址不得包含凭据、查询参数或片段")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise WpsSyncError("WPS_URL_INVALID", "WPS 地址不得使用 IP 地址")
    if hostname != "kdocs.cn" and not hostname.endswith(".kdocs.cn"):
        raise WpsSyncError("WPS_URL_INVALID", "WPS 地址必须属于 kdocs.cn")
    try:
        port = parsed.port
    except ValueError:
        raise WpsSyncError("WPS_URL_INVALID", "WPS 地址端口无效") from None
    if port not in (None, 443):
        raise WpsSyncError("WPS_URL_INVALID", "WPS 地址仅允许标准 HTTPS 端口")
    if kind == "webhook" and not parsed.path.endswith("/sync_task"):
        raise WpsSyncError("WPS_WEBHOOK_INVALID", "AirScript webhook 必须以 /sync_task 结尾")
    if kind == "document" and not parsed.path.startswith("/l/"):
        raise WpsSyncError("WPS_DOCUMENT_URL_INVALID", "在线文档地址必须使用 kdocs.cn/l/ 链接")
    return normalized


def _document_id_from_webhook(value: str) -> str:
    parts = [part for part in urlsplit(value).path.split("/") if part]
    try:
        index = parts.index("file")
        document_id = parts[index + 1]
    except (ValueError, IndexError):
        raise WpsSyncError("WPS_WEBHOOK_INVALID", "AirScript webhook 缺少文档标识") from None
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,160}", document_id):
        raise WpsSyncError("WPS_WEBHOOK_INVALID", "AirScript webhook 文档标识无效")
    return document_id


def _validate_target_configuration(target: WpsSyncTarget) -> None:
    _validate_wps_url(target.document_open_url, kind="document")
    webhook = _validate_wps_url(target.webhook_url, kind="webhook")
    if _document_id_from_webhook(webhook) != target.expected_document_id:
        raise WpsSyncError("WPS_DOCUMENT_ID_MISMATCH", "webhook 文档身份与已保存配置不一致")


def _sanitize_result(value: Mapping[str, object]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if "token" in str(key).casefold() or "header" in str(key).casefold():
            continue
        if isinstance(item, str):
            result[str(key)] = _sanitize_error(item)
        elif isinstance(item, Mapping):
            result[str(key)] = _sanitize_result(item)
        elif isinstance(item, list):
            result[str(key)] = [
                _sanitize_result(entry) if isinstance(entry, Mapping) else entry
                for entry in item
            ]
        else:
            result[str(key)] = item
    return result


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


__all__ = [
    "DEFAULT_TARGETS",
    "SMART_TARGET_CODE",
    "STANDARD_TARGET_CODE",
    "WPS_SYNC_OWNER",
    "WPS_SYNC_TASK_TYPE",
    "TracksideApWpsSyncService",
    "WpsAirScriptClient",
    "WpsSmartSheetAdapter",
    "WpsStandardSpreadsheetAdapter",
    "WpsSyncError",
    "workbook_dto_from_xlsx",
]
