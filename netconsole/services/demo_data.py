from __future__ import annotations

from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository


DEMO_DEVICES = (
    Device(
        name="Huawei SW-SSH-Only",
        sysname="DEMO-HW-SW01",
        station="人民广场站",
        device_vendor="Huawei",
        device_type="SW",
        ip_address="10.10.1.1",
        ssh_enabled=1,
        ssh_port=22,
        telnet_enabled=0,
        telnet_port=23,
        ssh_username="huawei",
        ssh_password="huawei123",
        snmp_v1_enabled=0,
        snmp_v2c_enabled=1,
        snmp_v3_enabled=0,
        snmp_port=161,
        snmp_ro_community="hw_public",
        remark="SSH only with username and password.",
    ),
    Device(
        name="Ruijie SW-Telnet-Password",
        sysname="DEMO-RJ-SW01",
        station="体育中心站",
        device_vendor="Ruijie",
        device_type="SW",
        ip_address="10.10.2.1",
        ssh_enabled=0,
        ssh_port=22,
        telnet_enabled=1,
        telnet_port=23,
        telnet_username="",
        telnet_password="ruijie123",
        snmp_v1_enabled=0,
        snmp_v2c_enabled=1,
        snmp_v3_enabled=0,
        snmp_port=161,
        snmp_ro_community="rj_public",
        remark="Telnet only with password and blank username.",
    ),
    Device(
        name="H3C SW-Same-SSH-Telnet",
        sysname="DEMO-H3C-SW01",
        station="控制中心",
        device_vendor="H3C",
        device_type="SW",
        ip_address="10.10.3.1",
        ssh_enabled=1,
        ssh_port=22,
        telnet_enabled=1,
        telnet_port=23,
        ssh_username="admin",
        ssh_password="admin123",
        telnet_username="admin",
        telnet_password="admin123",
        snmp_v1_enabled=0,
        snmp_v2c_enabled=1,
        snmp_v3_enabled=0,
        snmp_port=161,
        snmp_ro_community="public",
        snmp_rw_community="private",
        remark="SSH and Telnet use the same credentials.",
    ),
    Device(
        name="H3C AC-Different-SSH-Telnet",
        sysname="DEMO-H3C-AC01",
        station="无线机房",
        device_vendor="H3C",
        device_type="AC",
        ip_address="10.10.4.10",
        ssh_enabled=1,
        ssh_port=22,
        telnet_enabled=1,
        telnet_port=23,
        ssh_username="sshadmin",
        ssh_password="ssh123",
        telnet_username="teladmin",
        telnet_password="tel123",
        snmp_v1_enabled=1,
        snmp_v2c_enabled=1,
        snmp_v3_enabled=1,
        snmp_port=161,
        snmp_ro_community="ac_public",
        snmpv3_security_level="noAuthNoPriv",
        remark="SSH and Telnet use different credentials.",
    ),
    Device(
        name="H3C FW-SSH-SNMPv3-AuthPriv",
        sysname="DEMO-H3C-FW01",
        station="控制中心安全区",
        device_vendor="H3C",
        device_type="FW",
        ip_address="10.10.5.254",
        ssh_enabled=1,
        ssh_port=22,
        telnet_enabled=0,
        telnet_port=23,
        ssh_username="secadmin",
        ssh_password="fw123",
        snmp_v1_enabled=0,
        snmp_v2c_enabled=0,
        snmp_v3_enabled=1,
        snmp_port=161,
        snmpv3_security_level="AuthPriv",
        snmpv3_auth_protocol="SHA",
        snmpv3_auth_password="auth123456",
        snmpv3_priv_protocol="AES128",
        snmpv3_priv_password="priv123456",
        remark="SNMPv3 AuthPriv example.",
    ),
    Device(
        name="AC",
        station="Demo",
        device_vendor="H3C",
        device_type="AC",
        ip_address="10.0.0.51",
        ssh_enabled=1,
        ssh_port=22,
        telnet_enabled=0,
        telnet_port=23,
        ssh_username="admin",
        ssh_password="Admin@123",
        remark="模拟器设备，用于 demo 环境测试",
    ),
    Device(
        name="SW01",
        station="Demo",
        device_vendor="H3C",
        device_type="SW",
        ip_address="10.0.0.52",
        ssh_enabled=1,
        ssh_port=22,
        telnet_enabled=0,
        telnet_port=23,
        ssh_username="admin",
        ssh_password="Admin@123",
        remark="模拟器设备，用于 demo 环境测试",
    ),
    Device(
        name="SW02",
        station="Demo",
        device_vendor="H3C",
        device_type="SW",
        ip_address="10.0.0.53",
        ssh_enabled=1,
        ssh_port=22,
        telnet_enabled=0,
        telnet_port=23,
        ssh_username="admin",
        ssh_password="Admin@123",
        remark="模拟器设备，用于 demo 环境测试",
    ),
)


