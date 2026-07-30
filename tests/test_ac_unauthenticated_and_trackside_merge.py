from __future__ import annotations

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.parsers.h3c.ac.wlan_ap_unauthenticated_parser import parse_wlan_ap_unauthenticated_rows, parse_wlan_ap_unauthenticated_summary
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services import h3c_ac_collect_service
from netconsole.services.h3c_ac_collect_service import collect_h3c_ac_resources
from netconsole.services.trackside_ap_business import build_new_online_ap_overview_rows, build_trackside_ap_business_rows, format_trackside_display_value


UNAUTHENTICATED_SAMPLE = """
Total number of APs: 128
Total number of connected APs: 92
Total number of connected manual APs: 83
Total number of connected auto APs: 9
Total number of connected common APs: 9
Total number of connected WTUs: 0
Inside APs: 0
Maximum supported APs: 1024
Remaining APs: 932
Total AP licenses: 128
Local AP licenses: 128
Server AP licenses: 0
Remaining local AP licenses: 36
Sync AP licenses: 0

AP information:
State : I = Idle,      J  = Join,       JA = JoinAck,    IL = ImageLoad
        C = Config,    DC = DataCheck,  R  = Run,        M = Master,  B = Backup

AP name                        APID  State Model           Serial ID            Dev-Type        Work-mode
30f5-277a-1780                 872   R/M   WA6624X         219801A4588256E0002X  COMMON          FitAP
30f5-277a-1781                 873   R/M   WA6624X         219801A4588256E0002Y  COMMON          FitAP
30f5-277a-1782                 874   R/M   WA6624X         219801A4588256E0002Z  COMMON          FitAP
30f5-277a-1783                 875   R/M   WA6624X         219801A4588256E00030  COMMON          FitAP
30f5-277a-1784                 876   R/M   WA6624X         219801A4588256E00031  COMMON          FitAP
30f5-277a-1785                 877   R/M   WA6624X         219801A4588256E00032  COMMON          FitAP
30f5-277a-1786                 878   R/M   WA6624X         219801A4588256E00033  COMMON          FitAP
30f5-277a-1787                 879   R/M   WA6624X         219801A4588256E00034  COMMON          FitAP
30f5-277a-1788                 880   R/M   WA6624X         219801A4588256E00035  COMMON          FitAP
"""


def make_ac_repository(tmp_path) -> AcRepository:
    database = Database(tmp_path / "ac.db")
    database.initialize()
    return AcRepository(database)


class FakeAcConnection:
    def __init__(self, outputs: dict[str, object] | None = None) -> None:
        self.outputs = outputs or {}
        self.commands: list[str] = []

    def send_command(self, command, **_kwargs):
        self.commands.append(command)
        if command in self.outputs:
            value = self.outputs[command]
            if isinstance(value, Exception):
                raise value
            return value
        return {
            "screen-length disable": "",
            "display wlan ap all": "AP name APID State Model Serial ID Group name Online time Clients Mode IP address\nAP-A 1 R/M WA6624X SN-A G 1:00 0 Fit 10.0.0.1\n",
            "display wlan ap all address": "AP name IP address MAC address\nAP-A 10.0.0.1 30f5-277a-1780\n",
            "display wlan ap all radio": "AP name RID State Channel BW Usage TxPower Clients\nAP-A 1 Up 1 20 0 20 0\n",
            "display wlan ap all radio verbose filter bbssid": "",
            "display wlan ap all lldp": "",
        }[command]

    def disconnect(self):
        pass


def make_ac_device() -> Device:
    return Device(
        name="AC",
        device_uuid="22222222-2222-4222-8222-222222222222",
        device_vendor="H3C",
        device_type="AC",
        ip_address="10.0.0.254",
        ssh_username="u",
        ssh_password="p",
    )


def test_wlan_ap_unauthenticated_parser_extracts_summary_and_rows():
    summary = parse_wlan_ap_unauthenticated_summary(UNAUTHENTICATED_SAMPLE)
    rows = parse_wlan_ap_unauthenticated_rows(UNAUTHENTICATED_SAMPLE)

    assert summary["connected_auto_aps"] == 9
    assert len(rows) == 9
    assert rows[0]["ap_name"] == "30f5-277a-1780"
    assert rows[0]["apid"] == "872"
    assert rows[0]["state"] == "R/M"
    assert rows[0]["model"] == "WA6624X"
    assert rows[0]["serial_number"] == "219801A4588256E0002X"
    assert rows[0]["dev_type"] == "COMMON"
    assert rows[0]["work_mode"] == "FitAP"
    assert rows[0]["inferred_ap_mac"] is None
    assert all(row["ap_name"] != "C" for row in rows)
    assert all(row["apid"] != "=" for row in rows)
    assert all(row["model"] != "DC" for row in rows)
    assert all(row["serial_number"] != "=" for row in rows)


def test_wlan_ap_unauthenticated_parser_skips_state_legend_before_header():
    rows = parse_wlan_ap_unauthenticated_rows(
        """
AP information:
State : I = Idle,      J  = Join,       JA = JoinAck,    IL = ImageLoad
        C = Config,    DC = DataCheck,  R  = Run,        M = Master,  B = Backup
"""
    )

    assert rows == []


def test_fit_ap_unauthenticated_snapshot_can_clear_without_deleting_history(tmp_path):
    repository = make_ac_repository(tmp_path)
    repository.replace_fit_ap_unauthenticated(
        "ac-1",
        {"connected_auto_aps": 1},
        [{"ap_name": "30f5-277a-1780", "serial_number": "SN-1"}],
    )

    repository.replace_fit_ap_unauthenticated("ac-1", {"connected_auto_aps": 0}, [])

    assert repository.list_fit_ap_unauthenticated("22222222-2222-4222-8222-222222222222") == []
    assert len(repository.list_fit_ap_unauthenticated_history("ac-1")) == 1
    assert repository.get_fit_ap_unauthenticated_summary("ac-1")["connected_auto_aps"] == 0


