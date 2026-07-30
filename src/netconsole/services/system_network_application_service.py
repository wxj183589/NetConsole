from __future__ import annotations

import ctypes
import ipaddress
import socket
import struct
import sys
from collections import Counter
from datetime import datetime
from typing import Protocol

from netconsole.models.api.system_network import (
    LocalIpv4AddressDTO,
    LocalIpv4AddressPageDTO,
    SourceIpRecommendationDTO,
    SourceIpRecommendationRequestDTO,
    SourceIpRouteDTO,
    UdpPortCheckDTO,
    UdpPortCheckRequestDTO,
)


class SystemNetworkError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NetworkAddressProvider(Protocol):
    def list_ipv4_addresses(self) -> list[LocalIpv4AddressDTO]: ...

    def route_source_ip(self, target_ip: str) -> str: ...


class SystemNetworkAddressProvider:
    """通过 Windows IP Helper 与系统 UDP 选路读取本机网络状态。"""

    def list_ipv4_addresses(self) -> list[LocalIpv4AddressDTO]:
        if sys.platform == "win32":
            return _windows_ipv4_addresses()
        return _portable_ipv4_addresses()

    @staticmethod
    def route_source_ip(target_ip: str) -> str:
        target = _ipv4(target_ip, field_name="目标地址")
        if not _is_unicast(target):
            raise SystemNetworkError("NETWORK_TARGET_INVALID", "目标地址必须是单播 IPv4")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # UDP connect 只查询系统路由，不发送报文。
            sock.connect((str(target), 9))
            return str(sock.getsockname()[0])
        except OSError as exc:
            raise SystemNetworkError(
                "NETWORK_ROUTE_UNAVAILABLE",
                "系统无法确定到目标地址的源 IPv4",
                status_code=409,
            ) from exc
        finally:
            sock.close()


