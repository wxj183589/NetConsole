from __future__ import annotations

import ipaddress
import json
import subprocess
from dataclasses import dataclass
from typing import Iterable

from netconsole.core.admin import is_admin
from netconsole.services.windows_network_manager import NetworkAdapterInfo, RouteInfo, WindowsNetworkManager


@dataclass(frozen=True)
class LocalRouteRow:
    order_index: int
    destination_prefix: str
    destination: str
    prefix_length: int
    netmask: str
    next_hop: str
    interface_index: int
    interface_alias: str
    interface_ip: str
    metric: int
    policy_store: str
    persistent: bool
    source: str
    on_link: bool


def list_local_routes(manager: WindowsNetworkManager | None = None) -> list[LocalRouteRow]:
    manager = manager or WindowsNetworkManager()
    adapters = manager.list_adapters()
    routes = manager.list_routes()
    return normalize_routes(routes, adapters)


def normalize_routes(routes: Iterable[RouteInfo], adapters: Iterable[NetworkAdapterInfo]) -> list[LocalRouteRow]:
    adapter_by_index = {int(adapter.interface_index): adapter for adapter in adapters}
    rows: list[LocalRouteRow] = []
    for route in routes:
        network = ipaddress.IPv4Network(route.destination_prefix, strict=False)
        adapter = adapter_by_index.get(int(route.interface_index))
        next_hop = str(route.next_hop or "")
        on_link = next_hop in {"", "0.0.0.0"}
        rows.append(
            LocalRouteRow(
                order_index=int(route.order_index or 0),
                destination_prefix=str(network),
                destination=str(network.network_address),
                prefix_length=network.prefixlen,
                netmask=str(network.netmask),
                next_hop="在链路上" if on_link else next_hop,
                interface_index=int(route.interface_index),
                interface_alias=route.interface_alias or (adapter.name if adapter else ""),
                interface_ip=", ".join(adapter.ipv4_addresses) if adapter else "",
                metric=int(route.route_metric or 0),
                policy_store=route.policy_store or "",
                persistent=bool(route.persistent) or str(route.policy_store or "").lower() == "persistentstore",
                source=route.source or route.policy_store or "",
                on_link=on_link,
            )
        )
    return sort_route_rows(rows)


def sort_route_rows(rows: Iterable[LocalRouteRow]) -> list[LocalRouteRow]:
    return sorted(rows, key=route_sort_key)


def route_sort_key(route: LocalRouteRow | RouteInfo) -> tuple[int, int, int, str]:
    destination_prefix = str(getattr(route, "destination_prefix", "") or "")
    order_index = int(getattr(route, "order_index", 0) or 0)
    try:
        network = ipaddress.IPv4Network(destination_prefix, strict=False)
        prefix_length = network.prefixlen
        network_value = int(network.network_address)
        network_text = str(network.network_address)
    except ValueError:
        prefix_length = int(getattr(route, "prefix_length", 32) or 32)
        network_value = 2**32 - 1
        network_text = str(getattr(route, "destination", destination_prefix))
    return (network_value, prefix_length, order_index, network_text)


def parse_powershell_routes_json(routes_json: str, interfaces_json: str = "[]", adapters_json: str = "[]") -> list[LocalRouteRow]:
    route_rows = _ensure_list(json.loads(routes_json or "[]"))
    interface_rows = _ensure_list(json.loads(interfaces_json or "[]"))
    adapter_rows = _ensure_list(json.loads(adapters_json or "[]"))
    alias_by_index = {int(row.get("InterfaceIndex") or 0): str(row.get("InterfaceAlias") or row.get("Name") or "") for row in interface_rows + adapter_rows if isinstance(row, dict)}
    ip_by_index = {int(row.get("InterfaceIndex") or 0): str(row.get("IPAddress") or row.get("IPv4Address") or "") for row in interface_rows if isinstance(row, dict)}
    routes = []
    adapters = []
    for fallback_index, row in enumerate(route_rows):
        if not isinstance(row, dict):
            continue
        routes.append(
            RouteInfo(
                destination_prefix=str(row.get("DestinationPrefix") or "0.0.0.0/0"),
                order_index=int(row.get("OrderIndex") if row.get("OrderIndex") is not None else fallback_index),
                next_hop=str(row.get("NextHop") or ""),
                interface_index=int(row.get("InterfaceIndex") or 0),
                interface_alias=alias_by_index.get(int(row.get("InterfaceIndex") or 0), ""),
                route_metric=int(row.get("RouteMetric") or 0),
                policy_store=str(row.get("PolicyStore") or ""),
                persistent="Persistent" in str(row.get("PolicyStore") or ""),
                source=str(row.get("Protocol") or "PowerShell"),
            )
        )
    for index, alias in alias_by_index.items():
        adapters.append(NetworkAdapterInfo(name=alias, interface_index=index, ipv4_addresses=[ip_by_index.get(index, "")] if ip_by_index.get(index) else []))
    return normalize_routes(routes, adapters)


def build_add_route_command(destination: str, gateway: str, *, interface_index: int | None = None, metric: int | None = None, persistent: bool = False) -> str:
    network = _parse_destination(destination)
    ipaddress.IPv4Address(gateway)
    parts = [f"New-NetRoute -DestinationPrefix '{network}'", f"-NextHop '{gateway}'"]
    if interface_index:
        parts.append(f"-InterfaceIndex {int(interface_index)}")
    if metric:
        parts.append(f"-RouteMetric {int(metric)}")
    if persistent:
        parts.append("-PolicyStore PersistentStore")
    return " ".join(parts)


def build_delete_route_command(destination: str, gateway: str = "", *, interface_index: int | None = None) -> str:
    network = _parse_destination(destination)
    parts = [f"Remove-NetRoute -DestinationPrefix '{network}'", "-Confirm:$false"]
    if gateway and gateway != "在链路上":
        ipaddress.IPv4Address(gateway)
        parts.append(f"-NextHop '{gateway}'")
    if interface_index:
        parts.append(f"-InterfaceIndex {int(interface_index)}")
    return " ".join(parts)


def can_modify_routes() -> bool:
    return is_admin()


def execute_powershell(command: str) -> subprocess.CompletedProcess:
    if not is_admin():
        raise PermissionError("需要以管理员身份运行才能修改路由。")
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], capture_output=True, text=True, encoding="utf-8", errors="replace")


def _parse_destination(text: str) -> ipaddress.IPv4Network:
    cleaned = " ".join(text.strip().split())
    if " " in cleaned and "/" not in cleaned:
        address, mask = cleaned.split(" ", 1)
        cleaned = f"{address}/{mask}"
    return ipaddress.IPv4Network(cleaned, strict=False)


def _ensure_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []
