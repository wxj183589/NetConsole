from __future__ import annotations

import base64
import html
import ipaddress
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from netconsole.core.admin import is_admin


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]

VIRTUAL_ADAPTER_KEYWORDS = (
    "vpn",
    "virtual",
    "vmware",
    "virtualbox",
    "hyper-v",
    "bluetooth",
    "wi-fi",
    "wifi",
    "wireless",
    "wlan",
    "tap",
    "tun",
    "wireguard",
    "zerotier",
    "tailscale",
    "loopback",
    "wan miniport",
)

VLAN_PROPERTY_KEYWORDS = (
    "vlan id",
    "vlanid",
    "vlan",
    "802.1q",
    "priority & vlan",
    "packet priority & vlan",
)

VLAN_ID_PROPERTY_KEYWORDS = (
    "vlan id",
    "vlanid",
    "vlan identifier",
    "802.1q vlan id",
    "vlan标识",
)

PRIORITY_VLAN_PROPERTY_KEYWORDS = (
    "packet priority & vlan",
    "priority & vlan",
    "packet priority",
)


@dataclass(frozen=True)
class VlanProperty:
    display_name: str
    registry_keyword: str = ""
    display_value: str = ""
    registry_value: str = ""
    valid_display_values: list[str] = field(default_factory=list)
    mode: str = "vlan_id_numeric"
    write_strategy: str = "display_numeric"


@dataclass(frozen=True)
class VlanCapability:
    supported: bool
    can_set_vlan_id: bool = False
    vlan_id_property: str | None = None
    vlan_switch_property: str | None = None
    vlan_id_property_name: str | None = None
    vlan_id_registry_keyword: str | None = None
    vlan_id_registry_value: str = ""
    vlan_id_display_value: str = ""
    priority_vlan_property_name: str | None = None
    valid_display_values: list[str] = field(default_factory=list)
    mode: str = "unsupported"
    message: str = ""


@dataclass(frozen=True)
class NetworkAdapterInfo:
    name: str
    interface_index: int = 0
    description: str = ""
    mac_address: str = ""
    status: str = ""
    link_speed: str = ""
    media_type: str = ""
    ndis_physical_medium: str = ""
    pnp_device_id: str = ""
    hardware_interface: bool = False
    ipv4_addresses: list[str] = field(default_factory=list)
    gateways: list[str] = field(default_factory=list)
    dns_servers: list[str] = field(default_factory=list)
    dhcp_enabled: bool | None = None
    vlan_property: VlanProperty | None = None
    score: int = 0
    tags: list[str] = field(default_factory=list)
    excluded: bool = False
    exclude_reason: str = ""

    @property
    def vlan_supported(self) -> bool:
        return self.vlan_property is not None


@dataclass(frozen=True)
class SecondaryIpConfig:
    ip_address: str
    prefix_length: int


@dataclass(frozen=True)
class AdapterIpConfig:
    interface_index: int
    mode: str
    ip_address: str = ""
    prefix_length: int = 24
    gateway: str = ""
    dns_servers: list[str] = field(default_factory=list)
    secondary_ips: list[SecondaryIpConfig] = field(default_factory=list)


@dataclass(frozen=True)
class RouteConfig:
    destination_prefix: str
    next_hop: str
    interface_alias: str
    metric: int = 10
    persistent: bool = True
    interface_index: int = 0


@dataclass(frozen=True)
class RouteInfo:
    destination_prefix: str
    order_index: int = 0
    next_hop: str = ""
    interface_index: int = 0
    interface_alias: str = ""
    route_metric: int = 0
    policy_store: str = ""
    persistent: bool = False
    source: str = "powershell"


class NetworkManagerError(RuntimeError):
    pass


def recommend_physical_adapters(adapters: Sequence[NetworkAdapterInfo]) -> list[NetworkAdapterInfo]:
    scored = [score_adapter(adapter) for adapter in adapters]
    return sorted((adapter for adapter in scored if not adapter.excluded), key=lambda item: item.score, reverse=True)