def test_fit_ap_resources_derive_unauthenticated_register_status(tmp_path):
    repository = make_ac_repository(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {"ap_name": "AP-Pending", "serial_number": "SN-PENDING", "apid": "1"},
            {"ap_name": "AP-Confirmed", "serial_number": "SN-CONFIRMED", "apid": "2"},
            {"ap_name": "AP-Normal", "serial_number": "SN-NORMAL", "apid": "3"},
        ],
    )
    repository.replace_fit_ap_unauthenticated(
        "ac-1",
        {"connected_auto_aps": 2},
        [
            {"ap_name": "AP-Pending", "serial_number": "SN-PENDING", "apid": "1", "collected_at": "2026-01-02T00:00:00"},
            {"ap_name": "AP-Confirmed", "serial_number": "SN-CONFIRMED", "apid": "2", "collected_at": "2026-01-02T00:00:00"},
        ],
    )
    repository.replace_fit_ap_unauthenticated(
        "ac-1",
        {"connected_auto_aps": 1},
        [{"ap_name": "AP-Pending", "serial_number": "SN-PENDING", "apid": "1", "collected_at": "2026-01-03T00:00:00"}],
    )

    rows = {row["ap_name"]: row for row in repository.list_fit_ap_resources_with_metadata("ac-1")}
    assert rows["AP-Pending"]["unauthenticated_state"] == "pending_confirm"
    assert rows["AP-Pending"]["register_status"] == "未固化"
    assert rows["AP-Confirmed"]["unauthenticated_state"] == "confirmed_manual"
    assert rows["AP-Confirmed"]["register_status"] == "已固化/已确认"
    assert rows["AP-Normal"]["register_status"] == "已手动固化或普通AP"


def test_fit_ap_unauthenticated_apid_does_not_match_across_ac(tmp_path):
    repository = make_ac_repository(tmp_path)
    repository.replace_fit_ap_resources("ac-2", [{"ap_name": "AP-Other", "apid": "1"}])
    repository.replace_fit_ap_unauthenticated("ac-1", {"connected_auto_aps": 1}, [{"ap_name": "AP-Pending", "apid": "1"}])

    row = repository.list_fit_ap_resources_with_metadata("ac-2")[0]
    assert row["register_status"] == "已手动固化或普通AP"


def test_ac_collect_optional_unauthenticated_failure_does_not_fail_resources(monkeypatch, tmp_path):
    repository = make_ac_repository(tmp_path)
    connection = FakeAcConnection({"display wlan ap unauthenticated": RuntimeError("optional failed")})
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)

    result = collect_h3c_ac_resources(
        make_ac_device(),
        "demo",
        repository=repository,
        paths=PathResolver(tmp_path),
        refresh_ac_overview=False,
    )

    assert result.success is True
    assert result.fit_ap_resources_updated == 1
    assert result.unauthenticated_updated is False
    assert "failed" in result.unauthenticated_error
    assert repository.list_fit_ap_unauthenticated("ac-1") == []


def test_build_new_online_ap_overview_rows_uses_only_current_unauthenticated_snapshot():
    rows = build_new_online_ap_overview_rows(
        [{"ac_device_uuid": "ac-1", "ap_name": "AP-Pending", "serial_number": "SN-PENDING", "site": "Station A"}],
        [],
        [{"ap_name": "AP-Pending", "serial_number": "SN-PENDING", "device_name": "SW-1", "interface_name": "GE1/0/1"}],
        unauthenticated_rows=[{"ac_device_uuid": "ac-1", "ap_name": "AP-Pending", "serial_number": "SN-PENDING", "collected_at": "2026-01-02T00:00:00"}],
        unauthenticated_history_rows=[
            {"ac_device_uuid": "ac-1", "ap_name": "AP-Confirmed", "serial_number": "SN-CONFIRMED", "collected_at": "2026-01-01T00:00:00"},
            {"ac_device_uuid": "ac-1", "ap_name": "AP-Gone", "serial_number": "SN-GONE", "collected_at": "2026-01-01T00:00:00"},
        ],
    )

    by_name = {row["ap_name"]: row for row in rows}
    assert list(by_name) == ["AP-Pending"]
    assert by_name["AP-Pending"]["register_status"] == "未固化"
    assert by_name["AP-Pending"]["new_online_status"] == "当前新上线Auto AP"
    assert by_name["AP-Pending"]["identity_source"] == "AC未固化Auto AP"


def test_build_new_online_ap_overview_rows_empty_current_snapshot_ignores_history():
    rows = build_new_online_ap_overview_rows(
        [],
        [],
        [],
        unauthenticated_rows=[],
        unauthenticated_history_rows=[
            {"ac_device_uuid": "ac-1", "ap_name": "AP-Gone", "serial_number": "SN-GONE", "collected_at": "2026-01-01T00:00:00"},
        ],
    )

    assert rows == []


def test_trackside_ap_business_current_lldp_neighbor_mac_never_displays_dash():
    switch = Device(name="HX_1", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/47", "description": "AP47"}]},
        {"sw-1": []},
        [],
        {"sw-1": [{"local_interface": "GE2/0/47", "neighbor_mac": "bc5a-3457-cfe0"}]},
    )

    assert rows[0]["ap_mac"] == "bc:5a:34:57:cf:e0"
    assert format_trackside_display_value("ap_mac", rows[0]) != "-"
