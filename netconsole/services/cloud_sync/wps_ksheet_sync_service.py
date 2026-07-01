from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
from time import perf_counter
from typing import Callable

from netconsole.core import app_logger
from netconsole.models.cloud_sync_models import CloudSyncRun, WpsReadonlyMember, WpsSheetPayload, WpsSyncResult
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.cloud_sync_repository import CloudSyncRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ap_online_overview import AP_ONLINE_OVERVIEW_COLUMNS, ApOnlineOverviewService
from netconsole.services.cloud_sync.wps_auth import WpsAuthContext
from netconsole.services.cloud_sync.wps_ksheet_client import WpsApiError, WpsKSheetClient
from netconsole.services.offline_ap_ledger import (
    OFFLINE_AP_LEDGER_COLUMNS,
    OFFLINE_AP_STATS_COLUMNS,
    build_device_lookup_by_name,
    build_latest_ap_history_indexes,
    build_offline_ap_ledger,
    offline_ap_headers,
)
from netconsole.services.trackside_ap_business import (
    AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
    NEW_ONLINE_AP_OVERVIEW_COLUMNS,
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    build_ap_optical_treatment_records,
    build_new_online_ap_overview_rows,
    build_trackside_ap_business_sheet_payloads,
    enrich_trackside_export_rows,
    filter_station_switch_devices,
)
from netconsole.ui.trackside_optical_worker import load_trackside_ap_business_snapshot


REPORT_TYPE = "trackside_ap_business"
PROFILE_NAME = "trackside_ap_business"