def score_adapter(adapter: NetworkAdapterInfo) -> NetworkAdapterInfo:
    haystack = " ".join(
        (
            adapter.name,
            adapter.description,
            adapter.media_type,
            adapter.ndis_physical_medium,
            adapter.pnp_device_id,
        )
    ).lower()
    for keyword in VIRTUAL_ADAPTER_KEYWORDS:
        if keyword in haystack:
            return _replace_adapter(adapter, excluded=True, exclude_reason=keyword, score=-1000, tags=["excluded"])

    score = 70
    tags: list[str] = []
    if "usb" in haystack or "usb\\" in haystack:
        score = 140
        tags.append("USB")
    elif "pci" in haystack or "pcie" in haystack or "pci\\" in haystack:
        score = 100
        tags.append("PCI")
    else:
        tags.append("Ethernet")
    if adapter.status.lower() in {"up", "connected"}:
        score += 20
        tags.append("Connected")
    if adapter.ipv4_addresses:
        score += 10
        tags.append("IPv4")
    if adapter.hardware_interface:
        score += 5
        tags.append("Hardware")
    return _replace_adapter(adapter, score=score, tags=tags, excluded=False, exclude_reason="")


def detect_vlan_capability(properties: Sequence[dict]) -> VlanCapability:
    priority_property: str | None = None
    valid_display_values: list[str] = []
    for row in properties:
        name = str(row.get("DisplayName") or row.get("display_name") or "")
        keyword = str(row.get("RegistryKeyword") or row.get("registry_keyword") or "")
        display_value = str(row.get("DisplayValue") or row.get("display_value") or "")
        registry_value = str(row.get("RegistryValue") or row.get("registry_value") or "")
        text = f"{name} {keyword}".lower()
        values = row.get("ValidDisplayValues") or row.get("valid_display_values") or row.get("DisplayValues") or []
        if isinstance(values, str):
            values = [values]
        row_values = [str(item) for item in _ensure_list(values) if str(item).strip()]
        if display_value and display_value not in row_values:
            row_values.append(display_value)
        is_switch_vlan = any(item in text for item in PRIORITY_VLAN_PROPERTY_KEYWORDS) or _looks_like_vlan_switch_values(row_values)
        if any(item in text for item in VLAN_ID_PROPERTY_KEYWORDS) and not is_switch_vlan:
            return VlanCapability(
                supported=True,
                can_set_vlan_id=True,
                vlan_id_property=name or keyword,
                vlan_id_property_name=name or keyword,
                vlan_id_registry_keyword=keyword or None,
                vlan_id_registry_value=registry_value,
                vlan_id_display_value=display_value,
                valid_display_values=row_values,
                mode="vlan_id_numeric",
                message="已检测到可写入 VLAN ID 的网卡高级属性。",
            )
        if is_switch_vlan:
            priority_property = name or keyword
            valid_display_values = row_values
    if priority_property:
        return VlanCapability(
            supported=True,
            can_set_vlan_id=False,
            vlan_switch_property=priority_property,
            priority_vlan_property_name=priority_property,
            valid_display_values=valid_display_values,
            mode="priority_vlan_enum",
            message="该网卡仅检测到 VLAN 开关属性，未检测到可写入 VLAN ID 的属性，不能直接配置 VLAN ID。",
        )
    return VlanCapability(supported=False, mode="unsupported", message="该网卡驱动未检测到 VLAN ID 配置项。")


def detect_vlan_property(properties: Sequence[dict]) -> VlanProperty | None:
    capability = detect_vlan_capability(properties)
    if capability.mode != "vlan_id_numeric" or not capability.vlan_id_property_name:
        return None
    return VlanProperty(
        capability.vlan_id_property_name,
        capability.vlan_id_registry_keyword or "",
        display_value=capability.vlan_id_display_value,
        registry_value=capability.vlan_id_registry_value,
        valid_display_values=capability.valid_display_values,
        mode=capability.mode,
        write_strategy="display_numeric",
    )


