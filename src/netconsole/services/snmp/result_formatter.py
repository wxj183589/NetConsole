from __future__ import annotations

from typing import Any

from netconsole.models.snmp_models import SNMP_STATUS_LABELS, SnmpCollectionResult, SnmpQueryResult, SnmpSetResult, SnmpVarBind
from netconsole.services.snmp.request_builder import build_query_request, build_set_request, query_request_to_payload, set_request_to_payload


def query_result_to_payload(result: SnmpQueryResult) -> dict[str, Any]:
    rows = sorted(result.rows, key=lambda row: _oid_sort_key(row.oid))
    return {
        "request": query_request_to_payload(result.request),
        "rows": [_varbind_to_payload(row, result) for row in rows],
        "status": result.status,
        "error_message": result.error_message,
        "elapsed_ms": result.elapsed_ms,
    }


def query_result_from_payload(payload: dict[str, Any]) -> SnmpQueryResult:
    values = dict(payload or {})
    request = build_query_request(dict(values.get("request") or {}))
    rows = [
        SnmpVarBind(
            oid=str(row.get("oid") or ""),
            value=row.get("value"),
            value_type=str(row.get("type") or row.get("value_type") or ""),
            name=str(row.get("name") or ""),
            decoded_value=str(row.get("translated_value") or row.get("decoded_value") or ""),
            instance=str(row.get("instance") or ""),
            latency_ms=int(row.get("latency_ms") or 0),
            status=str(row.get("status") or "success"),
            error_message=str(row.get("error") or row.get("error_message") or ""),
        )
        for row in values.get("rows") or []
        if isinstance(row, dict)
    ]
    return SnmpQueryResult(
        request=request,
        rows=rows,
        status=str(values.get("status") or "success"),
        error_message=str(values.get("error_message") or ""),
        elapsed_ms=int(values.get("elapsed_ms") or 0),
    )


def set_result_to_payload(result: SnmpSetResult) -> dict[str, Any]:
    return {
        "request": set_request_to_payload(result.request),
        "old_value": result.old_value,
        "new_value": result.new_value,
        "result_value": result.result_value,
        "status": result.status,
        "error_message": result.error_message,
        "elapsed_ms": result.elapsed_ms,
    }


def set_result_from_payload(payload: dict[str, Any]) -> SnmpSetResult:
    values = dict(payload or {})
    return SnmpSetResult(
        request=build_set_request(dict(values.get("request") or {})),
        old_value=str(values.get("old_value") or ""),
        new_value=str(values.get("new_value") or ""),
        result_value=str(values.get("result_value") or ""),
        status=str(values.get("status") or "success"),
        error_message=str(values.get("error_message") or ""),
        elapsed_ms=int(values.get("elapsed_ms") or 0),
    )


def collection_result_to_payload(result: SnmpCollectionResult, *, include_rows: bool = False) -> dict[str, Any]:
    return {
        "operation": result.request.operation,
        "oids": list(result.request.oids),
        "total_devices": result.total_devices,
        "success_devices": result.success_devices,
        "failed_devices": result.failed_devices,
        "pending_devices": result.pending_devices,
        "cancelled": result.cancelled,
        "stopped_early": result.stopped_early,
        "elapsed_ms": result.elapsed_ms,
        "started_at": result.request.started_at,
        "completed_at": result.completed_at,
        "devices": [
            {
                "device_id": device.device_id,
                "device_name": device.device_name,
                "host": device.host,
                "status": device.status,
                "success": device.status == "success",
                "error": device.error_message,
                "elapsed_ms": device.elapsed_ms,
                "items": [
                    {
                        "oid": item.oid,
                        "operation": item.operation,
                        "status": item.status,
                        "success": item.status == "success",
                        "error": item.error_message,
                        "attempts": item.attempts,
                        "elapsed_ms": item.elapsed_ms,
                        "timestamp": item.timestamp,
                        "row_count": len(item.rows),
                        **({"rows": [_collection_row(row) for row in item.rows]} if include_rows else {}),
                    }
                    for item in device.items
                ],
            }
            for device in result.device_results
        ],
    }


def format_browser_rows(result: SnmpQueryResult) -> list[list[Any]]:
    request = result.request
    rows: list[list[Any]] = []
    for row in sorted(result.rows, key=lambda item: _oid_sort_key(item.oid)):
        base_oid = request.base_oid or request.oid
        instance = _instance_suffix(row.oid, base_oid)
        name = row.name or request.object_name
        name_oid = f"{name}.{instance}" if name and instance else name or row.oid
        rows.append(
            [
                request.method,
                name_oid,
                row.decoded_value or row.value,
                row.value_type,
                f"{request.profile.host}:{request.profile.port}",
                SNMP_STATUS_LABELS.get(row.status, row.status),
                row.latency_ms,
                row.oid,
                instance,
                _decode_octet_string_instance(instance),
                request.module_name,
                request.started_at,
                _compact_error(row.error_message),
            ]
        )
    return rows


def format_query_rows(result: SnmpQueryResult) -> list[list[Any]]:
    return [
        [
            result.request.started_at,
            result.request.device_name,
            row.oid,
            row.name or result.request.object_name,
            row.instance or _instance_suffix(row.oid, result.request.base_oid or result.request.oid),
            row.value_type,
            row.value,
            row.decoded_value,
            row.latency_ms,
            row.status,
            row.error_message,
        ]
        for row in sorted(result.rows, key=lambda item: _oid_sort_key(item.oid))
    ]


def _varbind_to_payload(row: SnmpVarBind, result: SnmpQueryResult) -> dict[str, Any]:
    base_oid = result.request.base_oid or result.request.oid
    return {
        "oid": row.oid,
        "name": row.name or result.request.object_name,
        "value": _json_value(row.value),
        "type": row.value_type,
        "raw_value": str(row.value),
        "translated_value": row.decoded_value or str(row.value),
        "instance": row.instance or _instance_suffix(row.oid, base_oid),
        "latency_ms": row.latency_ms,
        "timestamp": result.request.started_at,
        "source": result.request.source,
        "status": row.status,
        "error": row.error_message,
    }


def _collection_row(row: SnmpVarBind) -> dict[str, Any]:
    return {
        "oid": row.oid,
        "name": row.name,
        "value": _json_value(row.value),
        "type": row.value_type,
        "raw_value": str(row.value),
        "translated_value": row.decoded_value or str(row.value),
        "instance": row.instance,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "error": row.error_message,
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _oid_sort_key(oid: object) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(oid or "").strip(".").split(".") if part)
    except ValueError:
        return (2**31 - 1,)


def _instance_suffix(oid: str, base_oid: str) -> str:
    prefix = f"{base_oid}." if base_oid else ""
    return oid[len(prefix) :] if prefix and oid.startswith(prefix) else ""


def _decode_octet_string_instance(instance: str) -> str:
    try:
        numbers = [int(part) for part in instance.split(".") if part]
    except ValueError:
        return ""
    payload = numbers[1 : 1 + numbers[0]] if len(numbers) >= 2 and len(numbers) >= numbers[0] + 1 else numbers
    if not payload or any(value < 32 or value > 126 for value in payload):
        return ""
    return "".join(chr(value) for value in payload)


def _compact_error(value: object) -> str:
    return " ".join(str(value or "").split())
