from __future__ import annotations

from datetime import datetime
from typing import Any

from netconsole.models.snmp_models import (
    SnmpCollectionRequest,
    SnmpCollectionTarget,
    SnmpOperation,
    SnmpProfile,
    SnmpQueryRequest,
    SnmpSetRequest,
)


_METHOD_ALIASES = {
    "GET": "Get",
    "GETNEXT": "GetNext",
    "GET_NEXT": "GetNext",
    "GETBULK": "GetBulk",
    "GET_BULK": "GetBulk",
    "GETSUBTREE": "GetSubtree",
    "GET_SUBTREE": "GetSubtree",
    "WALK": "Walk",
    "BULKWALK": "BulkWalk",
    "BULK_WALK": "BulkWalk",
    "TABLEWALK": "TableWalk",
    "TABLE_WALK": "TableWalk",
    "SET": "Set",
}


def normalize_operation(value: object) -> str:
    key = str(value or "GET").strip().upper().replace(" ", "_").replace("-", "_")
    return _METHOD_ALIASES.get(key, str(value or "Get").strip())


def operation_key(value: object) -> str:
    method = normalize_operation(value)
    return {
        "Get": SnmpOperation.GET.value,
        "GetNext": SnmpOperation.GETNEXT.value,
        "GetBulk": SnmpOperation.GETBULK.value,
        "Walk": SnmpOperation.WALK.value,
        "Set": SnmpOperation.SET.value,
    }.get(method, method.upper())


def profile_to_payload(profile: SnmpProfile) -> dict[str, Any]:
    return {
        "host": profile.host,
        "version": profile.version,
        "port": profile.port,
        "community_ro": profile.community_ro,
        "community_rw": profile.community_rw,
        "username": profile.username,
        "security_level": profile.security_level,
        "auth_protocol": profile.auth_protocol,
        "auth_key": profile.auth_key,
        "priv_protocol": profile.priv_protocol,
        "priv_key": profile.priv_key,
        "context_name": profile.context_name,
        "timeout_ms": profile.timeout_ms,
        "retries": profile.retries,
    }


def build_profile(payload: dict[str, Any]) -> SnmpProfile:
    values = dict(payload or {})
    return SnmpProfile(
        host=str(values.get("host") or values.get("target_host") or values.get("ip") or "").strip(),
        version=str(values.get("version") or values.get("snmp_version") or "v2c"),
        port=_bounded_int(values.get("port") or values.get("target_port"), 161, 1, 65535),
        community_ro=str(values.get("community_ro") or values.get("community") or "public"),
        community_rw=str(values.get("community_rw") or values.get("write_community") or ""),
        username=str(values.get("username") or values.get("v3_username") or ""),
        security_level=str(values.get("security_level") or values.get("v3_security_level") or "noAuthNoPriv"),
        auth_protocol=str(values.get("auth_protocol") or values.get("v3_auth_protocol") or "SHA"),
        auth_key=str(values.get("auth_key") or values.get("auth_password") or values.get("v3_auth_password") or ""),
        priv_protocol=str(values.get("priv_protocol") or values.get("v3_priv_protocol") or "AES128"),
        priv_key=str(values.get("priv_key") or values.get("priv_password") or values.get("v3_priv_password") or ""),
        context_name=str(values.get("context_name") or ""),
        timeout_ms=_bounded_int(values.get("timeout_ms") or values.get("timeout"), 2000, 100, 60000),
        retries=_bounded_int(values.get("retries") if values.get("retries") is not None else values.get("retry"), 1, 0, 10),
    )


def query_request_to_payload(request: SnmpQueryRequest) -> dict[str, Any]:
    return {
        "profile": profile_to_payload(request.profile),
        "method": request.method,
        "oid": request.oid,
        "max_repetitions": request.max_repetitions,
        "non_repeaters": request.non_repeaters,
        "max_rows": request.max_rows,
        "decode": request.decode,
        "save_history": request.save_history,
        "device_id": request.device_id,
        "device_name": request.device_name,
        "object_name": request.object_name,
        "module_name": request.module_name,
        "base_oid": request.base_oid,
        "source": request.source,
        "started_at": request.started_at,
    }


