from __future__ import annotations

import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import VehicleMrDTO
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.boot_config import (
    MrBootSessionService,
    MrSyslogConfigService,
    analyze_syslog_config,
)
from netconsole.services.ground_unattended.inventory import TrainInventorySyncService
from netconsole.services.ground_unattended.syslog_runtime import SyslogUdpReceiver


def test_inventory_incremental_sync_preserves_policy_and_marks_removed(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    site = "site-a"
    db = Database(paths.site_db_path(site))
    db.initialize()
    ct = DeviceRepository(db).create(
        Device(
            name="T01-CT",
            system_name="T01-MR-CT-SYSLOG",
            primary_address="192.0.2.10",
            ssh_enabled=1,
            ssh_username="admin",
            ssh_password="secret",
        )
    )
    cw = DeviceRepository(db).create(
        Device(
            name="T01-CW",
            primary_address="192.0.2.11",
            ssh_enabled=1,
            ssh_username="admin",
            ssh_password="secret",
        )
    )
    rows = [
        _mr(ct, "train-01", "01", "CT"),
        _mr(cw, "train-01", "01", "CW"),
    ]
    repository = GroundUnattendedRepository(paths.ground_unattended_db_path(site), site_id=site)
    service = TrainInventorySyncService(
        paths,
        site_id=site,
        repository=repository,
        base_query=_BaseQuery(rows),  # type: ignore[arg-type]
    )

    summary = service.synchronize()
    assert summary.discovered_train_count == 1
    assert summary.complete_train_count == 1
    repository.save_train_policy(
        "train-01",
        {"priority": True, "monitor_only": True, "remark": "重点列车"},
    )

    summary = TrainInventorySyncService(
        paths,
        site_id=site,
        repository=repository,
        base_query=_BaseQuery([rows[0]]),  # type: ignore[arg-type]
    ).synchronize()
    inventory = repository.list_inventory()
    assert summary.removed_endpoint_count == 1
    assert inventory[0]["priority"] is True
    assert inventory[0]["monitor_only"] is True
    assert inventory[0]["remark"] == "重点列车"
    assert inventory[0]["endpoints"][0]["source_hostname"] == "T01-MR-CT-SYSLOG"
    assert any(item["binding_status"] == "REMOVED" for item in inventory[0]["endpoints"])


def test_boot_session_uses_device_clock_midpoint_and_ignores_ntp_jump(
    tmp_path: Path,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground-unattended.sqlite",
        site_id="site-a",
    )
    service = MrBootSessionService(repository=repository, tolerance_seconds=120)
    device_zone = timezone(timedelta(hours=8))
    checked = datetime(2026, 7, 27, 3, 26, 49, tzinfo=timezone.utc)

    first, created = service.observe(
        device_uuid="mr-clock",
        device_id=1,
        train_id="train-01",
        mr_role="CT",
        checked_at=checked,
        uptime_seconds=1 * 3600 + 59 * 60,
        evidence_path="evidence/clock-1.json",
        device_clock_before=datetime(
            2026, 7, 27, 11, 26, 47, tzinfo=device_zone
        ),
        device_clock_after=datetime(
            2026, 7, 27, 11, 26, 49, tzinfo=device_zone
        ),
        boot_time_uncertainty_seconds=60,
        reboot_reason="Power on",
        timezone_name="BeiJing",
        utc_offset_seconds=8 * 3600,
        time_quality="DEVICE_CLOCK",
    )
    same, created_same = service.observe(
        device_uuid="mr-clock",
        device_id=1,
        train_id="train-01",
        mr_role="CT",
        checked_at=checked + timedelta(minutes=1),
        uptime_seconds=2 * 3600,
        evidence_path="evidence/clock-2.json",
        device_clock_before=datetime(
            2026, 7, 27, 11, 32, 47, tzinfo=device_zone
        ),
        device_clock_after=datetime(
            2026, 7, 27, 11, 32, 49, tzinfo=device_zone
        ),
        boot_time_uncertainty_seconds=60,
        reboot_reason="Power on",
        timezone_name="BeiJing",
        utc_offset_seconds=8 * 3600,
        time_quality="DEVICE_CLOCK",
    )

    assert created and not created_same
    assert first["estimated_boot_time"] == "2026-07-27T09:27:48.000+08:00"
    assert first["boot_time_uncertainty_seconds"] == 60
    assert first["reboot_reason"] == "Power on"
    assert first["utc_offset_seconds"] == 8 * 3600
    assert same["boot_session_id"] == first["boot_session_id"]
    assert same["time_quality"] == "CLOCK_JUMP"
    assert same["clock_jump_seconds"] == 300

    restarted, created_restart = service.observe(
        device_uuid="mr-clock",
        device_id=1,
        train_id="train-01",
        mr_role="CT",
        checked_at=checked + timedelta(minutes=2),
        uptime_seconds=60,
        evidence_path="evidence/clock-3.json",
        device_clock_before=datetime(
            2026, 7, 27, 11, 33, 47, tzinfo=device_zone
        ),
        device_clock_after=datetime(
            2026, 7, 27, 11, 33, 49, tzinfo=device_zone
        ),
        time_quality="DEVICE_CLOCK",
    )
    assert created_restart
    assert restarted["boot_session_id"] != first["boot_session_id"]


def test_device_clock_boot_estimate_crosses_year_boundary(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground-unattended.sqlite",
        site_id="site-a",
    )
    zone = timezone(timedelta(hours=-5))

    row, _created = MrBootSessionService(repository=repository).observe(
        device_uuid="mr-year",
        device_id=2,
        train_id="train-02",
        mr_role="CW",
        checked_at=datetime(2027, 1, 1, 7, 0, tzinfo=timezone.utc),
        uptime_seconds=2 * 3600,
        evidence_path="evidence/year.json",
        device_clock_before=datetime(2027, 1, 1, 0, 59, 59, tzinfo=zone),
        device_clock_after=datetime(2027, 1, 1, 1, 0, 1, tzinfo=zone),
        timezone_name="EST",
        utc_offset_seconds=-5 * 3600,
        time_quality="DEVICE_CLOCK",
    )

    assert row["estimated_boot_time"] == "2026-12-31T23:00:00.000-05:00"


def test_boot_session_detects_restart_during_gap_even_when_previous_uptime_is_low(
    tmp_path: Path,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground-unattended.sqlite",
        site_id="site-a",
    )
    service = MrBootSessionService(repository=repository, tolerance_seconds=120)
    zone = timezone(timedelta(hours=8))
    checked = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)

    first, _created = service.observe(
        device_uuid="mr-fast-reboot",
        device_id=3,
        train_id="train-03",
        mr_role="CT",
        checked_at=checked,
        uptime_seconds=60,
        evidence_path="evidence/fast-1.json",
        device_clock_before=datetime(2026, 7, 27, 12, 0, tzinfo=zone),
        device_clock_after=datetime(2026, 7, 27, 12, 0, 2, tzinfo=zone),
        time_quality="DEVICE_CLOCK",
    )
    restarted, created = service.observe(
        device_uuid="mr-fast-reboot",
        device_id=3,
        train_id="train-03",
        mr_role="CT",
        checked_at=checked + timedelta(minutes=5),
        uptime_seconds=60,
        evidence_path="evidence/fast-2.json",
        device_clock_before=datetime(2026, 7, 27, 12, 5, tzinfo=zone),
        device_clock_after=datetime(2026, 7, 27, 12, 5, 2, tzinfo=zone),
        time_quality="DEVICE_CLOCK",
    )

    assert created
    assert restarted["boot_session_id"] != first["boot_session_id"]