def insert_demo_devices(repository: DeviceRepository) -> int:
    created_devices: list[Device] = []
    for device in DEMO_DEVICES:
        created_devices.append(repository.create(device))
    insert_demo_collected_data(repository, created_devices)
    return len(DEMO_DEVICES)


def insert_demo_collected_data(repository: DeviceRepository, devices: list[Device]) -> None:
    by_name = {device.name: device for device in devices}
    required = {name: by_name[name] for name in ("AC", "SW01", "SW02") if name in by_name and by_name[name].device_uuid}
    if set(required) != {"AC", "SW01", "SW02"}:
        return

    fact_repository = DeviceFactRepository(repository.database)
    run = fact_repository.create_collect_run(
        {
            "collect_run_uuid": "demo-collect-run-0001",
            "collect_type": "device_facts",
            "status": "success",
            "started_at": "2026-06-13T09:00:00",
            "ended_at": "2026-06-13T09:00:30",
            "raw_log_dir": "raw/collect/demo-collect-run-0001",
            "created_at": "2026-06-13T09:00:00",
        }
    )
    run_uuid = str(run["collect_run_uuid"])
    collected_at = "2026-06-13T09:00:30"

    facts = {
        "AC": {"sysname": "AC-DEMO", "model": "H3C WX3540H", "serial_number": "DEMO-AC-0001"},
        "SW01": {"sysname": "SW01-DEMO", "model": "H3C S5560X", "serial_number": "DEMO-SW01-0001"},
        "SW02": {"sysname": "SW02-DEMO", "model": "H3C S5130S", "serial_number": "DEMO-SW02-0001"},
    }
    for name, fact in facts.items():
        device_uuid = str(required[name].device_uuid)
        fact_repository.upsert_device_fact(
            {
                "device_uuid": device_uuid,
                **fact,
                "software_version": "Comware V7 Demo",
                "bootrom_version": "Demo BootROM",
                "vendor": "H3C",
                "uptime": "12 days, 03:21:00",
                "collected_at": collected_at,
                "collect_run_uuid": run_uuid,
                "raw_log_path": f"raw/collect/{run_uuid}/{device_uuid}.log",
                "updated_at": collected_at,
            }
        )

    sw01_uuid = str(required["SW01"].device_uuid)
    sw02_uuid = str(required["SW02"].device_uuid)
    ac_uuid = str(required["AC"].device_uuid)
    fact_repository.replace_device_interfaces(
        sw01_uuid,
        [
            _demo_interface("GigabitEthernet1/0/1", "UP", "UP", "1000M", "full", "L3", "route", "", "Uplink to AC", "10.0.0.52/24", "00:11:22:33:52:01", "Vlan-interface1", run_uuid, sw01_uuid, collected_at),
            _demo_interface("GigabitEthernet1/0/2", "UP", "UP", "1000M", "full", "L2", "trunk", "1", "Link to SW02", "", "00:11:22:33:52:02", "1,10,20", run_uuid, sw01_uuid, collected_at),
            _demo_interface("GigabitEthernet1/0/3", "DOWN", "DOWN", "auto", "auto", "L2", "shutdown", "1", "Unused", "", "00:11:22:33:52:03", "1", run_uuid, sw01_uuid, collected_at),
        ],
    )
    fact_repository.replace_device_interfaces(
        sw02_uuid,
        [
            _demo_interface("GigabitEthernet1/0/1", "UP", "UP", "1000M", "full", "L2", "trunk", "1", "Uplink to SW01", "", "00:11:22:33:53:01", "1,10,20", run_uuid, sw02_uuid, collected_at),
            _demo_interface("GigabitEthernet1/0/2", "UP", "UP", "100M", "full", "L2", "access", "10", "Access Port", "", "00:11:22:33:53:02", "10", run_uuid, sw02_uuid, collected_at),
            _demo_interface("GigabitEthernet1/0/3", "DOWN", "DOWN", "auto", "auto", "L2", "shutdown", "1", "Unused", "", "00:11:22:33:53:03", "1", run_uuid, sw02_uuid, collected_at),
        ],
    )
    fact_repository.replace_optical_modules(
        sw01_uuid,
        [
            _demo_optical_module("GigabitEthernet1/0/2", "-3.21 dBm", "-2.85 dBm", "38.5 C", "3.31 V", "6.2 mA", "DEMO-OPT-SW01-0001", run_uuid, sw01_uuid, collected_at),
        ],
    )
    fact_repository.replace_optical_modules(
        sw02_uuid,
        [
            _demo_optical_module("GigabitEthernet1/0/1", "-3.45 dBm", "-2.91 dBm", "37.8 C", "3.29 V", "6.0 mA", "DEMO-OPT-SW02-0001", run_uuid, sw02_uuid, collected_at),
        ],
    )
    fact_repository.replace_lldp_neighbors(
        sw01_uuid,
        [
            _demo_lldp("GigabitEthernet1/0/2", "SW02-DEMO", "GigabitEthernet1/0/1", "10.0.0.53", sw02_uuid, run_uuid, sw01_uuid, collected_at),
        ],
    )
    fact_repository.replace_lldp_neighbors(
        sw02_uuid,
        [
            _demo_lldp("GigabitEthernet1/0/1", "SW01-DEMO", "GigabitEthernet1/0/2", "10.0.0.52", sw01_uuid, run_uuid, sw02_uuid, collected_at),
        ],
    )
    fact_repository.replace_lldp_neighbors(
        ac_uuid,
        [
            _demo_lldp("GigabitEthernet1/0/1", "SW01-DEMO", "GigabitEthernet1/0/1", "10.0.0.52", sw01_uuid, run_uuid, ac_uuid, collected_at),
        ],
    )
    insert_demo_history(fact_repository, sw01_uuid, sw02_uuid)


