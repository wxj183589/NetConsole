from __future__ import annotations

from pathlib import Path

from netconsole.parsers.h3c.arp_parser import ArpParseResult, ArpRecord, parse_h3c_arp
from netconsole.repositories.ground_arp_repository import GroundArpRepository
from netconsole.models.device import Device
from netconsole.core.paths import PathResolver
from netconsole.services.ground_unattended.arp_collection import GroundArpCollector
from netconsole.services.ground_unattended.arp_identity import GroundMrIdentityService


def _mr(number: int, ip: str, mac: str = "") -> dict[str, str]:
    return {
        "id": f"mr-{number}", "train_id": f"train-{number}",
        "train_no": str(number), "role": "CT", "management_ip": ip,
        "backup_management_ip": "", "mac": mac,
    }


def _record(ip: str, mac: str, *, vlan: str = "100") -> ArpRecord:
    return ArpRecord(ip_address=ip, mac_address=mac, vlan=vlan, interface_name="GE1/0/1")


def _success(repo: GroundArpRepository, identity: GroundMrIdentityService, records: list[ArpRecord], mrs: list[dict[str, str]], *, collection_id: str | None = None) -> dict[str, object]:
    result = repo.save_collection(
        source_device_uuid="sw-1", source_device_name="交换机",
        query_mode="ALL", query_scope="ALL", requested_vlans=[],
        started_at="2026-11-15T10:00:00+08:00", completed_at="2026-11-15T10:00:01+08:00",
        parse_result=ArpParseResult(records=tuple(records)),
    )
    stats = identity.apply_collection(
        collection_id=str(result["collection_id"]), records=records, mrs=mrs,
    )
    repo.update_collection_stats(str(result["collection_id"]), **stats)
    return result | stats


def test_arp_parser_recognizes_comware_rows_and_flags_pagination() -> None:
    parsed = parse_h3c_arp(
        "IP Address       MAC Address     VLAN  Interface  Aging Type\n"
        "10.0.0.1         0011-2233-4455  100   GE1/0/1    20    D"
    )
    assert parsed.complete
    assert parsed.records[0].mac_address == "00:11:22:33:44:55"
    assert not parse_h3c_arp(
        "IP Address MAC Address VLAN Interface\n10.0.0.1 0011-2233-4455 100 GE1/0/1\n--More--"
    ).complete


def test_incremental_arp_keeps_history_marks_absence_and_recovers(tmp_path: Path) -> None:
    repo = GroundArpRepository(tmp_path / "ground.sqlite", site_id="site-a")
    identity = GroundMrIdentityService(repo)
    mrs = [_mr(1, "10.0.0.1"), _mr(2, "10.0.0.2"), _mr(3, "10.0.0.3"), _mr(4, "10.0.0.4"), _mr(5, "10.0.0.5")]
    first = [_record("10.0.0.1", "00:00:00:00:00:01"), _record("10.0.0.2", "00:00:00:00:00:02"), _record("10.0.0.3", "00:00:00:00:00:03")]
    second = [_record("10.0.0.3", "00:00:00:00:00:03"), _record("10.0.0.4", "00:00:00:00:00:04"), _record("10.0.0.5", "00:00:00:00:00:05")]
    _success(repo, identity, first, mrs)
    _success(repo, identity, second, mrs)

    observations = repo.list_observations(source_device_uuid="sw-1", query_scope="ALL")
    assert {row["ip_address"] for row in observations} == {f"10.0.0.{n}" for n in range(1, 6)}
    by_ip = {row["ip_address"]: row for row in observations}
    assert by_ip["10.0.0.1"]["observed_in_last_success"] == 0
    assert by_ip["10.0.0.2"]["observed_in_last_success"] == 0
    assert by_ip["10.0.0.3"]["observed_in_last_success"] == 1
    assert by_ip["10.0.0.1"]["freshness_status"] == "NOT_OBSERVED"
    assert by_ip["10.0.0.3"]["observation_count"] == 2
    assert len(repo.find_identity_relations(mr_uuid="mr-1", confirmed_only=True)) == 1
    assert len(repo.find_identity_relations(mr_uuid="mr-5", confirmed_only=True)) == 1

    _success(repo, identity, first[:2], mrs)
    by_ip = {row["ip_address"]: row for row in repo.list_observations()}
    assert by_ip["10.0.0.1"]["observed_in_last_success"] == 1
    assert by_ip["10.0.0.2"]["observed_in_last_success"] == 1
    assert by_ip["10.0.0.5"]["observed_in_last_success"] == 0