class SystemNetworkApplicationService:
    def __init__(self, provider: NetworkAddressProvider | None = None) -> None:
        self.provider = provider or SystemNetworkAddressProvider()

    def list_ipv4_addresses(
        self,
        *,
        include_loopback: bool = False,
        include_apipa: bool = False,
        include_down: bool = False,
    ) -> LocalIpv4AddressPageDTO:
        rows = self.provider.list_ipv4_addresses()
        items = [
            row
            for row in rows
            if (include_loopback or not row.is_loopback)
            and (include_apipa or not row.is_apipa)
            and (include_down or row.is_up)
        ]
        items.sort(
            key=lambda row: (
                not row.is_up,
                row.is_virtual,
                not row.has_default_route,
                row.route_metric if row.route_metric is not None else 2**31,
                row.adapter_name.casefold(),
                ipaddress.ip_address(row.ipv4),
            )
        )
        return LocalIpv4AddressPageDTO(
            items=items,
            total=len(items),
            generated_at=_now(),
        )

    def recommend_source_ip(
        self, request: SourceIpRecommendationRequestDTO
    ) -> SourceIpRecommendationDTO:
        candidates = self.list_ipv4_addresses().items
        local = {row.ipv4: row for row in candidates}
        routes: list[SourceIpRouteDTO] = []
        selected: list[str] = []
        for raw in dict.fromkeys(value.strip() for value in request.target_ips if value.strip()):
            try:
                target = _ipv4(raw, field_name="目标地址")
                if not _is_unicast(target):
                    raise SystemNetworkError(
                        "NETWORK_TARGET_INVALID", "目标地址必须是单播 IPv4"
                    )
                source_ip = self.provider.route_source_ip(str(target))
                reachable = source_ip in local
                routes.append(
                    SourceIpRouteDTO(
                        target_ip=str(target),
                        source_ip=source_ip,
                        reachable=reachable,
                        reason=(
                            "系统路由选择了该本机地址"
                            if reachable
                            else "系统返回的源地址不在当前可用本机地址列表中"
                        ),
                    )
                )
                if reachable:
                    selected.append(source_ip)
            except SystemNetworkError as exc:
                routes.append(
                    SourceIpRouteDTO(
                        target_ip=raw,
                        reachable=False,
                        reason=exc.message,
                    )
                )

        recommended_ip = ""
        reason = "没有可靠的系统选路结果，请从可用本机地址中手动选择"
        if selected:
            counts = Counter(selected)
            top_count = max(counts.values())
            top = {value for value, count in counts.items() if count == top_count}
            preferred = request.preferred_ip.strip()
            if preferred in top:
                recommended_ip = preferred
                reason = f"已保存地址仍有效，并被 {top_count} 个目标的系统路由选中"
            else:
                recommended_ip = min(
                    top,
                    key=lambda value: (
                        local[value].route_metric
                        if local[value].route_metric is not None
                        else 2**31,
                        ipaddress.ip_address(value),
                    ),
                )
                reason = f"{top_count} 个目标的系统路由共同选择该源地址"
        marked = [
            row.model_copy(
                update={
                    "recommended": row.ipv4 == recommended_ip,
                    "recommendation_reason": reason
                    if row.ipv4 == recommended_ip
                    else "",
                }
            )
            for row in candidates
        ]
        return SourceIpRecommendationDTO(
            recommended_ip=recommended_ip,
            recommendation_reason=reason,
            routes=routes,
            candidates=marked,
            generated_at=_now(),
        )

    def check_udp_port(self, request: UdpPortCheckRequestDTO) -> UdpPortCheckDTO:
        host = str(_ipv4(request.listen_host, field_name="监听地址"))
        if host != "0.0.0.0":
            self.validate_listen_host(host)
        if sys.platform == "win32":
            return self.inspect_udp_port(host, request.listen_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((host, request.listen_port))
            available = True
            status = "AVAILABLE"
            message = "UDP 端口空闲"
        except OSError:
            available = False
            status = "IN_USE"
            message = "UDP 端口已被占用或当前无权绑定"
        finally:
            sock.close()
        return UdpPortCheckDTO(
            listen_host=host,
            listen_port=request.listen_port,
            available=available,
            status=status,
            message=message,
            checked_at=_now(),
        )

    def inspect_udp_port(self, listen_host: str, listen_port: int) -> UdpPortCheckDTO:
        """只读检查 Windows UDP endpoint 表，不临时绑定被检测端口。"""

        host = str(_ipv4(listen_host, field_name="监听地址"))
        if host != "0.0.0.0":
            self.validate_listen_host(host)
        if not 1 <= int(listen_port) <= 65_535:
            raise SystemNetworkError("NETWORK_PORT_INVALID", "UDP 监听端口无效")
        if sys.platform != "win32":
            return self.check_udp_port(
                UdpPortCheckRequestDTO(
                    listen_host=host,
                    listen_port=int(listen_port),
                )
            )
        endpoints = _windows_udp_endpoints()
        occupied = any(
            port == int(listen_port)
            and (
                host == "0.0.0.0"
                or address == "0.0.0.0"
                or address == host
            )
            for address, port, _pid in endpoints
        )
        return UdpPortCheckDTO(
            listen_host=host,
            listen_port=int(listen_port),
            available=not occupied,
            status="IN_USE" if occupied else "AVAILABLE",
            message="UDP 端口已被占用" if occupied else "UDP 端口空闲",
            checked_at=_now(),
        )

    def validate_listen_host(self, value: str) -> None:
        address = _ipv4(value, field_name="本机监听地址")
        if address.is_unspecified:
            return
        if str(address) not in self._local_ipv4_values(include_down=True):
            raise SystemNetworkError(
                "UDP_LISTEN_HOST_NOT_LOCAL",
                "本机监听地址已不属于当前计算机，请刷新地址列表后重新选择",
                status_code=409,
            )

    def validate_syslog_server_ip(
        self,
        value: str,
        *,
        required: bool,
        allow_external: bool,
    ) -> None:
        text = str(value or "").strip()
        if not text:
            if required:
                raise SystemNetworkError(
                    "SYSLOG_TARGET_REQUIRED",
                    "启用无人值守或执行配置检查前，必须选择具体的 MR 日志回传地址",
                    status_code=409,
                )
            return
        address = _ipv4(text, field_name="MR 日志回传地址")
        if not _is_unicast(address):
            raise SystemNetworkError(
                "SYSLOG_TARGET_INVALID",
                "MR 日志回传地址不能是任意、回环、组播或广播地址",
            )
        local_rows = self.provider.list_ipv4_addresses()
        local_values = {row.ipv4 for row in local_rows}
        broadcasts = {
            str(
                ipaddress.ip_network(
                    f"{row.ipv4}/{row.prefix_length}", strict=False
                ).broadcast_address
            )
            for row in local_rows
            if 0 <= row.prefix_length < 32
        }
        if str(address) in broadcasts:
            raise SystemNetworkError(
                "SYSLOG_TARGET_BROADCAST",
                "MR 日志回传地址不能是本机网络的广播地址",
            )
        if str(address) not in local_values and not allow_external:
            raise SystemNetworkError(
                "SYSLOG_TARGET_NOT_LOCAL",
                "MR 日志回传地址已不属于当前计算机；如确为外部 NAT 地址，请启用高级选项并再次确认",
                status_code=409,
            )

    def validate_profile_addresses(
        self,
        *,
        udp_listen_host: str,
        syslog_server_ip: str,
        require_syslog: bool,
        allow_external: bool,
    ) -> None:
        self.validate_listen_host(udp_listen_host)
        self.validate_syslog_server_ip(
            syslog_server_ip,
            required=require_syslog,
            allow_external=allow_external,
        )

    def is_local_ipv4(self, value: str) -> bool:
        try:
            address = str(_ipv4(value, field_name="地址"))
        except SystemNetworkError:
            return False
        return address in self._local_ipv4_values(include_down=True)

    def _local_ipv4_values(self, *, include_down: bool) -> set[str]:
        return {
            row.ipv4
            for row in self.provider.list_ipv4_addresses()
            if include_down or row.is_up
        }


def _ipv4(value: str, *, field_name: str) -> ipaddress.IPv4Address:
    try:
        parsed = ipaddress.ip_address(str(value or "").strip())
    except ValueError as exc:
        raise SystemNetworkError(
            "NETWORK_IPV4_INVALID", f"{field_name}必须是 IPv4 地址"
        ) from exc
    if not isinstance(parsed, ipaddress.IPv4Address):
        raise SystemNetworkError(
            "NETWORK_IPV4_INVALID", f"{field_name}必须是 IPv4 地址"
        )
    return parsed


def _is_unicast(value: ipaddress.IPv4Address) -> bool:
    return not (
        value.is_unspecified
        or value.is_loopback
        or value.is_multicast
        or value == ipaddress.IPv4Address("255.255.255.255")
    )


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _portable_ipv4_addresses() -> list[LocalIpv4AddressDTO]:
    values: set[str] = set()
    try:
        values.update(
            item[4][0]
            for item in socket.getaddrinfo(
                socket.gethostname(), None, family=socket.AF_INET
            )
        )
    except OSError:
        pass
    values.add("127.0.0.1")
    return [
        LocalIpv4AddressDTO(
            adapter_id="portable",
            adapter_name="本机",
            interface_index=0,
            ipv4=value,
            prefix_length=8 if value.startswith("127.") else 32,
            netmask="255.0.0.0" if value.startswith("127.") else "255.255.255.255",
            is_up=True,
            is_loopback=ipaddress.ip_address(value).is_loopback,
            is_apipa=ipaddress.ip_address(value).is_link_local,
            source="python_socket",
        )
        for value in sorted(values, key=ipaddress.ip_address)
    ]


def _windows_ipv4_addresses() -> list[LocalIpv4AddressDTO]:
    from ctypes import wintypes

    class Sockaddr(ctypes.Structure):
        _fields_ = [("sa_family", wintypes.USHORT), ("sa_data", ctypes.c_byte * 14)]

    class SocketAddress(ctypes.Structure):
        _fields_ = [
            ("lp_sockaddr", ctypes.POINTER(Sockaddr)),
            ("sockaddr_length", ctypes.c_int),
        ]

    class UnicastAddress(ctypes.Structure):
        pass

    UnicastAddress._fields_ = [
        ("length", wintypes.ULONG),
        ("flags", wintypes.DWORD),
        ("next", ctypes.POINTER(UnicastAddress)),
        ("address", SocketAddress),
        ("prefix_origin", ctypes.c_int),
        ("suffix_origin", ctypes.c_int),
        ("dad_state", ctypes.c_int),
        ("valid_lifetime", wintypes.ULONG),
        ("preferred_lifetime", wintypes.ULONG),
        ("lease_lifetime", wintypes.ULONG),
        ("on_link_prefix_length", ctypes.c_ubyte),
    ]

    class GatewayAddress(ctypes.Structure):
        pass

    GatewayAddress._fields_ = [
        ("length", wintypes.ULONG),
        ("reserved", wintypes.DWORD),
        ("next", ctypes.POINTER(GatewayAddress)),
        ("address", SocketAddress),
    ]

    class AdapterAddresses(ctypes.Structure):
        pass

    AdapterAddresses._fields_ = [
        ("length", wintypes.ULONG),
        ("if_index", wintypes.DWORD),
        ("next", ctypes.POINTER(AdapterAddresses)),
        ("adapter_name", ctypes.c_char_p),
        ("first_unicast_address", ctypes.POINTER(UnicastAddress)),
        ("first_anycast_address", ctypes.c_void_p),
        ("first_multicast_address", ctypes.c_void_p),
        ("first_dns_server_address", ctypes.c_void_p),
        ("dns_suffix", wintypes.LPWSTR),
        ("description", wintypes.LPWSTR),
        ("friendly_name", wintypes.LPWSTR),
        ("physical_address", ctypes.c_ubyte * 8),
        ("physical_address_length", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("mtu", wintypes.DWORD),
        ("if_type", wintypes.DWORD),
        ("oper_status", ctypes.c_int),
        ("ipv6_if_index", wintypes.DWORD),
        ("zone_indices", wintypes.DWORD * 16),
        ("first_prefix", ctypes.c_void_p),
        ("transmit_link_speed", ctypes.c_ulonglong),
        ("receive_link_speed", ctypes.c_ulonglong),
        ("first_wins_server_address", ctypes.c_void_p),
        ("first_gateway_address", ctypes.POINTER(GatewayAddress)),
        ("ipv4_metric", wintypes.ULONG),
    ]

    function = ctypes.windll.iphlpapi.GetAdaptersAddresses
    function.argtypes = [
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        ctypes.POINTER(AdapterAddresses),
        ctypes.POINTER(wintypes.ULONG),
    ]
    function.restype = wintypes.ULONG
    size = wintypes.ULONG(15_000)
    buffer = ctypes.create_string_buffer(size.value)
    flags = 0x0002 | 0x0004 | 0x0008 | 0x0010 | 0x0080
    result = function(
        socket.AF_INET,
        flags,
        None,
        ctypes.cast(buffer, ctypes.POINTER(AdapterAddresses)),
        ctypes.byref(size),
    )
    if result == 111:
        buffer = ctypes.create_string_buffer(size.value)
        result = function(
            socket.AF_INET,
            flags,
            None,
            ctypes.cast(buffer, ctypes.POINTER(AdapterAddresses)),
            ctypes.byref(size),
        )
    if result != 0:
        raise SystemNetworkError(
            "NETWORK_ENUMERATION_FAILED",
            f"Windows IP Helper 无法枚举本机地址（错误码 {result}）",
            status_code=503,
        )

    rows: list[LocalIpv4AddressDTO] = []
    current = ctypes.cast(buffer, ctypes.POINTER(AdapterAddresses))
    while current:
        adapter = current.contents
        gateway = ""
        gateway_ptr = adapter.first_gateway_address
        while gateway_ptr:
            gateway = _socket_address_ipv4(gateway_ptr.contents.address) or gateway
            gateway_ptr = gateway_ptr.contents.next
        name = adapter.friendly_name or ""
        description = adapter.description or ""
        identity = (
            adapter.adapter_name.decode("ascii", errors="replace")
            if adapter.adapter_name
            else name
        )
        virtual = _is_virtual_adapter(
            name=name,
            description=description,
            if_type=int(adapter.if_type),
        )
        unicast = adapter.first_unicast_address
        while unicast:
            item = unicast.contents
            address = _socket_address_ipv4(item.address)
            if address:
                parsed = ipaddress.ip_address(address)
                prefix = int(item.on_link_prefix_length)
                rows.append(
                    LocalIpv4AddressDTO(
                        adapter_id=identity,
                        adapter_name=name or description or identity,
                        description=description,
                        interface_index=int(adapter.if_index),
                        ipv4=address,
                        prefix_length=prefix,
                        netmask=str(
                            ipaddress.ip_network(
                                f"0.0.0.0/{prefix}", strict=False
                            ).netmask
                        ),
                        gateway=gateway,
                        is_up=int(adapter.oper_status) == 1,
                        is_loopback=parsed.is_loopback or int(adapter.if_type) == 24,
                        is_virtual=virtual,
                        is_apipa=parsed.is_link_local,
                        has_default_route=bool(gateway),
                        route_metric=int(adapter.ipv4_metric),
                        source="windows_ip_helper_api",
                    )
                )
            unicast = item.next
        current = adapter.next
    return rows


def _windows_udp_endpoints() -> list[tuple[str, int, int]]:
    from ctypes import wintypes

    class UdpRowOwnerPid(ctypes.Structure):
        _fields_ = [
            ("local_address", wintypes.DWORD),
            ("local_port", wintypes.DWORD),
            ("owning_pid", wintypes.DWORD),
        ]

    function = ctypes.windll.iphlpapi.GetExtendedUdpTable
    function.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.ULONG),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    function.restype = wintypes.DWORD
    size = wintypes.ULONG(0)
    result = function(None, ctypes.byref(size), False, socket.AF_INET, 1, 0)
    if result not in {0, 122}:
        raise SystemNetworkError(
            "UDP_ENDPOINT_ENUMERATION_FAILED",
            f"Windows IP Helper 无法读取 UDP endpoint（错误码 {result}）",
            status_code=503,
        )
    buffer = ctypes.create_string_buffer(max(4, int(size.value)))
    result = function(
        buffer,
        ctypes.byref(size),
        False,
        socket.AF_INET,
        1,
        0,
    )
    if result != 0:
        raise SystemNetworkError(
            "UDP_ENDPOINT_ENUMERATION_FAILED",
            f"Windows IP Helper 无法读取 UDP endpoint（错误码 {result}）",
            status_code=503,
        )
    count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
    base = ctypes.addressof(buffer) + ctypes.sizeof(wintypes.DWORD)
    row_size = ctypes.sizeof(UdpRowOwnerPid)
    endpoints: list[tuple[str, int, int]] = []
    for index in range(int(count)):
        row = UdpRowOwnerPid.from_address(base + index * row_size)
        address = socket.inet_ntoa(struct.pack("<I", int(row.local_address)))
        port = socket.ntohs(int(row.local_port) & 0xFFFF)
        endpoints.append((address, port, int(row.owning_pid)))
    return endpoints


def _socket_address_ipv4(address: object) -> str:
    pointer = getattr(address, "lp_sockaddr", None)
    if not pointer or int(pointer.contents.sa_family) != socket.AF_INET:
        return ""
    base = ctypes.addressof(pointer.contents)
    raw = bytes((ctypes.c_ubyte * 4).from_address(base + 4))
    return socket.inet_ntoa(raw)


def _is_virtual_adapter(*, name: str, description: str, if_type: int) -> bool:
    text = f"{name} {description}".casefold()
    tokens = (
        "virtual",
        "vmware",
        "hyper-v",
        "vethernet",
        "wsl",
        "docker",
        "loopback",
        "tap-",
        "tun-",
        "vpn",
    )
    return if_type in {24, 53, 131} or any(token in text for token in tokens)


__all__ = [
    "NetworkAddressProvider",
    "SystemNetworkAddressProvider",
    "SystemNetworkApplicationService",
    "SystemNetworkError",
]