def insert_demo_history(fact_repository: DeviceFactRepository, sw01_uuid: str, sw02_uuid: str) -> None:
    samples = (
        ("2026-06-13T09:00:00", "-3.45 dBm"),
        ("2026-06-13T10:00:00", "-3.38 dBm"),
        ("2026-06-13T11:00:00", "-3.21 dBm"),
    )
    for device_uuid, interface_name, neighbor_name, neighbor_ip in (
        (sw01_uuid, "GigabitEthernet1/0/2", "SW02-DEMO", "10.0.0.53"),
        (sw02_uuid, "GigabitEthernet1/0/1", "SW01-DEMO", "10.0.0.52"),
    ):
        for index, (collected_at, rx_power) in enumerate(samples, start=1):
            history_run_uuid = f"demo-history-{device_uuid[-4:]}-{index}"
            raw_log_path = f"raw/collect/{history_run_uuid}/{device_uuid}.log"
            fact_repository.append_interface_history(
                _demo_interface(
                    interface_name,
                    "UP",
                    "UP",
                    "1000M",
                    "full",
                    "二层",
                    "trunk",
                    "1",
                    "Demo historical interface",
                    "",
                    f"00:11:22:33:{device_uuid[-2:]}:{index:02d}",
                    "Tagged VLANs: 10,20",
                    history_run_uuid,
                    device_uuid,
                    collected_at,
                    raw_log_path=raw_log_path,
                )
            )
            fact_repository.append_optical_history(
                _demo_optical_module(
                    interface_name,
                    rx_power,
                    "-2.85 dBm",
                    "38.5 C",
                    "3.31 V",
                    "6.2 mA",
                    f"DEMO-HIST-OPT-{index}",
                    history_run_uuid,
                    device_uuid,
                    collected_at,
                    raw_log_path=raw_log_path,
                )
            )
            fact_repository.append_lldp_history(
                _demo_lldp(
                    interface_name,
                    neighbor_name,
                    "GigabitEthernet1/0/1",
                    neighbor_ip,
                    "",
                    history_run_uuid,
                    device_uuid,
                    collected_at,
                    raw_log_path=raw_log_path,
                )
            )


