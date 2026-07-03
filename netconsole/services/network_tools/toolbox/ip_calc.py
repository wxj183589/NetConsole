from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TableResult:
    rows: list[dict[str, object]]
    summary: dict[str, object]
    errors: list[str]


def ipv4_calculate(text: str) -> dict[str, object]:
    network = _parse_ipv4_network(text)
    hosts = list(network.hosts())
    first = hosts[0] if hosts else None
    last = hosts[-1] if hosts else None
    note = ""
    if network.prefixlen == 31:
        note = "/31 是点到点特殊网段，两个地址在 P2P 场景都可用。"
    elif network.prefixlen == 32:
        note = "/32 是单主机路由。"
    return {
        "input": text.strip(),
        "network": str(network.network_address),
        "cidr": str(network),
        "broadcast": str(network.broadcast_address),
        "netmask": str(network.netmask),
        "prefix_length": network.prefixlen,
        "wildcard": str(ipaddress.IPv4Address(int(network.hostmask))),
        "total_addresses": network.num_addresses,
        "usable_hosts": len(hosts),
        "first_usable": str(first) if first is not None else "-",
        "last_usable": str(last) if last is not None else "-",
        "ip_type": _ipv4_type(network.network_address),
        "class": _ipv4_class(network.network_address),
        "note": note,
    }


def ipv6_calculate(text: str) -> dict[str, object]:
    network = ipaddress.ip_network(text.strip(), strict=False)
    if network.version != 6:
        raise ValueError("请输入 IPv6 地址/前缀。")
    address = ipaddress.IPv6Interface(text.strip()).ip
    return {
        "input": text.strip(),
        "compressed": address.compressed,
        "exploded": address.exploded,
        "network": str(network.network_address),
        "cidr": str(network),
        "prefix_length": network.prefixlen,
        "start": str(network.network_address),
        "end": str(network.broadcast_address),
        "total_addresses": network.num_addresses,
        "ip_type": _ipv6_type(address),
        "broadcast": "IPv6 无广播地址",
    }


def plan_vlsm(parent_text: str, requests_text: str) -> TableResult:
    parent = _parse_ipv4_network(parent_text)
    errors: list[str] = []
    requests = _parse_vlsm_requests(requests_text, errors)
    if errors:
        return TableResult([], {}, errors)
    sorted_requests = sorted(requests, key=lambda item: item[2], reverse=True)
    cursor = int(parent.network_address)
    end = int(parent.broadcast_address)
    rows: list[dict[str, object]] = []
    for _line_no, name, hosts in sorted_requests:
        needed = hosts + 2
        block_size = 1 << math.ceil(math.log2(needed))
        prefix = 32 - int(math.log2(block_size))
        if cursor % block_size:
            cursor += block_size - (cursor % block_size)
        if cursor + block_size - 1 > end:
            return TableResult([], {}, [f"主网络容量不足，无法分配 {name} 需要的 {hosts} 个主机地址。"])
        subnet = ipaddress.IPv4Network((cursor, prefix))
        rows.append(_ipv4_subnet_row(name, hosts, subnet))
        cursor += block_size
    return TableResult(rows, {"parent": str(parent), "allocated": len(rows)}, [])


def split_subnets(parent_text: str, target_prefix: int, *, page: int = 1, page_size: int = 50) -> TableResult:
    parent = _parse_ipv4_network(parent_text)
    if target_prefix <= parent.prefixlen or target_prefix > 32:
        return TableResult([], {}, ["目标子网前缀必须大于主网络前缀，且不超过 32。"])
    subnets = list(parent.subnets(new_prefix=target_prefix))
    total = len(subnets)
    page_size = max(1, min(int(page_size), 500))
    page = max(1, int(page))
    start = (page - 1) * page_size
    selected = subnets[start : start + page_size]
    rows = [_ipv4_split_row(index + start + 1, subnet) for index, subnet in enumerate(selected)]
    return TableResult(rows, {"total": total, "page": page, "page_size": page_size, "pages": math.ceil(total / page_size)}, [])


def summarize_routes(text: str) -> TableResult:
    errors: list[str] = []
    networks: list[ipaddress.IPv4Network] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            networks.append(_parse_ipv4_network(line))
        except ValueError as exc:
            errors.append(f"第 {line_no} 行错误：{exc}")
    if errors:
        return TableResult([], {}, errors)
    unique = sorted(set(networks), key=lambda item: int(item.network_address))
    collapsed = list(ipaddress.collapse_addresses(unique))
    input_total = sum(item.num_addresses for item in unique)
    output_total = sum(item.num_addresses for item in collapsed)
    rows = [
        {
            "summary": str(network),
            "network": str(network.network_address),
            "prefix": network.prefixlen,
            "netmask": str(network.netmask),
            "wildcard": str(network.hostmask),
            "range": f"{network.network_address} - {network.broadcast_address}",
            "total_addresses": network.num_addresses,
            "full_cover": True,
        }
        for network in collapsed
    ]
    return TableResult(
        rows,
        {
            "input_count": len(networks),
            "unique_count": len(unique),
            "input_total_addresses": input_total,
            "summary_total_addresses": output_total,
            "utilization_percent": round((input_total / output_total * 100) if output_total else 0, 2),
            "wasted_addresses": max(output_total - input_total, 0),
        },
        [],
    )


