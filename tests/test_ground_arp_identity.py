from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from netconsole.parsers.h3c.arp_parser import ArpParseResult, ArpRecord, parse_h3c_arp
from netconsole.repositories.ground_arp_repository import GroundArpRepository
from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.core.paths import PathResolver
from netconsole.services.ground_unattended.arp_collection import GroundArpCollector
from netconsole.services.ground_unattended.arp_identity import GroundMrIdentityService
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor


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


def test_supervisor_reads_all_mrs_when_base_data_is_paginated() -> None:
    rows = [_mr(index, f"10.0.0.{index}") for index in range(1, 251)]

    class InventorySync:
        calls = 0

        def current_mrs(self):
            self.calls += 1
            return rows

    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor.site_id = "site-a"
    supervisor.inventory_sync = InventorySync()

    discovered = supervisor._current_mrs()

    assert len(discovered) == 250
    assert supervisor.inventory_sync.calls == 1


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


def test_open_conflict_blocks_old_confirmed_peer_until_reviewed(tmp_path: Path) -> None:
    repo = GroundArpRepository(tmp_path / "ground.sqlite", site_id="site-a")
    identity = GroundMrIdentityService(repo)
    mr_a = _mr(1, "10.0.0.1")
    mr_b = _mr(2, "10.0.0.2")
    shared_mac = "00:00:00:00:00:aa"
    _success(repo, identity, [_record("10.0.0.1", shared_mac)], [mr_a])
    result = _success(repo, identity, [_record("10.0.0.2", shared_mac)], [mr_a, mr_b])
    assert result["conflict_count"] == 1
    blocked = identity.resolve_peer(shared_mac, [mr_a, mr_b])
    assert blocked.status == "CONFLICT"
    assert blocked.mr_uuid == ""
    conflict = repo.list_conflicts()[0]
    assert repo.resolve_conflict(conflict["conflict_id"])
    resolved = identity.resolve_peer(shared_mac, [mr_a, mr_b])
    assert resolved.status == "CONFIRMED"
    assert resolved.mr_uuid == "mr-1"


def test_mesh_identity_batch_read_is_site_scoped_and_does_not_initialize_missing_db(tmp_path: Path) -> None:
    missing = tmp_path / "missing-ground.sqlite"
    assert GroundArpRepository.find_identity_index_by_mac_readonly(
        missing, site_id="site-a", identity_macs=["00:00:00:00:00:01"]
    ) == {"confirmed": {}, "conflicts": {}}
    assert not missing.exists()

    repo = GroundArpRepository(tmp_path / "ground.sqlite", site_id="site-a")
    identity = GroundMrIdentityService(repo)
    mr = _mr(1, "10.0.0.1")
    _success(repo, identity, [_record("10.0.0.1", "00:00:00:00:00:01")], [mr])
    other_site = GroundArpRepository(tmp_path / "other.sqlite", site_id="site-b")
    other_identity = GroundMrIdentityService(other_site)
    _success(other_site, other_identity, [_record("10.0.0.1", "00:00:00:00:00:02")], [mr])

    index = GroundArpRepository.find_identity_index_by_mac_readonly(
        repo.db_path,
        site_id="site-a",
        identity_macs=["00:00:00:00:00:01", "00:00:00:00:00:02"],
    )
    assert {row["mr_uuid"] for row in index["confirmed"]["00:00:00:00:00:01"]} == {"mr-1"}
    assert "00:00:00:00:00:02" not in index["confirmed"]


def test_identity_observation_projection_uses_one_read_connection_for_many_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "ground.sqlite"
    repo = GroundArpRepository(path, site_id="site-a")
    identity = GroundMrIdentityService(repo)
    mrs = [_mr(index, f"10.0.0.{index}") for index in range(1, 51)]
    records = [_record(mr["management_ip"], f"00:00:00:00:01:{index:02x}") for index, mr in enumerate(mrs, 1)]
    _success(repo, identity, records, mrs)

    calls = 0
    original = Database.connect_readonly

    def tracked(database: Database):
        nonlocal calls
        calls += 1
        return original(database)

    monkeypatch.setattr(Database, "connect_readonly", tracked)
    projection = repo.build_identity_observation_projection(
        mr_uuids=[mr["id"] for mr in mrs],
        ip_addresses=[record.ip_address for record in records],
    )

    assert calls == 1
    assert len(projection["relations_by_mr"]) == len(mrs)
    assert len(projection["observations_by_ip"]) == len(records)


def test_h3c_derived_peer_conflict_is_not_auto_selected(tmp_path: Path) -> None:
    repo = GroundArpRepository(tmp_path / "ground.sqlite", site_id="site-a")
    identity = GroundMrIdentityService(repo)
    mr = _mr(1, "10.0.0.1", "00:11:22:33:44:50")
    identity.register_mr_registry([mr])
    derived = next(row["identity_mac"] for row in repo.find_identity_relations(mr_uuid="mr-1") if row["alias_type"] == "DERIVED_R1")
    repo.save_conflict(
        conflict_type="MAC_MULTIPLE_MR", conflict_key=f"MAC_MULTIPLE_MR:{derived}",
        mac_address=derived, details={"mr_uuids": ["mr-1", "mr-2"]},
    )
    resolved = identity.resolve_peer(derived, [mr])
    assert resolved.status == "CONFLICT"
    assert resolved.mr_uuid == ""


def test_startup_arp_is_scoped_to_running_session() -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor._run_session_id = "session-1"
    supervisor._arp_startup_session_id = ""
    supervisor._arp_future = None
    supervisor._arp_next_poll_monotonic = 0.0
    supervisor._arp_last_error = ""
    calls: list[str] = []
    supervisor.request_arp_refresh = lambda *, reason: calls.append(reason)  # type: ignore[method-assign]
    profile = SimpleNamespace(
        arp_collection_device_uuid="switch-1",
        arp_management_vlans=[],
        arp_startup_collection_enabled=True,
        arp_auto_refresh_enabled=False,
        arp_auto_refresh_interval_seconds=300,
    )

    supervisor._schedule_arp_poll(profile, None)
    assert calls == []
    assert supervisor._arp_startup_session_id == ""
    supervisor._schedule_arp_poll(profile, {"run_id": "run-1", "state": "RUNNING"})
    supervisor._schedule_arp_poll(profile, {"run_id": "run-1", "state": "RUNNING"})
    assert calls == ["startup"]
    supervisor._run_session_id = "session-2"
    supervisor._schedule_arp_poll(profile, {"run_id": "run-1", "state": "RUNNING"})
    assert calls == ["startup", "startup"]


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