def build_query_request(payload: dict[str, Any]) -> SnmpQueryRequest:
    values = dict(payload.get("request") or payload or {})
    profile_values = dict(values.get("profile") or values.get("security") or values)
    return SnmpQueryRequest(
        profile=build_profile(profile_values),
        method=normalize_operation(values.get("method") or payload.get("operation")),
        oid=str(values.get("oid") or "").strip(),
        max_repetitions=_bounded_int(values.get("max_repetitions"), 10, 1, 50),
        non_repeaters=_bounded_int(values.get("non_repeaters"), 0, 0, 50),
        max_rows=_bounded_int(values.get("max_rows"), 200, 1, 10000),
        decode=bool(values.get("decode", True)),
        save_history=bool(values.get("save_history", True)),
        device_id=str(values.get("device_id") or ""),
        device_name=str(values.get("device_name") or ""),
        object_name=str(values.get("object_name") or ""),
        module_name=str(values.get("module_name") or ""),
        base_oid=str(values.get("base_oid") or ""),
        source=str(values.get("source") or "device"),
        started_at=str(values.get("started_at") or "") or datetime.now().isoformat(timespec="seconds"),
    )


def set_request_to_payload(request: SnmpSetRequest) -> dict[str, Any]:
    return {
        "profile": profile_to_payload(request.profile),
        "oid": request.oid,
        "data_type": request.data_type,
        "value": request.value,
        "device_id": request.device_id,
        "device_name": request.device_name,
        "object_name": request.object_name,
        "module_name": request.module_name,
        "access": request.access,
        "old_value": request.old_value,
        "started_at": request.started_at,
    }


def build_set_request(payload: dict[str, Any]) -> SnmpSetRequest:
    values = dict(payload.get("request") or payload or {})
    profile_values = dict(values.get("profile") or values.get("security") or values)
    return SnmpSetRequest(
        profile=build_profile(profile_values),
        oid=str(values.get("oid") or "").strip(),
        data_type=str(values.get("data_type") or values.get("set_type") or "DisplayString"),
        value=str(values.get("value") if values.get("value") is not None else values.get("set_value") or ""),
        device_id=str(values.get("device_id") or ""),
        device_name=str(values.get("device_name") or ""),
        object_name=str(values.get("object_name") or ""),
        module_name=str(values.get("module_name") or ""),
        access=str(values.get("access") or ""),
        old_value=str(values.get("old_value") or ""),
        started_at=str(values.get("started_at") or "") or datetime.now().isoformat(timespec="seconds"),
    )


def collection_request_to_payload(request: SnmpCollectionRequest) -> dict[str, Any]:
    return {
        "devices": [
            {
                "device_id": target.device_id,
                "device_name": target.device_name,
                "profile": profile_to_payload(target.profile),
            }
            for target in request.devices
        ],
        "oids": list(request.oids),
        "operation": operation_key(request.operation),
        "concurrency": request.concurrency,
        "timeout_ms": request.timeout_ms,
        "retries": request.retries,
        "max_repetitions": request.max_repetitions,
        "non_repeaters": request.non_repeaters,
        "max_rows": request.max_rows,
        "stop_on_failure": request.stop_on_failure,
        "started_at": request.started_at,
    }


def build_collection_request(payload: dict[str, Any]) -> SnmpCollectionRequest:
    values = dict(payload.get("request") or payload or {})
    timeout_ms = _bounded_int(values.get("timeout_ms") or values.get("timeout"), 2000, 100, 60000)
    retries = _bounded_int(values.get("retries") if values.get("retries") is not None else values.get("retry"), 1, 0, 10)
    targets: list[SnmpCollectionTarget] = []
    for item in values.get("devices") or []:
        if not isinstance(item, dict):
            continue
        profile_values = dict(item.get("profile") or item)
        profile_values["timeout_ms"] = timeout_ms
        profile_values["retries"] = retries
        profile = build_profile(profile_values)
        targets.append(
            SnmpCollectionTarget(
                device_id=str(item.get("device_id") or item.get("id") or ""),
                device_name=str(item.get("device_name") or item.get("name") or profile.host),
                profile=profile,
            )
        )
    oids = list(dict.fromkeys(str(oid or "").strip() for oid in values.get("oids") or [] if str(oid or "").strip()))
    return SnmpCollectionRequest(
        devices=targets,
        oids=oids,
        operation=operation_key(values.get("operation") or payload.get("operation") or "GET"),
        concurrency=_bounded_int(values.get("concurrency"), 10, 5, 50),
        timeout_ms=timeout_ms,
        retries=retries,
        max_repetitions=_bounded_int(values.get("max_repetitions"), 10, 1, 50),
        non_repeaters=_bounded_int(values.get("non_repeaters"), 0, 0, 50),
        max_rows=_bounded_int(values.get("max_rows"), 200, 1, 10000),
        stop_on_failure=bool(values.get("stop_on_failure", False)),
        started_at=str(values.get("started_at") or "") or datetime.now().isoformat(timespec="seconds"),
    )


def snmp_cancel_grace_ms(profile: SnmpProfile) -> int:
    request_window = max(100, int(profile.timeout_ms or 2000)) * (max(0, int(profile.retries or 0)) + 1)
    return max(1500, min(10000, request_window + 500))


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value) if value not in {None, ""} else default
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))
