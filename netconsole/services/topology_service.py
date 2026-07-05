from __future__ import annotations

from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository


class TopologyService:
    def __init__(self, device_repository: DeviceRepository, site_repository: SiteSnmpRepository) -> None:
        self.device_repository = device_repository
        self.site_repository = site_repository
        self.fact_repository = DeviceFactRepository(device_repository.database)

    def discover_basic_topology(self) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        devices = self.device_repository.list()
        nodes = [
            {
                "node_id": device.device_uuid or str(device.id),
                "name": device.system_name or device.name,
                "node_type": device.device_type or "未知设备",
                "device_uuid": device.device_uuid or "",
                "address": device.primary_address or "",
            }
            for device in devices
        ]
        by_name = {str(device.system_name or device.name).lower(): device for device in devices}
        edges: list[dict[str, object]] = []
        for device in devices:
            if not device.device_uuid:
                continue
            for neighbor in self.fact_repository.list_lldp_neighbors(device.device_uuid):
                neighbor_name = str(neighbor.get("neighbor_sysname") or "").lower()
                remote = by_name.get(neighbor_name)
                if remote is None:
                    continue
                edges.append(
                    {
                        "source_id": device.device_uuid,
                        "target_id": remote.device_uuid or str(remote.id),
                        "edge_type": "lldp",
                        "local_interface": neighbor.get("local_interface") or "",
                        "remote_interface": neighbor.get("neighbor_interface") or "",
                        "source": "LLDP",
                        "confidence": 90,
                    }
                )
        self.site_repository.upsert_topology_nodes_edges(nodes, edges)
        return nodes, edges