class WindowsNetworkManager:
    def __init__(self, runner: Runner | None = None) -> None:
        self.runner = runner or _default_runner

    def list_adapters(self) -> list[NetworkAdapterInfo]:
        try:
            rows = self._run_json(_list_adapters_script())
        except NetworkManagerError:
            rows = _parse_netsh_interfaces(self._run_script("netsh interface show interface").stdout)
        adapters = [_adapter_from_powershell_row(row) for row in _ensure_list(rows)]
        return recommend_physical_adapters(adapters) + [score_adapter(adapter) for adapter in adapters if score_adapter(adapter).excluded]

    def list_routes(self) -> list[RouteInfo]:
        try:
            rows = self._run_json(_list_routes_script())
            return [_route_from_powershell_row(row, index) for index, row in enumerate(_ensure_list(rows))]
        except NetworkManagerError:
            return _parse_route_print(self._run_script("route print -4").stdout)

    def get_vlan_property(self, adapter_name: str) -> VlanProperty | None:
        rows = self._run_json(_get_vlan_properties_script(adapter_name))
        return detect_vlan_property(_ensure_list(rows))

    def get_vlan_capability(self, adapter_name: str) -> VlanCapability:
        rows = self._run_json(_get_vlan_properties_script(adapter_name))
        return detect_vlan_capability(_ensure_list(rows))

    def apply_ip_config(self, config: AdapterIpConfig, *, require_admin: bool = True) -> None:
        _ensure_write_allowed(require_admin)
        self._run_script(build_apply_ip_config_script(config))

    def reset_adapter_defaults(
        self,
        interface_index: int,
        *,
        adapter_name: str = "",
        vlan_property: VlanProperty | None = None,
        require_admin: bool = True,
    ) -> None:
        _ensure_write_allowed(require_admin)
        self._run_script(build_reset_adapter_defaults_script(interface_index, adapter_name=adapter_name, vlan_property=vlan_property))

    def set_vlan_id(self, adapter_name: str, vlan_property: VlanProperty, vlan_id: int, *, require_admin: bool = True) -> None:
        _ensure_write_allowed(require_admin)
        self._run_script(build_set_vlan_script(adapter_name, vlan_property, vlan_id))

    def apply_route(self, route: RouteConfig, *, require_admin: bool = True) -> None:
        _ensure_write_allowed(require_admin)
        self._run_script(build_new_route_script(route))

    def remove_route(self, route: RouteConfig, *, require_admin: bool = True) -> None:
        _ensure_write_allowed(require_admin)
        self._run_script(build_remove_route_script(route))

    def _run_json(self, script: str):
        result = self._run_script(script)
        if not result.stdout.strip():
            return []
        return json.loads(result.stdout)

    def _run_script(self, script: str) -> subprocess.CompletedProcess:
        result = self.runner(_powershell_args(script))
        if result.returncode != 0:
            message = clean_powershell_error_output(result.stderr or result.stdout)
            raise NetworkManagerError(message or "PowerShell command failed")
        return result


def build_apply_ip_config_script(config: AdapterIpConfig) -> str:
    if config.interface_index <= 0:
        raise ValueError("网卡接口索引无效")
    mode = config.mode.lower()
    if mode not in {"dhcp", "static"}:
        raise ValueError("IP配置模式无效")
    lines = [f"$ifIndex = {config.interface_index}"]
    if mode == "dhcp":
        lines.extend(
            [
                "Get-NetIPAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.PrefixOrigin -eq 'Manual' } | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue",
                "Set-NetIPInterface -InterfaceIndex $ifIndex -AddressFamily IPv4 -Dhcp Enabled -ErrorAction Stop",
            ]
        )
        return "\n".join(lines)

    config = AdapterIpConfig(
        interface_index=config.interface_index,
        mode=config.mode,
        ip_address=config.ip_address,
        prefix_length=config.prefix_length,
        gateway=_normalized_gateway(config.gateway),
        dns_servers=[],
        secondary_ips=config.secondary_ips,
    )

    _validate_ip(config.ip_address, "IP地址")
    _validate_prefix(config.prefix_length)
    if config.gateway:
        _validate_ip(config.gateway, "默认网关")
    lines.extend(
        [
            "Set-NetIPInterface -InterfaceIndex $ifIndex -AddressFamily IPv4 -Dhcp Disabled -ErrorAction Stop",
            "Get-NetIPAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.PrefixOrigin -eq 'Manual' } | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue",
        ]
    )
    gateway_arg = f" -DefaultGateway {_ps_quote(config.gateway)}" if config.gateway else ""
    lines.append(f"New-NetIPAddress -InterfaceIndex $ifIndex -IPAddress {_ps_quote(config.ip_address)} -PrefixLength {config.prefix_length}{gateway_arg} -ErrorAction Stop")
    for secondary in config.secondary_ips:
        _validate_ip(secondary.ip_address, "备用IP")
        _validate_prefix(secondary.prefix_length)
        lines.append(
            f"New-NetIPAddress -InterfaceIndex $ifIndex -IPAddress {_ps_quote(secondary.ip_address)} -PrefixLength {secondary.prefix_length} -ErrorAction Stop"
        )
    return "\n".join(lines)


