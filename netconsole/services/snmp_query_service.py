from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Callable

from openpyxl import Workbook

from netconsole.models.snmp_models import SnmpQueryRequest, SnmpQueryResult, SnmpSetRequest, SnmpSetResult
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.snmp_client import SnmpClient


class SnmpQueryService:
    def __init__(self, site_repository: SiteSnmpRepository, client: SnmpClient | None = None) -> None:
        self.site_repository = site_repository
        self.client = client or SnmpClient()

    def run(
        self,
        request: SnmpQueryRequest,
        *,
        cancel_checker: Callable[[], bool] | None = None,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> SnmpQueryResult:
        method = request.method.lower().replace(" ", "_")
        self._progress(progress_callback, "snmp_query", 0, self._progress_total(request), f"正在执行 SNMP {request.method}...")
        if cancel_checker is not None and cancel_checker():
            return SnmpQueryResult(request=request, status="cancelled", error_message="查询已取消。")
        if method == "get":
            result = self.client.get(request.profile, request.oid)
        elif method in {"getnext", "get_next"}:
            result = self.client.get_next(request.profile, request.oid)
        elif method in {"getbulk", "get_bulk"}:
            options = {"max_repetitions": request.max_repetitions}
            if request.non_repeaters:
                options["non_repeaters"] = request.non_repeaters
            result = self.client.get_bulk(request.profile, request.oid, **options)
        elif method in {"getsubtree", "get_subtree"}:
            options = self._walk_options(cancel_checker, progress_callback, request)
            result = self.client.get_subtree(
                request.profile,
                request.oid,
                max_rows=request.max_rows,
                **options,
            )
        elif method == "walk":
            options = self._walk_options(cancel_checker, progress_callback, request)
            result = self.client.walk(
                request.profile,
                request.oid,
                max_rows=request.max_rows,
                **options,
            )
        elif method in {"bulkwalk", "bulk_walk"}:
            options = self._walk_options(cancel_checker, progress_callback, request)
            result = self.client.bulk_walk(
                request.profile,
                request.oid,
                max_repetitions=request.max_repetitions,
                max_rows=request.max_rows,
                **({"non_repeaters": request.non_repeaters} if request.non_repeaters else {}),
                **options,
            )
        elif method in {"table_walk", "tablewalk"}:
            options = self._walk_options(cancel_checker, progress_callback, request)
            result = self.client.table_walk(
                request.profile,
                request.oid,
                max_repetitions=request.max_repetitions,
                max_rows=request.max_rows,
                **({"non_repeaters": request.non_repeaters} if request.non_repeaters else {}),
                **options,
            )
        else:
            result = SnmpQueryResult(request=request, status="failed", error_message=f"不支持的查询方式：{request.method}")
        result = SnmpQueryResult(request=request, rows=result.rows, status=result.status, error_message=result.error_message, elapsed_ms=result.elapsed_ms)
        if request.save_history:
            self.site_repository.save_query_history(result)
        self._progress(
            progress_callback,
            "snmp_query",
            len(result.rows) if self._is_walk(request.method) else 1,
            self._progress_total(request),
            f"SNMP {request.method} 完成，返回 {len(result.rows)} 条。",
        )
        return result

    def set_value(
        self,
        request: SnmpSetRequest,
        *,
        cancel_checker: Callable[[], bool] | None = None,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> SnmpSetResult:
        self._progress(progress_callback, "snmp_set", 0, 3, "正在读取 SNMP Set 当前值...")
        if cancel_checker is not None and cancel_checker():
            return self._cancelled_set(request)
        if not self.site_repository.snmp_set_enabled():
            result = SnmpSetResult(request=request, status="cancelled", error_message="SNMP Set 默认关闭，请先在高级参数中启用写操作。")
            self.site_repository.save_set_history(result)
            return result
        version = request.profile.version.lower()
        if version in {"v1", "v2", "v2c"} and not request.profile.community_rw:
            result = SnmpSetResult(request=request, status="auth_failed", error_message="当前设备未配置 SNMP 写团体字 community_rw，不能执行 Set。")
            self.site_repository.save_set_history(result)
            return result
        if version == "v3" and request.profile.security_level.lower() != "authpriv":
            result = SnmpSetResult(request=request, status="auth_failed", error_message="当前 SNMPv3 安全级别可能不允许写操作，请检查设备 SNMPv3 写权限。")
            self.site_repository.save_set_history(result)
            return result
        access = request.access.strip().lower()
        if access and access not in {"read-write", "read-create", "write-only"}:
            result = SnmpSetResult(request=request, status="not_writable", error_message=f"当前对象访问权限为 {request.access}，不能执行 Set。")
            self.site_repository.save_set_history(result)
            return result
        before = self.client.get(request.profile, request.oid)
        old_value = str(before.rows[0].decoded_value or before.rows[0].value) if before.rows else request.old_value
        if before.status not in {"success", "no_such_instance"}:
            result = SnmpSetResult(request=request, old_value=old_value, status=before.status, error_message=f"Set 前 Get 当前值失败：{before.error_message}")
            self.site_repository.save_set_history(result)
            return result
        if cancel_checker is not None and cancel_checker():
            return self._cancelled_set(request, old_value=old_value)
        self._progress(progress_callback, "snmp_set", 1, 3, "正在发送 SNMP Set...")
        set_request = SnmpSetRequest(
            profile=request.profile,
            oid=request.oid,
            data_type=request.data_type,
            value=request.value,
            device_id=request.device_id,
            device_name=request.device_name,
            object_name=request.object_name,
            module_name=request.module_name,
            access=request.access,
            old_value=old_value,
            started_at=request.started_at,
        )
        result = self.client.set_value(set_request)
        if result.status == "success":
            if cancel_checker is not None and cancel_checker():
                return self._cancelled_set(set_request, old_value=old_value)
            self._progress(progress_callback, "snmp_set", 2, 3, "正在验证 SNMP Set 结果...")
            after = self.client.get(request.profile, request.oid)
            verify_value = str(after.rows[0].decoded_value or after.rows[0].value) if after.rows else ""
            if after.status == "success":
                result = SnmpSetResult(request=set_request, old_value=old_value, new_value=request.value, result_value=verify_value, status="success", error_message="Set 后验证成功。", elapsed_ms=result.elapsed_ms + after.elapsed_ms)
            else:
                result = SnmpSetResult(request=set_request, old_value=old_value, new_value=request.value, result_value=verify_value, status="verify_failed", error_message=f"Set 已发送，但 Set 后 Get 验证失败：{after.error_message}", elapsed_ms=result.elapsed_ms + after.elapsed_ms)
        else:
            result = SnmpSetResult(request=set_request, old_value=old_value, new_value=request.value, result_value=result.result_value, status=result.status, error_message=result.error_message, elapsed_ms=result.elapsed_ms)
        self.site_repository.save_set_history(result)
        self._progress(progress_callback, "snmp_set", 3, 3, "SNMP Set 执行完成。")
        return result

    def _cancelled_set(self, request: SnmpSetRequest, *, old_value: str = "") -> SnmpSetResult:
        result = SnmpSetResult(request=request, old_value=old_value, status="cancelled", error_message="SNMP Set 已取消。")
        self.site_repository.save_set_history(result)
        return result

    @staticmethod
    def _progress(callback, stage: str, current: int, total: int, message: str) -> None:
        if callback is not None:
            callback(stage, current, total, message)

    @classmethod
    def _client_progress(cls, callback, request: SnmpQueryRequest):
        if callback is None:
            return None

        def report(current: int, total: int) -> None:
            cls._progress(callback, "snmp_walk", current, total, f"正在执行 SNMP {request.method}，已返回 {current} 条...")

        return report

    @classmethod
    def _walk_options(cls, cancel_checker, progress_callback, request: SnmpQueryRequest) -> dict[str, object]:
        options: dict[str, object] = {"cancel_checker": cancel_checker}
        client_progress = cls._client_progress(progress_callback, request)
        if client_progress is not None:
            options["progress_callback"] = client_progress
        return options

    @staticmethod
    def _is_walk(method: str) -> bool:
        return method.lower().replace(" ", "_") in {"getsubtree", "get_subtree", "walk", "bulkwalk", "bulk_walk", "tablewalk", "table_walk"}

    @classmethod
    def _progress_total(cls, request: SnmpQueryRequest) -> int:
        return max(1, request.max_rows) if cls._is_walk(request.method) else 1

    def export_result(self, result: SnmpQueryResult, target_path: str | Path) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "时间": result.request.started_at,
                "设备": result.request.device_name,
                "OID": row.oid,
                "名称": row.name,
                "实例": row.instance,
                "类型": row.value_type,
                "原始值": str(row.value),
                "解码值": row.decoded_value,
                "延迟": row.latency_ms,
                "状态": row.status,
                "错误信息": row.error_message,
            }
            for row in result.rows
        ]
        if target.suffix.lower() == ".json":
            target.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        elif target.suffix.lower() == ".xlsx":
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "SNMP查询结果"
            headers = list(rows[0].keys()) if rows else ["时间", "设备", "OID", "名称", "实例", "类型", "原始值", "解码值", "延迟", "状态", "错误信息"]
            sheet.append(headers)
            for row in rows:
                sheet.append([row.get(header, "") for header in headers])
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            workbook.save(target)
        else:
            with target.open("w", encoding="utf-8-sig", newline="") as file:
                headers = list(rows[0].keys()) if rows else ["时间", "设备", "OID", "名称", "实例", "类型", "原始值", "解码值", "延迟", "状态", "错误信息"]
                writer = csv.DictWriter(file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
        return target
