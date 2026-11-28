from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol
from ipaddress import ip_address

from netconsole.core.ap_identity.normalizers import normalize_mac_key

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.site_identity import current_site_name, validate_site_name
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository


def _address(value: object) -> str | None:
    try:
        return str(ip_address(str(value or "").strip()))
    except ValueError:
        return None


def resolve_lldp_neighbors(
    rows: Iterable[dict[str, object | None]], devices: Iterable[Device], local_uuid: str,
) -> list[dict[str, object | None]]:
    by_uuid = {str(device.device_uuid): device for device in devices if device.device_uuid}
    by_mac: dict[str, set[str]] = {}
    by_address: dict[str, set[str]] = {}
    for uuid, device in by_uuid.items():
        if mac := normalize_mac_key(device.mac_address):
            by_mac.setdefault(mac, set()).add(uuid)
        for value in (device.primary_address, device.backup_address):
            if address := _address(value):
                by_address.setdefault(address, set()).add(uuid)
    results = []
    for row in rows:
        recorded = str(row.get("neighbor_device_uuid") or "").strip()
        mac = normalize_mac_key(row.get("neighbor_mac"))
        address = _address(row.get("neighbor_ip"))
        candidates = by_mac.get(mac or "", set()) | by_address.get(address or "", set())
        if recorded in by_uuid and recorded != local_uuid:
            uuid, source = recorded, "recorded_uuid"
        elif len(candidates) == 1 and local_uuid not in candidates:
            uuid, = candidates
            source = "mac" if mac and uuid in by_mac.get(mac, set()) else "management_address"
        else:
            uuid, source = None, "ambiguous" if len(candidates) > 1 else ""
        results.append({**row, "neighbor_device_uuid": uuid, "association_source": source})
    return results


class DeviceDetailDataGateway(Protocol):
    def current_site_id(self) -> str: ...

    def get_device(self, device_uuid: str) -> Device | None: ...

    def get_fact(self, device_uuid: str) -> dict[str, object | None] | None: ...

    def get_group_name(self, group_id: int) -> str | None: ...

    def snapshot_source(
        self, device_uuid: str, dataset: str
    ) -> dict[str, object | None] | None: ...

    def snapshot_counts(self, device_uuid: str) -> dict[str, int]: ...

    def list_interfaces(
        self,
        device_uuid: str,
        *,
        search: str,
        status: str | Iterable[str],
        interface_type: str | Iterable[str],
        admin_status: str | Iterable[str],
        physical_status: str | Iterable[str],
        protocol_status: str | Iterable[str],
        media_type: str | Iterable[str],
        sort_by: str,
        sort_order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object | None]], int]: ...

    def get_interface(
        self, device_uuid: str, interface_name: str
    ) -> dict[str, object | None] | None: ...

    def list_transceivers(
        self,
        device_uuid: str,
        *,
        search: str,
        sort_by: str,
        sort_order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object | None]], int]: ...

    def list_transceivers_all(
        self,
        device_uuid: str,
        *,
        search: str,
        sort_by: str,
        sort_order: str,
    ) -> list[dict[str, object | None]]: ...

    def get_transceiver(
        self, device_uuid: str, interface_name: str
    ) -> dict[str, object | None] | None: ...

    def list_transceivers_bounded(
        self,
        device_uuid: str,
        *,
        search: str,
        sort_by: str,
        sort_order: str,
        limit: int,
    ) -> tuple[list[dict[str, object | None]], int, bool]: ...

    def list_lldp(
        self,
        device_uuid: str,
        *,
        search: str,
        linked_only: bool,
        sort_by: str,
        sort_order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object | None]], int]: ...

    def list_lldp_for_interface(
        self, device_uuid: str, interface_name: str, *, limit: int
    ) -> tuple[list[dict[str, object | None]], int, bool]: ...