def build_set_vlan_script(adapter_name: str, vlan_property: VlanProperty, vlan_id: int) -> str:
    if not adapter_name.strip():
        raise ValueError("网卡名称不能为空")
    if not vlan_property.display_name.strip():
        raise ValueError("未检测到可写入的VLAN属性")
    if vlan_id < 0 or vlan_id > 4094:
        raise ValueError("VLAN ID必须在0到4094之间")
    if vlan_property.mode != "vlan_id_numeric" or _is_priority_vlan_property(vlan_property.display_name, vlan_property.registry_keyword):
        raise ValueError("VLAN配置失败：当前网卡未检测到可写入 VLAN ID 的高级属性，不能把数字 VLAN ID 写入 Packet Priority & VLAN。")
    return _build_set_vlan_script(adapter_name, vlan_property, vlan_id)


def build_reset_adapter_defaults_script(
    interface_index: int,
    *,
    adapter_name: str = "",
    vlan_property: VlanProperty | None = None,
) -> str:
    if interface_index <= 0:
        raise ValueError("网卡接口索引无效")
    lines = [
        f"$ifIndex = {interface_index}",
        "Get-NetIPAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.PrefixOrigin -eq 'Manual' } | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue",
        "Set-NetIPInterface -InterfaceIndex $ifIndex -AddressFamily IPv4 -Dhcp Enabled -ErrorAction Stop",
    ]
    if adapter_name.strip() and vlan_property is not None:
        lines.append(build_set_vlan_script(adapter_name, vlan_property, 0))
    return "\n".join(lines)


