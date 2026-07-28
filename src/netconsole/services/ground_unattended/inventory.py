from __future__ import annotations

from datetime import datetime
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

    def synchronize(self) -> GroundInventorySummaryDTO:
        mrs = self._all_mrs()
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
            if role in group["endpoints"]:
                # 设备管理存在重复端位时保留管理 IP 更完整的一条，避免错误覆盖。
                if group["endpoints"][role].get("management_ip"):
                    continue
            try:
                device = device_repository.get_by_uuid(str(mr.id))
            except (OSError, sqlite3.Error):
                device = None
            if device is None or not is_device_eligible_for_automatic_collection(
                device
            ):
                continue
            connectable = bool(device and connection_targets(device))
            if not str(mr.management_ip or "").strip():
                missing_ip += 1
            if not connectable:
                missing_credentials += 1
            group["endpoints"][role] = {
                "device_uuid": str(mr.id),
                "device_id": mr.device_id,
                "train_id": train_id,
                "mr_role": role,
                "device_name": str(mr.name or ""),
                "management_ip": str(mr.management_ip or ""),
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
        changes = self.repository.sync_inventory(trains=trains, endpoints=endpoints)
        complete = sum(set(row["endpoints"]) == {"CT", "CW"} for row in grouped.values())
        ct_only = sum(set(row["endpoints"]) == {"CT"} for row in grouped.values())
        cw_only = sum(set(row["endpoints"]) == {"CW"} for row in grouped.values())
        return GroundInventorySummaryDTO(
            site_id=self.site_id,
            discovered_train_count=len(grouped),
            complete_train_count=complete,
            ct_only_count=ct_only,
            cw_only_count=cw_only,
            missing_management_ip_count=missing_ip,
            missing_credential_count=missing_credentials,
            synchronized_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
            **changes,
        )

    def _all_mrs(self):
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