class DeviceDetailRepository:
    """设备详情 SQLite Data Gateway；只读取既有设备与快照表。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_name: str | None = None,
        site_resolver: Callable[[], str] | None = None,
    ) -> None:
        self.paths = paths
        self.site_name = site_name
        self.site_resolver = site_resolver

    def current_site_id(self) -> str:
        selected = (
            self.site_resolver()
            if self.site_resolver is not None
            else self.site_name or current_site_name(self.paths)
        )
        return validate_site_name(str(selected or "demo"))

    def get_device(self, device_uuid: str) -> Device | None:
        repositories = self._repositories()
        return repositories[0].get_by_uuid(str(device_uuid or "")) if repositories else None

    def get_fact(self, device_uuid: str) -> dict[str, object | None] | None:
        repositories = self._repositories()
        return repositories[1].get_device_fact(device_uuid) if repositories else None

    def get_group_name(self, group_id: int) -> str | None:
        repositories = self._repositories()
        if repositories is None:
            return None
        try:
            return DeviceGroupRepository(
                repositories[0].database, self.current_site_id()
            ).get(int(group_id)).name
        except KeyError:
            return None

    def snapshot_source(
        self, device_uuid: str, dataset: str
    ) -> dict[str, object | None] | None:
        return self._facts().current_snapshot_source(device_uuid, dataset)

    def snapshot_counts(self, device_uuid: str) -> dict[str, int]:
        repositories = self._repositories()
        if repositories is None:
            return {"interfaces": 0, "transceivers": 0, "lldp_neighbors": 0}
        facts = repositories[1]
        _rows, interface_count = facts.list_device_interfaces_page(
            device_uuid, limit=1
        )
        _rows, transceiver_count = facts.list_optical_modules_page(
            device_uuid, limit=1
        )
        _rows, lldp_count = facts.list_lldp_neighbors_page(device_uuid, limit=1)
        return {
            "interfaces": interface_count,
            "transceivers": transceiver_count,
            "lldp_neighbors": lldp_count,
        }

    def list_interfaces(
        self,
        device_uuid: str,
        *,
        search: str = "",
        status: str | Iterable[str] = "",
        interface_type: str | Iterable[str] = "",
        admin_status: str | Iterable[str] = "",
        physical_status: str | Iterable[str] = "",
        protocol_status: str | Iterable[str] = "",
        media_type: str | Iterable[str] = "",
        sort_by: str = "interface_name",
        sort_order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object | None]], int]:
        facts = self._facts()
        return facts.list_device_interfaces_page(
            device_uuid,
            search=search,
            status=status,
            interface_type=interface_type,
            admin_status=admin_status,
            physical_status=physical_status,
            protocol_status=protocol_status,
            media_type=media_type,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    def get_interface(
        self, device_uuid: str, interface_name: str
    ) -> dict[str, object | None] | None:
        return self._facts().get_device_interface(device_uuid, interface_name)

    def list_transceivers(
        self,
        device_uuid: str,
        *,
        search: str = "",
        sort_by: str = "interface_name",
        sort_order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object | None]], int]:
        return self._facts().list_optical_modules_page(
            device_uuid,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    def list_transceivers_all(
        self,
        device_uuid: str,
        *,
        search: str = "",
        sort_by: str = "interface_name",
        sort_order: str = "asc",
    ) -> list[dict[str, object | None]]:
        return self._facts().list_optical_modules_all(
            device_uuid,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def get_transceiver(
        self, device_uuid: str, interface_name: str
    ) -> dict[str, object | None] | None:
        return self._facts().get_optical_module(device_uuid, interface_name)

    def list_transceivers_bounded(
        self,
        device_uuid: str,
        *,
        search: str = "",
        sort_by: str = "interface_name",
        sort_order: str = "asc",
        limit: int = 1000,
    ) -> tuple[list[dict[str, object | None]], int, bool]:
        return self._facts().list_optical_modules_bounded(
            device_uuid,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
        )

    def list_lldp(
        self,
        device_uuid: str,
        *,
        search: str = "",
        linked_only: bool = False,
        sort_by: str = "local_interface",
        sort_order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object | None]], int]:
        repositories = self._repositories()
        if repositories is None:
            raise KeyError("设备数据库不存在")
        devices, facts = repositories
        inventory = devices.list()
        rows, total = facts.list_lldp_neighbors_page(
            device_uuid,
            search=search,
            linked_only=False,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=0 if linked_only else offset,
        )
        if not linked_only:
            return resolve_lldp_neighbors(rows, inventory, device_uuid), total
        matches: list[dict[str, object | None]] = []
        matched_total = 0
        for batch_offset in range(0, total, limit):
            if batch_offset:
                rows, _ = facts.list_lldp_neighbors_page(
                    device_uuid, search=search, sort_by=sort_by, sort_order=sort_order,
                    limit=limit, offset=batch_offset,
                )
            for row in resolve_lldp_neighbors(rows, inventory, device_uuid):
                if row["neighbor_device_uuid"]:
                    if offset <= matched_total < offset + limit:
                        matches.append(row)
                    matched_total += 1
        return matches, matched_total

    def list_lldp_for_interface(
        self, device_uuid: str, interface_name: str, *, limit: int = 200
    ) -> tuple[list[dict[str, object | None]], int, bool]:
        repositories = self._repositories()
        if repositories is None:
            raise KeyError("设备数据库不存在")
        devices, facts = repositories
        rows, total, truncated = facts.list_lldp_neighbors_for_interface(
            device_uuid, interface_name, limit=limit
        )
        return resolve_lldp_neighbors(rows, devices.list(), device_uuid), total, truncated

    def _repositories(
        self,
    ) -> tuple[DeviceRepository, DeviceFactRepository] | None:
        path = self.paths.site_db_path(self.current_site_id())
        if not path.is_file():
            return None
        database = Database(path)
        return DeviceRepository(database), DeviceFactRepository(database)

    def _facts(self) -> DeviceFactRepository:
        repositories = self._repositories()
        if repositories is None:
            raise KeyError("设备数据库不存在")
        return repositories[1]


__all__ = ["DeviceDetailDataGateway", "DeviceDetailRepository"]