def _build_set_vlan_script(adapter_name: str, vlan_property: VlanProperty, vlan_id: int) -> str:
    display_name = vlan_property.display_name.strip()
    registry_keyword = vlan_property.registry_keyword.strip()
    reset_value = _vlan_zero_display_value(vlan_property)
    value = str(vlan_id)
    if vlan_id == 0 and reset_value:
        value = reset_value
    lines = [
        f"$adapterName = {_ps_quote(adapter_name)}",
        f"$expectedDisplayName = {_ps_quote(display_name)}",
        f"$expectedRegistryKeyword = {_ps_quote(registry_keyword)}",
        f"$targetValue = {_ps_quote(value)}",
        "$properties = Get-NetAdapterAdvancedProperty -Name $adapterName -ErrorAction Stop",
        "$property = $properties | Where-Object {",
        "  ($expectedDisplayName -and $_.DisplayName -eq $expectedDisplayName) -or",
        "  ($expectedRegistryKeyword -and $_.RegistryKeyword -eq $expectedRegistryKeyword)",
        "} | Select-Object -First 1",
        "if (-not $property) { throw 'VLAN配置失败：当前网卡未找到之前检测到的 VLAN 属性，请刷新网卡信息后重试。' }",
    ]
    if vlan_id == 0 and not reset_value and "0" not in {item.strip() for item in vlan_property.valid_display_values}:
        lines.extend(
            [
                "$resetCommand = Get-Command Reset-NetAdapterAdvancedProperty -ErrorAction SilentlyContinue",
                "if ($resetCommand) {",
                "  if ($property.DisplayName) {",
                "    Reset-NetAdapterAdvancedProperty -Name $adapterName -DisplayName $property.DisplayName -NoRestart -ErrorAction Stop",
                "  } elseif ($property.RegistryKeyword) {",
                "    Reset-NetAdapterAdvancedProperty -Name $adapterName -RegistryKeyword $property.RegistryKeyword -NoRestart -ErrorAction Stop",
                "  }",
                "} else {",
                "  Write-Warning 'VLAN属性无法自动恢复默认值，请在网卡高级属性中手动恢复。'",
                "}",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            "$writeError = $null",
            "try {",
            "  Set-NetAdapterAdvancedProperty -Name $adapterName -DisplayName $property.DisplayName -DisplayValue $targetValue -NoRestart -ErrorAction Stop",
            "} catch {",
            "  $writeError = $_",
            "  if ($property.RegistryKeyword) {",
            "    Set-NetAdapterAdvancedProperty -Name $adapterName -RegistryKeyword $property.RegistryKeyword -RegistryValue $targetValue -NoRestart -ErrorAction Stop",
            "  } else {",
            "    throw $writeError",
            "  }",
            "}",
            "$updated = Get-NetAdapterAdvancedProperty -Name $adapterName -ErrorAction Stop | Where-Object {",
            "  ($property.DisplayName -and $_.DisplayName -eq $property.DisplayName) -or",
            "  ($property.RegistryKeyword -and $_.RegistryKeyword -eq $property.RegistryKeyword)",
            "} | Select-Object -First 1",
            "if (-not $updated) { Write-Warning 'VLAN写入命令已执行，但无法从驱动读取确认值。' }",
        ]
    )
    return "\n".join(lines)


def build_new_route_script(route: RouteConfig) -> str:
    _validate_route(route)
    network, mask = route_prefix_to_route_parts(route.destination_prefix)
    persistent_arg = " -p" if route.persistent else ""
    interface_arg = f" if {int(route.interface_index)}" if route.interface_index > 0 else ""
    return f"route.exe{persistent_arg} add {network} mask {mask} {route.next_hop} metric {int(route.metric)}{interface_arg}"


def build_remove_route_script(route: RouteConfig) -> str:
    _validate_route(route)
    network, mask = route_prefix_to_route_parts(route.destination_prefix)
    return f"route.exe delete {network} mask {mask} {route.next_hop}"


def build_open_network_connections_command() -> list[str]:
    return ["control", "ncpa.cpl"]


def build_destination_prefix(destination: str, netmask: str = "") -> str:
    destination_text = str(destination).strip()
    netmask_text = str(netmask).strip()
    if not destination_text:
        raise ValueError("目标网络不能为空。")
    try:
        if "/" in destination_text:
            if netmask_text:
                raise ValueError("目标网络已包含前缀长度时，掩码请留空。")
            return ipaddress.IPv4Network(destination_text, strict=False).with_prefixlen
        prefix = parse_prefix_or_netmask(netmask_text)
        return ipaddress.IPv4Network(f"{destination_text}/{prefix}", strict=False).with_prefixlen
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("目标网络或掩码格式错误。") from exc


def route_prefix_to_route_parts(destination_prefix: str) -> tuple[str, str]:
    try:
        network = ipaddress.IPv4Network(destination_prefix, strict=False)
    except Exception as exc:
        raise ValueError("目标网络或掩码格式错误。") from exc
    return str(network.network_address), str(network.netmask)


def _ensure_write_allowed(require_admin: bool) -> None:
    if require_admin and not is_admin():
        raise PermissionError("该操作需要管理员权限")


def _default_runner(args: Sequence[str]) -> subprocess.CompletedProcess:
    kwargs = _hidden_subprocess_kwargs()
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, **kwargs)