def wildcard_calculate(text: str) -> TableResult:
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            network = _wildcard_network(line)
            rows.append(
                {
                    "input": line,
                    "network": str(network.network_address),
                    "prefix": network.prefixlen,
                    "netmask": str(network.netmask),
                    "wildcard": str(network.hostmask),
                    "usable_hosts": len(list(network.hosts())),
                }
            )
        except ValueError as exc:
            errors.append(f"第 {line_no} 行错误：{exc}")
    return TableResult(rows, {"count": len(rows)}, errors)


def _parse_vlsm_requests(requests_text: str, errors: list[str]) -> list[tuple[int, str, int]]:
    requests: list[tuple[int, str, int]] = []
    normalized = requests_text.replace("，", ",").replace("、", ",")
    item_pattern = re.compile(r"([^,\s]+)\s*,?\s*(\d+)")
    for line_no, raw in enumerate(normalized.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        matches = list(item_pattern.finditer(line))
        consumed = "".join(match.group(0) for match in matches)
        if not matches or _compact(consumed) != _compact(line):
            errors.append(f"第 {line_no} 行格式应为：名称,主机数")
            continue
        for match in matches:
            name = match.group(1).strip()
            hosts = int(match.group(2))
            if hosts <= 0:
                errors.append(f"第 {line_no} 行主机数必须为正整数")
                continue
            requests.append((line_no, name, hosts))
    return requests


def _parse_ipv4_network(text: str) -> ipaddress.IPv4Network:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        raise ValueError("请输入 IPv4 网络。")
    if " " in cleaned and "/" not in cleaned:
        address, mask = cleaned.split(" ", 1)
        cleaned = f"{address}/{mask}"
    network = ipaddress.ip_network(cleaned, strict=False)
    if network.version != 4:
        raise ValueError("请输入 IPv4 网络。")
    return network


def _wildcard_network(text: str) -> ipaddress.IPv4Network:
    cleaned = " ".join(text.strip().split())
    if cleaned.startswith("/"):
        return _parse_ipv4_network(f"0.0.0.0{cleaned}")
    if _looks_like_netmask(cleaned):
        return _parse_ipv4_network(f"0.0.0.0/{cleaned}")
    return _parse_ipv4_network(cleaned)


def _looks_like_netmask(text: str) -> bool:
    try:
        ipaddress.IPv4Network(f"0.0.0.0/{text}")
        return text.count(".") == 3
    except ValueError:
        return False


def _ipv4_subnet_row(name: str, requested_hosts: int, subnet: ipaddress.IPv4Network) -> dict[str, object]:
    hosts = list(subnet.hosts())
    usable = len(hosts)
    return {
        "name": name,
        "requested_hosts": requested_hosts,
        "prefix": subnet.prefixlen,
        "network": str(subnet.network_address),
        "cidr": str(subnet),
        "netmask": str(subnet.netmask),
        "wildcard": str(subnet.hostmask),
        "first_usable": str(hosts[0]) if hosts else "-",
        "last_usable": str(hosts[-1]) if hosts else "-",
        "broadcast": str(subnet.broadcast_address),
        "usable_hosts": usable,
        "wasted_hosts": max(usable - requested_hosts, 0),
    }


def _ipv4_split_row(index: int, subnet: ipaddress.IPv4Network) -> dict[str, object]:
    hosts = list(subnet.hosts())
    return {
        "index": index,
        "network": str(subnet.network_address),
        "cidr": str(subnet),
        "prefix": subnet.prefixlen,
        "netmask": str(subnet.netmask),
        "wildcard": str(subnet.hostmask),
        "first_usable": str(hosts[0]) if hosts else "-",
        "last_usable": str(hosts[-1]) if hosts else "-",
        "broadcast": str(subnet.broadcast_address),
        "usable_hosts": len(hosts),
    }


def _ipv4_type(address: ipaddress.IPv4Address) -> str:
    if address.is_loopback:
        return "环回"
    if address.is_link_local:
        return "链路本地"
    if address.is_multicast:
        return "组播"
    if address.is_reserved:
        return "保留地址"
    if address.is_private:
        return "私有地址"
    if address.is_global:
        return "公网地址"
    return "未指定"


def _ipv4_class(address: ipaddress.IPv4Address) -> str:
    first = int(str(address).split(".", 1)[0])
    if first <= 127:
        return "A"
    if first <= 191:
        return "B"
    if first <= 223:
        return "C"
    if first <= 239:
        return "D"
    return "E"


def _ipv6_type(address: ipaddress.IPv6Address) -> str:
    if address.is_unspecified:
        return "Unspecified"
    if address.is_loopback:
        return "Loopback"
    if address.is_link_local:
        return "Link-local"
    if address.is_private:
        return "ULA"
    if address.is_multicast:
        return "Multicast"
    if address.is_global:
        return "Global"
    return "Reserved"


def _compact(text: str) -> str:
    return text.replace(",", "").replace(" ", "").replace("\t", "")