def test_failed_partial_and_truncated_collection_do_not_clear_last_success(tmp_path: Path) -> None:
    repo = GroundArpRepository(tmp_path / "ground.sqlite", site_id="site-a")
    identity = GroundMrIdentityService(repo)
    mrs = [_mr(1, "10.0.0.1"), _mr(2, "10.0.0.2")]
    _success(repo, identity, [_record("10.0.0.1", "00:00:00:00:00:01"), _record("10.0.0.2", "00:00:00:00:00:02")], mrs)
    before = {row["ip_address"]: row for row in repo.list_observations()}
    for result in (
        ArpParseResult(status="FAILED", completeness="UNKNOWN"),
        ArpParseResult(records=(_record("10.0.0.1", "00:00:00:00:00:01"),), status="PARTIAL", completeness="INCOMPLETE"),
        ArpParseResult(records=(_record("10.0.0.1", "00:00:00:00:00:01"),), status="TRUNCATED", completeness="INCOMPLETE"),
    ):
        repo.save_collection(
            source_device_uuid="sw-1", source_device_name="交换机", query_mode="ALL", query_scope="ALL",
            requested_vlans=[], started_at="2026-11-15T10:00:00+08:00", completed_at="2026-11-15T10:00:01+08:00", parse_result=result,
        )
    after = {row["ip_address"]: row for row in repo.list_observations()}
    assert after["10.0.0.2"]["observed_in_last_success"] == before["10.0.0.2"]["observed_in_last_success"] == 1
    assert after["10.0.0.2"]["last_success_collection_id"] == before["10.0.0.2"]["last_success_collection_id"]
    assert {row["status"] for row in repo.list_collections(limit=5)} == {"TRUNCATED", "PARTIAL", "FAILED", "SUCCESS"}


def test_partial_vlan_scope_does_not_mark_other_scope_absent(tmp_path: Path) -> None:
    repo = GroundArpRepository(tmp_path / "ground.sqlite", site_id="site-a")
    repo.save_collection(
        source_device_uuid="sw-1", source_device_name="交换机", query_mode="VLAN", query_scope="VLAN:100",
        requested_vlans=[100], started_at="a", completed_at="b",
        parse_result=ArpParseResult(records=(_record("10.0.0.1", "00:00:00:00:00:01", vlan="100"),)),
    )
    repo.save_collection(
        source_device_uuid="sw-1", source_device_name="交换机", query_mode="VLAN", query_scope="VLAN:200",
        requested_vlans=[200], started_at="a", completed_at="b",
        parse_result=ArpParseResult(records=(_record("10.0.0.2", "00:00:00:00:00:02", vlan="200"),), status="PARTIAL", completeness="INCOMPLETE"),
    )
    rows = repo.list_observations()
    assert {row["query_scope"] for row in rows} == {"VLAN:100", "VLAN:200"}
    assert next(row for row in rows if row["query_scope"] == "VLAN:100")["observed_in_last_success"] == 1


def test_mac_conflict_is_retained_without_replacing_confirmed_identity(tmp_path: Path) -> None:
    repo = GroundArpRepository(tmp_path / "ground.sqlite", site_id="site-a")
    identity = GroundMrIdentityService(repo)
    mr = _mr(1, "10.0.0.1", "00:00:00:00:00:10")
    _success(repo, identity, [_record("10.0.0.1", "00:00:00:00:00:10")], [mr])
    result = _success(repo, identity, [_record("10.0.0.1", "00:00:00:00:00:11")], [mr])
    confirmed = repo.find_identity_relations(mr_uuid="mr-1", confirmed_only=True)
    assert {row["identity_mac"] for row in confirmed} >= {"00:00:00:00:00:10"}
    assert "00:00:00:00:00:11" not in {row["identity_mac"] for row in confirmed}
    assert result["conflict_count"] == 1
    assert repo.list_conflicts()[0]["conflict_type"] == "MR_MAC_CHANGED"


def test_identity_survives_repository_restart_and_peer_resolution(tmp_path: Path) -> None:
    path = tmp_path / "ground.sqlite"
    repo = GroundArpRepository(path, site_id="site-a")
    identity = GroundMrIdentityService(repo)
    mr = _mr(1, "10.0.0.1")
    _success(repo, identity, [_record("10.0.0.1", "00:00:00:00:00:01")], [mr])
    restarted = GroundMrIdentityService(GroundArpRepository(path, site_id="site-a"))
    resolved = restarted.resolve_peer("00:00:00:00:00:01", [mr])
    assert resolved.status == "CONFIRMED"
    assert resolved.mr_uuid == "mr-1"


def test_collector_uses_full_table_for_blank_vlan_and_one_command_per_vlan(tmp_path: Path) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def send_command(self, command: str, timeout: int) -> str:
            self.commands.append(command)
            if command == "screen-length disable":
                return ""
            return "IP Address MAC Address VLAN Interface Aging Type\n10.0.0.1 0011-2233-4455 100 GE1/0/1 20 D"

        def close(self) -> None:
            return None

    created: list[FakeConnection] = []

    def factory(_config):
        item = FakeConnection()
        created.append(item)
        return item

    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    repo = GroundArpRepository(tmp_path / "ground.sqlite", site_id="site-a")
    identity = GroundMrIdentityService(repo)
    source = Device(
        device_uuid="sw-1", name="SW-1", device_type="SW", device_vendor="H3C",
        primary_address="10.0.0.254", protocol="SSH", port=22,
        ssh_username="u", ssh_password="p",
    )
    collector = GroundArpCollector(
        paths, site_id="site-a", repository=repo, identity_service=identity,
        mr_provider=lambda: [_mr(1, "10.0.0.1")], connection_factory=factory,
    )
    collector.collect_from_device(source=source, vlans=[])
    assert created[-1].commands == ["screen-length disable", "display arp"]
    collector.collect_from_device(source=source, vlans=[200, 300])
    assert created[-1].commands == ["screen-length disable", "display arp vlan 200", "display arp vlan 300"]
