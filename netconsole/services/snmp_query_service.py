from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import Workbook

from netconsole.models.snmp_models import SnmpQueryRequest, SnmpQueryResult, SnmpSetRequest, SnmpSetResult
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.snmp_client import SnmpClient


class SnmpQueryService:
    def __init__(self, site_repository: SiteSnmpRepository, client: SnmpClient | None = None) -> None:
        self.site_repository = site_repository
        self.client = client or SnmpClient()

    def run(self, request: SnmpQueryRequest, *, cancel_checker=None) -> SnmpQueryResult:
        method = request.method.lower().replace(" ", "_")
        if method == "get":
            result = self.client.get(request.profile, request.oid)
        elif method in {"getnext", "get_next"}:
            result = self.client.get_next(request.profile, request.oid)
        elif method in {"getbulk", "get_bulk"}:
            result = self.client.get_bulk(request.profile, request.oid, max_repetitions=request.max_repetitions)
        elif method in {"getsubtree", "get_subtree"}:
            result = self.client.get_subtree(request.profile, request.oid, max_rows=request.max_rows, cancel_checker=cancel_checker)
        elif method == "walk":
            result = self.client.walk(request.profile, request.oid, max_rows=request.max_rows, cancel_checker=cancel_checker)
        elif method in {"bulkwalk", "bulk_walk"}:
            result = self.client.bulk_walk(request.profile, request.oid, max_repetitions=request.max_repetitions, max_rows=request.max_rows, cancel_checker=cancel_checker)
        elif method in {"table_walk", "tablewalk"}:
            result = self.client.table_walk(request.profile, request.oid, max_repetitions=request.max_repetitions, max_rows=request.max_rows, cancel_checker=cancel_checker)
        else:
            result = SnmpQueryResult(request=request, status="failed", error_message=f"不支持的查询方式：{request.method}")
        result = SnmpQueryResult(request=request, rows=result.rows, status=result.status, error_message=result.error_message, elapsed_ms=result.elapsed_ms)
        if request.save_history:
            self.site_repository.save_query_history(result)
        return result

    def set_value(self, request: SnmpSetRequest) -> SnmpSetResult:
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
            after = self.client.get(request.profile, request.oid)
            verify_value = str(after.rows[0].decoded_value or after.rows[0].value) if after.rows else ""
            if after.status == "success":
                result = SnmpSetResult(request=set_request, old_value=old_value, new_value=request.value, result_value=verify_value, status="success", error_message="Set 后验证成功。", elapsed_ms=result.elapsed_ms + after.elapsed_ms)
            else:
                result = SnmpSetResult(request=set_request, old_value=old_value, new_value=request.value, result_value=verify_value, status="verify_failed", error_message=f"Set 已发送，但 Set 后 Get 验证失败：{after.error_message}", elapsed_ms=result.elapsed_ms + after.elapsed_ms)
        else:
            result = SnmpSetResult(request=set_request, old_value=old_value, new_value=request.value, result_value=result.result_value, status=result.status, error_message=result.error_message, elapsed_ms=result.elapsed_ms)
        self.site_repository.save_set_history(result)
        return result

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