def test_udp_receiver_routes_multiple_mrs_and_keeps_unidentified_separate(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    repository.sync_inventory(
        trains=[
            {"train_id": "train-01", "train_no": "01", "train_name": "T01"},
            {"train_id": "train-02", "train_no": "02", "train_name": "T02"},
        ],
        endpoints=[
            {
                "device_uuid": "mr-ct-01",
                "device_id": 1,
                "train_id": "train-01",
                "mr_role": "CT",
                "device_name": "MR-CT-01",
                "management_ip": "127.0.0.1",
            },
            {
                "device_uuid": "mr-cw-02",
                "device_id": 2,
                "train_id": "train-02",
                "mr_role": "CW",
                "device_name": "MR-CW-02",
                "management_ip": "127.0.0.3",
            },
        ],
    )
    active = tmp_path / "ground" / "active" / "2026-07-25"
    receiver = SyslogUdpReceiver(repository=repository, site_id="site-a")
    receiver.start(
        run_id="run-1",
        run_date="2026-07-25",
        active_dir=active,
        listen_host="127.0.0.1",
        listen_port=0,
        queue_capacity=100,
        flush_records=1,
        flush_interval_seconds=0.1,
        event_batch_size=1,
        event_batch_interval_seconds=0.1,
    )
    _host, port_text = receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)
    message = (
        "%Jul  3 19:19:27:496 2026 MR-CT-01 WMESH/5/MESH_ACTIVELINK_SWITCH: "
        "Switch an active link from AP-A_0000-0000-0001(-60) to "
        "AP-B_0000-0000-0002(-55): peer quantity = 2, link quantity = 2, switch reason = 3."
    ).encode()
    unknown = b"%Jul  3 19:19:27:496 2026 OTHER WMESH/5/MESH_LINKUP: peer AP-X_0000-0000-0003"
    second = b"%Jul  3 19:19:27:496 2026 MR-CW-02 WMESH/5/MESH_LINKDOWN: peer AP-X_0000-0000-0003"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.sendto(message, ("127.0.0.1", int(port_text)))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.bind(("127.0.0.3", 0))
        sender.sendto(second, ("127.0.0.1", int(port_text)))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.bind(("127.0.0.2", 0))
        sender.sendto(unknown, ("127.0.0.1", int(port_text)))
    _wait_until(lambda: len(repository.list_wmesh_events(run_id="run-1")) == 3)
    stop_result = receiver.stop()
    assert stop_result["success"] is True
    assert stop_result["udp_port_released"] is True
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", int(port_text)))

    events = repository.list_wmesh_events(run_id="run-1")
    assert any(event["train_id"] == "train-01" for event in events)
    assert any(event["train_id"] == "train-02" for event in events)
    assert any(event["data_quality"] == "UNIDENTIFIED_SOURCE" for event in events)
    raw = repository.list_raw_files(data_type="syslog")
    assert raw and all(row["status"] == "CLOSED" for row in raw)
    assert any("train-01/CT" in row["relative_path"] for row in raw)
    assert any("_unidentified" in row["relative_path"] for row in raw)
    assert not any(thread.name.startswith("ground-syslog-") and thread.is_alive() for thread in __import__("threading").enumerate())