class TracksideApWpsKSheetSyncService:
    def __init__(
        self,
        device_repository: DeviceRepository,
        cloud_repository: CloudSyncRepository | None = None,
        client_factory: Callable[[WpsAuthContext], WpsKSheetClient] | None = None,
        header_getter: Callable[[str], str] | None = None,
    ) -> None:
        self.device_repository = device_repository
        self.cloud_repository = cloud_repository or CloudSyncRepository(device_repository.database)
        self.client_factory = client_factory or (lambda auth: WpsKSheetClient(auth))
        self.header_getter = header_getter or (lambda key: key)

    def sync_trackside_ap_business(
        self,
        site_id: str,
        profile_name: str = PROFILE_NAME,
        *,
        local_export_path: Path | None = None,
        progress_callback: Callable[[str, int | None], None] | None = None,
        cancel_event: threading.Event | None = None,
        force: bool = False,
    ) -> WpsSyncResult:
        started = datetime.now().isoformat(timespec="seconds")
        start = perf_counter()
        file_token = ""
        remote_url = ""
        try:
            self._progress(progress_callback, "wps_sync.progress_prepare")
            profile = self.cloud_repository.get_or_create_profile(site_id, "wps", profile_name)
            if not profile.enabled and not force:
                raise WpsApiError("WPS在线表格同步未启用")
            self._check_cancel(cancel_event)
            self._progress(progress_callback, "wps_sync.progress_build_data")
            payloads = self.build_trackside_ap_payloads(site_id)
            data_hash = _payloads_hash(payloads)
            old_hash = self.cloud_repository.get_document_hash(site_id, "wps", REPORT_TYPE, profile_name)
            file_token = profile.file_token
            remote_url = profile.remote_url
            if old_hash == data_hash and file_token and not force:
                result = WpsSyncResult(
                    "skipped",
                    "WPS在线表格数据无变化，已跳过写入",
                    file_token=file_token,
                    remote_url=remote_url or "",
                    rows_total=sum(len(item.rows) for item in payloads),
                    sheets_total=len(payloads),
                    skipped_unchanged=True,
                )
                self._record_success(site_id, profile_name, result, started, start, local_export_path, data_hash, profile.target_name)
                return result
            self._progress(progress_callback, "wps_sync.progress_connect")
            client = self.client_factory(WpsAuthContext.from_profile(profile))
            client.test_connection()
            self._check_cancel(cancel_event)
            self._progress(progress_callback, "wps_sync.progress_ensure_document")
            if not file_token:
                document = client.create_ksheet(profile.target_name or f"{site_id}_轨旁AP业务")
                file_token = document.file_token
                remote_url = document.url
            if not remote_url:
                remote_url = client.get_document_url(file_token)

            for payload in payloads:
                self._check_cancel(cancel_event)
                self._progress(progress_callback, "wps_sync.progress_write_sheet", payload.name)
                phase_start = perf_counter()
                sheet = client.ensure_sheet(file_token, payload.name, payload.headers)
                client.clear_sheet_data(file_token, sheet.sheet_id)
                client.write_table(file_token, sheet.sheet_id, payload.headers, payload.rows, cancel_event=cancel_event)
                client.apply_basic_format(file_token, sheet.sheet_id, [{"name": header} for header in payload.headers])
                app_logger.log_info(
                    "WPS_KSHEET_SYNC_PROFILE",
                    f"phase=write_sheet sheet={payload.name} rows={len(payload.rows)} elapsed_ms={int((perf_counter() - phase_start) * 1000)}",
                )

            permission_status = "skipped"
            permission_error = ""
            try:
                self._progress(progress_callback, "wps_sync.progress_update_permission")
                if profile.permission_mode == "readonly_link" or profile.readonly_link_enabled:
                    link = client.create_readonly_link(file_token)
                    permission_status = "success"
                    profile.readonly_link_url = link.url
                else:
                    members = [WpsReadonlyMember(account=str(item.get("account") or ""), display_name=str(item.get("display_name") or "")) for item in profile.readonly_members]
                    client.set_readonly_members(file_token, members)
                    permission_status = "success"
            except Exception as exc:
                permission_status = "failed"
                permission_error = str(exc)

            status = "success" if permission_status != "failed" else "partial_success"
            message = "同步完成" if permission_status != "failed" else f"数据已同步，但权限更新失败：{permission_error}"
            result = WpsSyncResult(
                status,
                message,
                file_token=file_token,
                remote_url=remote_url,
                rows_total=sum(len(item.rows) for item in payloads),
                sheets_total=len(payloads),
                permission_status=permission_status,
                error_message=permission_error,
            )
            self._record_success(site_id, profile_name, result, started, start, local_export_path, data_hash, profile.target_name, profile.readonly_link_url)
            self._progress(progress_callback, "wps_sync.progress_done")
            return result
        except Exception as exc:
            ended = datetime.now().isoformat(timespec="seconds")
            elapsed_ms = int((perf_counter() - start) * 1000)
            message = str(exc)
            self.cloud_repository.update_profile_sync_state(site_id, "wps", profile_name, status="failed", error_message=message)
            self.cloud_repository.add_run(
                CloudSyncRun(
                    site_id=site_id,
                    provider="wps",
                    report_type=REPORT_TYPE,
                    profile_name=profile_name,
                    action="sync",
                    status="failed",
                    file_token=file_token,
                    started_at=started,
                    ended_at=ended,
                    elapsed_ms=elapsed_ms,
                    error_message=message,
                    local_export_path=str(local_export_path or ""),
                    remote_url=remote_url,
                )
            )
            raise

    def build_trackside_ap_payloads(self, site_id: str) -> list[WpsSheetPayload]:
        ac_repository = AcRepository(self.device_repository.database)
        fact_repository = DeviceFactRepository(self.device_repository.database)
        snapshot = load_trackside_ap_business_snapshot(self.device_repository, site_id, generation=0)
        resources = ac_repository.list_all_fit_ap_resources_with_metadata()
        ac_device_names = {str(device.device_uuid or ""): device.name for device in self.device_repository.list() if str(device.device_uuid or "")}
        resources = [{**row, "ac_device_name": row.get("ac_device_name") or ac_device_names.get(str(row.get("ac_device_uuid") or ""))} for row in resources]
        optical_rows = ac_repository.list_all_fit_ap_optical()
        resource_history_rows = ac_repository.list_all_fit_ap_resource_history()
        ap_optical_history_rows = ac_repository.list_all_ap_optical_history()
        capacity_details = ac_repository.list_active_trackside_plan_capacity_details() or ac_repository.list_station_ap_capacity_details()
        overview_rows = ApOnlineOverviewService.build_rows(
            metadata_rows=ac_repository.list_fit_ap_metadata(),
            fit_ap_resources=resources,
            optical_rows=optical_rows,
            capacity_details=capacity_details,
        )
        latest_lldp, latest_optical = build_latest_ap_history_indexes(ac_repository, resources)
        devices = filter_station_switch_devices(self.device_repository.list(), self.device_repository.database, site_id)
        switch_optical_history_rows = fact_repository.list_all_optical_history([str(device.device_uuid or "") for device in devices])
        offline_stats, offline_ledger_rows = build_offline_ap_ledger(
            fit_ap_resources=resources,
            latest_lldp_by_ap=latest_lldp,
            latest_optical_by_ap=latest_optical,
            device_lookup_by_name=build_device_lookup_by_name(devices),
            resource_history_rows=resource_history_rows,
        )
        rows = enrich_trackside_export_rows(
            snapshot.rows,
            fact_repository,
            ac_repository,
            switch_optical_history_rows=switch_optical_history_rows,
            ap_optical_history_rows=ap_optical_history_rows,
        )
        new_online_ap_rows = build_new_online_ap_overview_rows(resources, resource_history_rows, snapshot.rows)
        optical_treatment_rows = build_ap_optical_treatment_records(
            rows,
            ap_optical_history_rows,
            switch_optical_history_rows,
            resources,
            resource_history_rows,
            offline_ledger_rows=offline_ledger_rows,
        )
        return build_trackside_ap_business_sheet_payloads(
            rows,
            headers=self._headers(TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS),
            ap_online_overview_rows=overview_rows,
            ap_online_overview_columns=AP_ONLINE_OVERVIEW_COLUMNS,
            ap_online_overview_headers=self._headers(AP_ONLINE_OVERVIEW_COLUMNS),
            new_online_ap_rows=new_online_ap_rows,
            new_online_ap_columns=NEW_ONLINE_AP_OVERVIEW_COLUMNS,
            new_online_ap_headers=self._headers(NEW_ONLINE_AP_OVERVIEW_COLUMNS),
            new_online_ap_sheet_title=self.header_getter("trackside.export.sheet_new_online_ap_overview"),
            ap_optical_treatment_rows=optical_treatment_rows,
            ap_optical_treatment_columns=AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
            ap_optical_treatment_headers=self._headers(AP_OPTICAL_TREATMENT_RECORD_COLUMNS),
            ap_optical_treatment_sheet_title=self.header_getter("trackside.export.sheet_ap_optical_treatment"),
            offline_ap_stats=offline_stats,
            offline_ap_ledger_rows=offline_ledger_rows,
            offline_ap_stats_headers=offline_ap_headers(OFFLINE_AP_STATS_COLUMNS),
            offline_ap_ledger_headers=offline_ap_headers(OFFLINE_AP_LEDGER_COLUMNS),
        )

    def _headers(self, columns: tuple[tuple[str, str], ...]) -> list[str]:
        return [self.header_getter(key) for key, _field in columns]

    @staticmethod
    def _progress(callback: Callable[[str, int | None], None] | None, key: str, value: object | None = None) -> None:
        if callback:
            callback(key if value is None else f"{key}|{value}", None)

    @staticmethod
    def _check_cancel(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise WpsApiError("WPS在线表格同步已取消")

    def _record_success(
        self,
        site_id: str,
        profile_name: str,
        result: WpsSyncResult,
        started: str,
        start: float,
        local_export_path: Path | None,
        data_hash: str,
        remote_name: str,
        readonly_link_url: str = "",
    ) -> None:
        ended = datetime.now().isoformat(timespec="seconds")
        elapsed_ms = int((perf_counter() - start) * 1000)
        self.cloud_repository.update_profile_sync_state(
            site_id,
            "wps",
            profile_name,
            file_token=result.file_token,
            remote_url=result.remote_url,
            readonly_link_url=readonly_link_url,
            status=result.status,
            error_message=result.error_message,
        )
        self.cloud_repository.upsert_document(
            site_id,
            "wps",
            REPORT_TYPE,
            profile_name,
            file_token=result.file_token,
            remote_url=result.remote_url,
            remote_name=remote_name,
            schema_hash="trackside_ap_business:v1",
            last_data_hash=data_hash,
        )
        self.cloud_repository.add_run(
            CloudSyncRun(
                site_id=site_id,
                provider="wps",
                report_type=REPORT_TYPE,
                profile_name=profile_name,
                action="sync",
                status=result.status,
                file_token=result.file_token,
                rows_total=result.rows_total,
                sheets_total=result.sheets_total,
                started_at=started,
                ended_at=ended,
                elapsed_ms=elapsed_ms,
                error_message=result.error_message,
                local_export_path=str(local_export_path or ""),
                remote_url=result.remote_url,
            )
        )


def _payloads_hash(payloads: list[WpsSheetPayload]) -> str:
    serializable = [{"name": item.name, "headers": item.headers, "rows": item.rows} for item in payloads]
    raw = json.dumps(serializable, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
