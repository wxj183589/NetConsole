from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
from typing import Any

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import GroundInventorySummaryDTO
from netconsole.models.device import is_device_eligible_for_automatic_collection
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.train_identity import canonical_train_id_for


class TrainInventorySyncService:
    """从设备管理事实源增量维护无人值守绑定和策略。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        repository: GroundUnattendedRepository,
        base_query: RailTransitBaseDataQueryService,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.base_query = base_query

    def collect(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], GroundInventorySummaryDTO, list[str]]:
        """Read the Site device projection without persisting or probing."""
        mrs = self._all_mrs()
        conflicts: list[str] = []
        seen_uuids: set[str] = set()
        device_repository = DeviceRepository(Database(self.paths.site_db_path(self.site_id)))
        grouped: dict[str, dict[str, Any]] = {}
        missing_ip = 0
        missing_credentials = 0
        for mr in mrs:
            role = str(mr.mr_position_code or "").upper()
            if role not in {"CT", "CW"}:
                continue
            identity = canonical_train_id_for(mr.train_no or mr.train_id)
            if not identity:
                continue
            train_id = str(mr.train_id or f"base:{identity}")
            group = grouped.setdefault(
                train_id,
                {
                    "train_id": train_id,
                    "train_no": str(mr.train_no or identity),
                    "train_name": train_id,
                    "endpoints": {},
                },
            )
            mr_uuid = str(mr.id or "")
            if not mr_uuid or mr_uuid in seen_uuids:
                conflicts.append(f"MR_UUID_DUPLICATE: {mr_uuid}")
                continue
            seen_uuids.add(mr_uuid)
            if role in group["endpoints"]:
                conflicts.append(f"MR_POSITION_DUPLICATE: {train_id}/{role}")
                continue
            try:
                device = device_repository.get_by_uuid(str(mr.id))
            except (OSError, sqlite3.Error):
                device = None
            # Heartbeat eligibility belongs to the rail-transit inventory, not
            # SSH credentials. Missing device connection data may block deep
            # collection, but it must not remove an otherwise valid MR target.
            connection_eligible = bool(
                device and is_device_eligible_for_automatic_collection(device)
            )
            connectable = bool(connection_eligible and connection_targets(device))
            if not str(mr.management_ip or "").strip():
                missing_ip += 1
            if not connection_eligible:
                missing_credentials += 1
            backup_strategy = str(
                mr.backup_monitoring_strategy or "MONITOR"
            ).upper()
            if backup_strategy not in {"MONITOR", "FAILOVER_ONLY", "DISABLED"}:
                backup_strategy = "MONITOR"
            group["endpoints"][role] = {
                "device_uuid": str(mr.id),
                "device_id": mr.device_id,
                "train_id": train_id,
                "mr_role": role,
                "device_name": str(mr.name or ""),
                "management_ip": str(mr.management_ip or ""),
                "backup_management_ip": str(device.backup_address or "") if device else "",
                "management_ip_role": "PRIMARY",
                "backup_management_ip_role": "BACKUP",
                "backup_monitoring_strategy": backup_strategy,
                "protocol": str(mr.protocol or ""),
                "port": mr.port,
                # Syslog hostname 以设备 sysname 为准，不能用本地化资产显示名替代。
                "source_hostname": str((device.system_name if device else "") or mr.name or ""),
                "connection_ready": connectable,
            }

        trains = [
            {
                "train_id": row["train_id"],
                "train_no": row["train_no"],
                "train_name": row["train_name"],
            }
            for row in grouped.values()
        ]
        endpoints = [
            endpoint
            for row in grouped.values()
            for endpoint in row["endpoints"].values()
        ]
        complete = sum(set(row["endpoints"]) == {"CT", "CW"} for row in grouped.values())
        ct_only = sum(set(row["endpoints"]) == {"CT"} for row in grouped.values())
        cw_only = sum(set(row["endpoints"]) == {"CW"} for row in grouped.values())
        summary = GroundInventorySummaryDTO(
            site_id=self.site_id,
            discovered_train_count=len(grouped),
            complete_train_count=complete,
            ct_only_count=ct_only,
            cw_only_count=cw_only,
            missing_management_ip_count=missing_ip,
            missing_credential_count=missing_credentials,
            synchronized_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
        )

        return trains, endpoints, summary, sorted(set(conflicts))

    def synchronize(self, *, heartbeat_revision: int | None = None,
                    preview_revision: str = "") -> GroundInventorySummaryDTO:
        trains, endpoints, summary, conflicts = self.collect()
        if conflicts:
            raise ValueError("HEARTBEAT_INVENTORY_CONFLICT: " + "; ".join(conflicts))
        if preview_revision:
            actual = self._preview(trains, endpoints, conflicts)
            revision = hashlib.sha256(f"SYNC:{actual['revision']}".encode("utf-8")).hexdigest()
            if revision != preview_revision:
                raise ValueError("HEARTBEAT_PREVIEW_STALE")
        changes = self.repository.sync_inventory(
            trains=trains, endpoints=endpoints, heartbeat_revision=heartbeat_revision,
        )
        return summary.model_copy(update=changes)

    def preview(self) -> dict[str, Any]:
        trains, endpoints, _, conflicts = self.collect()
        return self._preview(trains, endpoints, conflicts)

    def _preview(self, trains: list[dict[str, Any]], endpoints: list[dict[str, Any]],
                 conflicts: list[str]) -> dict[str, Any]:
        previous_trains = self.repository.list_inventory(include_removed=False)
        previous = {
            str(endpoint["device_uuid"]): endpoint
            for train in previous_trains
            for endpoint in train.get("endpoints", [])
        }
        current = {str(endpoint["device_uuid"]): endpoint for endpoint in endpoints}
        previous_train_names = {
            str(train["train_id"]): (train.get("train_no"), train.get("train_name"))
            for train in previous_trains
        }
        changed_trains = {
            str(train["train_id"]) for train in trains
            if previous_train_names.get(str(train["train_id"])) != (train.get("train_no"), train.get("train_name"))
        }
        fields = ("train_id", "mr_role", "management_ip", "backup_management_ip",
                  "backup_monitoring_strategy", "device_name", "protocol", "port", "source_hostname")
        state = self.repository.heartbeat_inventory_state()
        signature = {
            "site_id": self.site_id, "trains": sorted(trains, key=lambda row: row["train_id"]),
            "endpoints": sorted(endpoints, key=lambda row: row["device_uuid"]),
            "previous": [{field: row.get(field) for field in ("device_uuid", *fields)}
                         for row in sorted(previous.values(), key=lambda row: row["device_uuid"])],
            "previous_trains": previous_train_names,
            "state": state, "conflicts": conflicts,
        }
        return {
            "revision": hashlib.sha256(json.dumps(signature, sort_keys=True, ensure_ascii=False,
                                                   default=str).encode("utf-8")).hexdigest(),
            "added_count": len(current.keys() - previous.keys()) if state["enabled"] else len(current),
            "updated_count": sum(row["train_id"] in changed_trains or any(
                str(row.get(field) or "") != str(previous[key].get(field) or "")
                for field in fields) for key, row in current.items() if key in previous),
            "disabled_count": len(previous.keys() - current.keys()),
            "device_count": len(current), "train_count": len(trains),
            "conflicts": conflicts, "conflict_count": len(conflicts),
        }

    def _all_mrs(self):
        # Reuse the existing identity-only device projection. The general MR
        # page also enriches runtime/quality data and repeats that work for
        # every page; none of it belongs to inventory reconciliation.
        identity_reader = getattr(self.base_query, "list_mesh_import_context_mrs", None)
        if callable(identity_reader):
            return identity_reader(self.site_id)
        first = self.base_query.list_mrs(self.site_id, page=1, page_size=200)
        result = list(first.items)
        page = 2
        while len(result) < first.total:
            batch = self.base_query.list_mrs(self.site_id, page=page, page_size=200)
            if not batch.items:
                break
            result.extend(batch.items)
            page += 1
        return result


__all__ = ["TrainInventorySyncService"]