def test_boot_session_and_fixed_syslog_profile_do_not_save(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    site = "site-a"
    database = Database(paths.site_db_path(site))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(
            name="MR-CT-01",
            primary_address="192.0.2.10",
            ssh_enabled=1,
            ssh_username="admin",
            ssh_password="secret",
        )
    )
    device_uuid = str(device.device_uuid)
    repository = GroundUnattendedRepository(paths.ground_unattended_db_path(site), site_id=site)
    repository.sync_inventory(
        trains=[{"train_id": "train-01", "train_no": "01", "train_name": "T01"}],
        endpoints=[
            {
                "device_uuid": device_uuid,
                "device_id": device.id,
                "train_id": "train-01",
                "mr_role": "CT",
                "device_name": device.name,
                "management_ip": device.primary_address,
            }
        ],
    )
    observed = MrBootSessionService(repository=repository, tolerance_seconds=120)
    base = datetime.now().astimezone()
    first, created = observed.observe(
        device_uuid=device_uuid,
        device_id=device.id,
        train_id="train-01",
        mr_role="CT",
        checked_at=base,
        uptime_seconds=3600,
        evidence_path="evidence/a.json",
    )
    same, created_same = observed.observe(
        device_uuid=device_uuid,
        device_id=device.id,
        train_id="train-01",
        mr_role="CT",
        checked_at=base + timedelta(seconds=30),
        uptime_seconds=3630,
        evidence_path="evidence/b.json",
    )
    restarted, created_restart = observed.observe(
        device_uuid=device_uuid,
        device_id=device.id,
        train_id="train-01",
        mr_role="CT",
        checked_at=base + timedelta(seconds=90),
        uptime_seconds=10,
        evidence_path="evidence/c.json",
    )
    assert created and not created_same and created_restart
    assert first["boot_session_id"] == same["boot_session_id"]
    assert restarted["boot_session_id"] != first["boot_session_id"]

    connection = _Connection(
        version="H3C MR uptime is 1 day, 2 hours, 3 minutes\n",
        config="",
        config_after=(
            "info-center enable\n"
                "info-center loghost 192.0.2.100 port 5514\n"
                "info-center source default loghost deny\n"
                "info-center source WMESH loghost level notification\n"
                "info-center source IFNET loghost level notification\n"
                "info-center source CFGMAN loghost level notification\n"
            ),
        info_after=(
            "Information Center: Enabled\n"
            "Log host: Enabled\n"
            "    192.0.2.100,\n"
            "    port number: 5514, host facility: local7\n"
        ),
    )
    service = MrSyslogConfigService(
        paths,
        site_id=site,
        repository=repository,
        connection_factory=lambda _config: connection,
    )
    result = service.check(
        run_id="run-1",
        run_date="2026-07-25",
        device_uuid=device_uuid,
        target_ip="192.0.2.100",
        target_port=5514,
        boot_tolerance_seconds=120,
    )
    assert result.config_status == "CONFIG_SENT"
    assert "save" not in " ".join(connection.commands).casefold()
    assert "info-center loghost 192.0.2.100 port 5514" in connection.commands
    assert analyze_syslog_config(
        "\n".join(connection.commands), target_ip="192.0.2.100", target_port=5514
    ).complete