def _hidden_subprocess_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def _powershell_args(script: str) -> list[str]:
    executable = "powershell.exe" if sys.platform == "win32" else "pwsh"
    encoded = base64.b64encode(_with_powershell_utf8(script).encode("utf-16le")).decode("ascii")
    return [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def _with_powershell_utf8(script: str) -> str:
    return (
        "$ProgressPreference = 'SilentlyContinue'\n"
        "$InformationPreference = 'SilentlyContinue'\n"
        "$WarningPreference = 'Continue'\n"
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
        f"{script}"
    )


def is_only_powershell_progress_clixml(stderr: str) -> bool:
    text = (stderr or "").strip()
    if not text.startswith("#< CLIXML"):
        return False
    lower = text.lower()
    has_error_record = any(token.lower() in lower for token in ("categoryinfo", "fullyqualifiederrorid", "exception", "errorrecord"))
    return not has_error_record and ("s=\"progress\"" in lower or "completed" in lower or "progress" in lower)


def clean_powershell_error_output(stderr: str) -> str:
    text = (stderr or "").strip()
    if not text or is_only_powershell_progress_clixml(text):
        return ""
    if text.startswith("#< CLIXML"):
        text = text.replace("#< CLIXML", "", 1)
        text = re.sub(r"_x([0-9A-Fa-f]{4})_", lambda match: chr(int(match.group(1), 16)), text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    useful = [
        line
        for line in lines
        if not line.startswith("#<")
        and "S=\"progress\"" not in line
        and line.lower() not in {"completed", "preparing modules for first use."}
    ]
    message = " ".join(useful or lines).strip()
    message = re.sub(r"\s+", " ", message)
    lower = message.lower()
    if "set-netadapteradvancedproperty" in lower and ("0x80041002" in lower or "objectnotfound" in lower):
        return "VLAN配置失败：网卡驱动返回“属性对象不存在”，检测结果可能已失效，请重新选择网卡并检测 VLAN。"
    if "set-netadapteradvancedproperty" in lower:
        return "VLAN配置失败：当前网卡的 VLAN 属性已被检测到，但驱动不支持使用该属性标识写入。请刷新检测或在网卡高级属性中手动配置。"
    return message[:500]


def _list_adapters_script() -> str:
    return r"""
& {
  $adapters = Get-NetAdapter -ErrorAction Stop
  $configs = Get-NetIPConfiguration -ErrorAction SilentlyContinue
  $items = foreach ($adapter in $adapters) {
    $config = $configs | Where-Object { $_.InterfaceIndex -eq $adapter.InterfaceIndex } | Select-Object -First 1
    $ipIf = Get-NetIPInterface -InterfaceIndex $adapter.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1
    [PSCustomObject]@{
      Name = $adapter.Name
      InterfaceIndex = $adapter.InterfaceIndex
      InterfaceDescription = $adapter.InterfaceDescription
      MacAddress = $adapter.MacAddress
      Status = $adapter.Status
      LinkSpeed = $adapter.LinkSpeed
      MediaType = $adapter.MediaType
      NdisPhysicalMedium = $adapter.NdisPhysicalMedium
      PnPDeviceID = $adapter.PnPDeviceID
      HardwareInterface = $adapter.HardwareInterface
      IPv4Addresses = @($config.IPv4Address | ForEach-Object { $_.IPAddress + "/" + $_.PrefixLength })
      Gateways = @($config.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
      DnsServers = @($config.DNSServer.ServerAddresses)
      DhcpEnabled = if ($ipIf) { $ipIf.Dhcp -eq "Enabled" } else { $null }
    }
  }
  @($items) | ConvertTo-Json -Depth 6
}
"""


def _list_routes_script() -> str:
    return r"""
& {
  $index = 0
  $items = Get-NetRoute -AddressFamily IPv4 -ErrorAction Stop | ForEach-Object {
    [PSCustomObject]@{
      OrderIndex = $index
      DestinationPrefix = $_.DestinationPrefix
      NextHop = $_.NextHop
      InterfaceIndex = $_.InterfaceIndex
      InterfaceAlias = $_.InterfaceAlias
      RouteMetric = $_.RouteMetric
      PolicyStore = $_.PolicyStore
      Persistent = $_.PolicyStore -eq "PersistentStore"
    }
    $index += 1
  }
  @($items) | ConvertTo-Json -Depth 6
}
"""


def _get_vlan_properties_script(adapter_name: str) -> str:
    return (
        "& {\n"
        "  $command = Get-Command Get-NetAdapterAdvancedProperty -ErrorAction Stop\n"
        "  $params = @{ Name = " + _ps_quote(adapter_name) + "; ErrorAction = 'Stop' }\n"
        "  if ($command.Parameters.ContainsKey('AllProperties')) { $params['AllProperties'] = $true }\n"
        "  if ($command.Parameters.ContainsKey('IncludeHidden')) { $params['IncludeHidden'] = $true }\n"
        "  $items = Get-NetAdapterAdvancedProperty @params\n"
        "  $rows = foreach ($item in $items) {\n"
        "    [PSCustomObject]@{\n"
        "      DisplayName = $item.DisplayName\n"
        "      RegistryKeyword = $item.RegistryKeyword\n"
        "      DisplayValue = $item.DisplayValue\n"
        "      RegistryValue = $item.RegistryValue\n"
        "      ValidDisplayValues = @($item.ValidDisplayValues)\n"
        "    }\n"
        "  }\n"
        "  @($rows) | ConvertTo-Json -Depth 6\n"
        "}"
    )


def _adapter_from_powershell_row(row: dict) -> NetworkAdapterInfo:
    return NetworkAdapterInfo(
        name=str(row.get("Name", "")),
        interface_index=int(row.get("InterfaceIndex") or 0),
        description=str(row.get("InterfaceDescription", "")),
        mac_address=str(row.get("MacAddress", "")),
        status=str(row.get("Status", "")),
        link_speed=str(row.get("LinkSpeed", "")),
        media_type=str(row.get("MediaType", "")),
        ndis_physical_medium=str(row.get("NdisPhysicalMedium", "")),
        pnp_device_id=str(row.get("PnPDeviceID", "")),
        hardware_interface=bool(row.get("HardwareInterface", False)),
        ipv4_addresses=[str(item) for item in _ensure_list(row.get("IPv4Addresses")) if str(item).strip()],
        gateways=[str(item) for item in _ensure_list(row.get("Gateways")) if str(item).strip()],
        dns_servers=[str(item) for item in _ensure_list(row.get("DnsServers")) if str(item).strip()],
        dhcp_enabled=row.get("DhcpEnabled") if isinstance(row.get("DhcpEnabled"), bool) else None,
    )


def _route_from_powershell_row(row: dict, fallback_index: int = 0) -> RouteInfo:
    return RouteInfo(
        order_index=int(row.get("OrderIndex") if row.get("OrderIndex") is not None else fallback_index),
        destination_prefix=str(row.get("DestinationPrefix", "")),
        next_hop=str(row.get("NextHop", "")),
        interface_index=int(row.get("InterfaceIndex") or 0),
        interface_alias=str(row.get("InterfaceAlias", "")),
        route_metric=int(row.get("RouteMetric") or 0),
        policy_store=str(row.get("PolicyStore", "")),
        persistent=bool(row.get("Persistent", False)),
    )


def _parse_netsh_interfaces(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        text = line.strip()
        if not text or text.startswith("-") or "Admin State" in text or "管理状态" in text:
            continue
        parts = text.split()
        if len(parts) < 4:
            continue
        name = " ".join(parts[3:])
        rows.append(
            {
                "Name": name,
                "InterfaceDescription": name,
                "Status": parts[1],
                "HardwareInterface": True,
            }
        )
    return rows


def _parse_route_print(output: str) -> list[RouteInfo]:
    rows: list[RouteInfo] = []
    in_ipv4_routes = False
    order_index = 0
    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        if "IPv4 Route Table" in text or "IPv4 路由表" in text:
            in_ipv4_routes = True
            continue
        if not in_ipv4_routes or text.startswith("=") or text.startswith("-") or text.startswith("Network Destination"):
            continue
        parts = text.split()
        if len(parts) < 5:
            continue
        destination, mask, gateway, interface, metric = parts[:5]
        if not destination[0].isdigit():
            continue
        try:
            prefix = ipaddress.IPv4Network(f"{destination}/{mask}", strict=False).with_prefixlen
            metric_value = int(metric)
        except Exception:
            continue
        rows.append(
            RouteInfo(
                order_index=order_index,
                destination_prefix=prefix,
                next_hop=gateway,
                interface_alias=interface,
                route_metric=metric_value,
                source="route print",
            )
        )
        order_index += 1
    return rows


def _ensure_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _replace_adapter(adapter: NetworkAdapterInfo, **changes) -> NetworkAdapterInfo:
    data = adapter.__dict__.copy()
    data.update(changes)
    return NetworkAdapterInfo(**data)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _normalized_gateway(value: str | None) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "-", "none"} else text


def _is_priority_vlan_property(display_name: str, registry_keyword: str = "") -> bool:
    text = f"{display_name} {registry_keyword}".lower()
    return any(item in text for item in PRIORITY_VLAN_PROPERTY_KEYWORDS)


def _looks_like_vlan_switch_values(values: Sequence[str]) -> bool:
    text = " ".join(str(value).lower() for value in values)
    return "packet priority" in text or "vlan enable" in text or "vlan disable" in text


def _vlan_zero_display_value(vlan_property: VlanProperty) -> str:
    reset_tokens = ("不存在", "not present", "disabled", "disable", "none")
    for value in vlan_property.valid_display_values:
        text = str(value).strip()
        if text == "0" or any(token in text.lower() for token in reset_tokens):
            return text
    return ""


def _validate_ip(value: str, label: str) -> str:
    try:
        ipaddress.IPv4Address(value)
    except Exception as exc:
        raise ValueError(f"{label}格式错误：{value}") from exc
    return value


def _validate_prefix(value: int) -> None:
    if value < 1 or value > 32:
        raise ValueError("IPv4前缀长度必须在1到32之间")


def parse_prefix_or_netmask(value: str) -> int:
    text = str(value).strip()
    if text.isdigit():
        prefix = int(text)
        if 0 <= prefix <= 32:
            return prefix
        raise ValueError("前缀长度或子网掩码格式无效，请输入 24 或 255.255.255.0 这种格式。")
    try:
        mask = ipaddress.IPv4Address(text)
    except Exception as exc:
        raise ValueError("前缀长度或子网掩码格式无效，请输入 24 或 255.255.255.0 这种格式。") from exc
    bits = "".join(f"{octet:08b}" for octet in mask.packed)
    if "01" in bits:
        raise ValueError("前缀长度或子网掩码格式无效，请输入 24 或 255.255.255.0 这种格式。")
    return bits.count("1")


def _validate_route(route: RouteConfig) -> None:
    try:
        ipaddress.IPv4Network(route.destination_prefix, strict=False)
    except Exception as exc:
        raise ValueError(f"目标网络格式错误：{route.destination_prefix}") from exc
    _validate_ip(route.next_hop, "网关")
    if not route.interface_alias.strip():
        raise ValueError("接口别名不能为空")
    if route.metric < 1:
        raise ValueError("Metric必须大于0")
def _validate_route(route: RouteConfig) -> None:
    try:
        ipaddress.IPv4Network(route.destination_prefix, strict=False)
    except Exception as exc:
        raise ValueError(f"目标网络格式错误：{route.destination_prefix}") from exc
    _validate_ip(route.next_hop, "网关")
    if route.next_hop == "0.0.0.0":
        raise ValueError("路由写入失败：下一跳不能为 0.0.0.0。")
    if route.metric < 1 or route.metric > 9999:
        raise ValueError("路由写入失败：跃点数必须在 1~9999 之间。")
    if route.interface_index < 0:
        raise ValueError("路由写入失败：所选出接口无效。")
