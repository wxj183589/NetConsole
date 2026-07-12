from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.models.snmp_models import SnmpCollectionResult, SnmpQueryResult
from netconsole.services.snmp.result_formatter import collection_result_to_payload


class SnmpQueryResultCache:
    def __init__(self, paths: PathResolver) -> None:
        self.cache_dir = paths.runtime_cache_dir / "snmp_query_results"

    def write(self, result: SnmpQueryResult, *, cache_key: str) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{cache_key}.json"
        tmp_path = path.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
            return path
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise


class SnmpCollectionResultCache:
    def __init__(self, paths: PathResolver) -> None:
        self.cache_dir = paths.runtime_cache_dir / "snmp_collection_results"

    def write(self, result: SnmpCollectionResult, *, cache_key: str) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{cache_key}.json"
        tmp_path = path.with_suffix(".json.tmp")
        payload = collection_result_to_payload(result, include_rows=True)
        payload["records"] = _collection_records(payload)
        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
            return path
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise


def _collection_records(payload: dict[str, object]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for device in payload.get("devices") or []:
        if not isinstance(device, dict):
            continue
        for item in device.get("items") or []:
            if not isinstance(item, dict):
                continue
            rows = [row for row in item.get("rows") or [] if isinstance(row, dict)] or [{}]
            for row in rows:
                row_status = str(row.get("status") or item.get("status") or "failed")
                records.append(
                    {
                        "device_id": str(device.get("device_id") or ""),
                        "device_name": str(device.get("device_name") or ""),
                        "host": str(device.get("host") or ""),
                        "oid": str(row.get("oid") or item.get("oid") or ""),
                        "value": row.get("value"),
                        "type": str(row.get("type") or ""),
                        "timestamp": str(item.get("timestamp") or payload.get("completed_at") or ""),
                        "success": bool(item.get("success")) and row_status == "success",
                        "status": row_status,
                        "error": str(row.get("error") or item.get("error") or ""),
                    }
                )
    return records