def _mr(device: Device, train_id: str, train_no: str, role: str) -> VehicleMrDTO:
    return VehicleMrDTO(
        id=str(device.device_uuid),
        device_id=device.id,
        name=device.name,
        train_id=train_id,
        train_no=train_no,
        mr_position_code=role,  # type: ignore[arg-type]
        management_ip=device.primary_address,
        protocol="SSH",
        port=22,
    )


class _BaseQuery:
    def __init__(self, rows: list[VehicleMrDTO]) -> None:
        self.rows = rows

    def list_mrs(self, _site_id: str, *, page: int, page_size: int):
        del page_size
        return SimpleNamespace(items=self.rows if page == 1 else [], total=len(self.rows))


class _Connection:
    def __init__(
        self,
        *,
        version: str,
        config: str,
        config_after: str = "",
        info_before: str = "",
        info_after: str = "",
    ) -> None:
        self.version = version
        self.config = config
        self.config_after = config_after
        self.info_before = info_before
        self.info_after = info_after
        self.commands: list[str] = []
        self._write_started = False

    def send_command(self, command: str, _timeout: int) -> str:
        self.commands.append(command)
        if command == "display clock":
            return (
                "11:26:48 BeiJing Mon 07/27/2026\n"
                "Time Zone : BeiJing add 08:00:00\n"
            )
        if command == "display version":
            return self.version
        if command == "display info-center":
            return self.info_after if self._write_started else self.info_before
        if command.startswith("display current-configuration"):
            return self.config_after if self._write_started else self.config
        if command not in {"screen-length disable"}:
            self._write_started = True
        return ""

    def close(self) -> None:
        return None


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met")