def _demo_interface(
    interface_name: str,
    link_status: str,
    protocol_status: str,
    speed: str,
    duplex: str,
    interface_type: str,
    port_status: str,
    pvid: str,
    description: str,
    ip_address: str,
    mac_address: str,
    vlan: str,
    run_uuid: str,
    device_uuid: str,
    collected_at: str,
    raw_log_path: str | None = None,
) -> dict[str, object | None]:
    return {
        "device_uuid": device_uuid,
        "interface_name": interface_name,
        "interface_type": "ethernet",
        "link_status": link_status,
        "protocol_status": protocol_status,
        "speed": speed,
        "duplex": duplex,
        "interface_type": interface_type,
        "port_status": port_status,
        "pvid": pvid,
        "description": description,
        "ip_address": ip_address,
        "mac_address": mac_address,
        "vlan": vlan,
        "collected_at": collected_at,
        "collect_run_uuid": run_uuid,
        "raw_log_path": raw_log_path or f"raw/collect/{run_uuid}/{device_uuid}.log",
        "updated_at": collected_at,
    }


def _demo_optical_module(
    interface_name: str,
    rx_power: str,
    tx_power: str,
    temperature: str,
    voltage: str,
    bias_current: str,
    module_serial_number: str,
    run_uuid: str,
    device_uuid: str,
    collected_at: str,
    raw_log_path: str | None = None,
) -> dict[str, object | None]:
    return {
        "device_uuid": device_uuid,
        "interface_name": interface_name,
        "rx_power": rx_power,
        "tx_power": tx_power,
        "temperature": temperature,
        "voltage": voltage,
        "bias_current": bias_current,
        "module_model": "SFP-GE-LX-SM1310",
        "module_serial_number": module_serial_number,
        "module_vendor": "H3C",
        "wavelength": "1310 nm",
        "transmission_distance": "10 km",
        "connector_type": "LC",
        "status": "normal",
        "collected_at": collected_at,
        "collect_run_uuid": run_uuid,
        "raw_log_path": raw_log_path or f"raw/collect/{run_uuid}/{device_uuid}.log",
        "updated_at": collected_at,
    }


def _demo_lldp(
    local_interface: str,
    neighbor_sysname: str,
    neighbor_interface: str,
    neighbor_ip: str,
    neighbor_device_uuid: str,
    run_uuid: str,
    device_uuid: str,
    collected_at: str,
    raw_log_path: str | None = None,
) -> dict[str, object | None]:
    return {
        "device_uuid": device_uuid,
        "local_interface": local_interface,
        "neighbor_sysname": neighbor_sysname,
        "neighbor_interface": neighbor_interface,
        "neighbor_ip": neighbor_ip,
        "neighbor_device_uuid": neighbor_device_uuid,
        "collected_at": collected_at,
        "collect_run_uuid": run_uuid,
        "raw_log_path": raw_log_path or f"raw/collect/{run_uuid}/{device_uuid}.log",
        "updated_at": collected_at,
    }
