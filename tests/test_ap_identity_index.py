from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_identity import (
    ApIdentityQueryService,
    format_mac,
    mac_prefix,
    normalize_mac_key,
)


def _fixture(tmp_path: Path) -> tuple[Database, AcRepository, ApIdentityQueryService]:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database, AcRepository(database), ApIdentityQueryService(database)


def _base_ap(
    repository: AcRepository,
    *,
    name: str,
    mac: str,
    station: str = "明珠广场",
) -> dict[str, object | None]:
    return repository.upsert_ap_extension_point(
        {
            "ap_name": name,
            "ap_point_code": name,
            "ap_vendor": "H3C",
            "ap_mac_display": mac,
            "station_name": station,
            "belong_type": "station",
        }
    )


def test_mac_fact_source_uses_key_and_h3c_display() -> None:
    values = (
        "48:73:97:cc:e0:e0",
        "48-73-97-cc-e0-e0",
        "4873.97cc.e0e0",
        "487397cce0e0",
        "4873-97cc-e0e0",
    )

    assert {normalize_mac_key(value) for value in values} == {"487397cce0e0"}
    assert {format_mac(value) for value in values} == {"4873-97cc-e0e0"}
    assert mac_prefix(values[0], 36) == "487397cce"


def test_database_initializes_identity_index_idempotently(tmp_path: Path) -> None:
    database, _repository, service = _fixture(tmp_path)
    initial = service.index_state()
    first = service.rebuild_index("test_empty")

    database.initialize()
    second = service.rebuild_index("test_repeat")

    assert initial is not None
    assert initial["revision"] == 0
    assert first.entity_count == 0
    assert second.revision == first.revision + 1


def test_zero_source_revision_is_a_valid_current_index(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)

    built = service.rebuild_index("empty_source")
    match = service.resolve_peer_mac("642f-c778-ef5f")

    assert built.source_revision == 0
    assert service.index_state()["source_revision"] == 0
    assert (
        repository.trackside_online_status_revision()["identity_source_revision"] == 0
    )
    assert match.status == "unresolved"
    assert match.unresolved_reason == "exact_alias_not_collected"


def test_revision_state_reports_missing_ready_and_stale_without_exposing_rows(
    tmp_path: Path,
) -> None:
    _database, repository, service = _fixture(tmp_path)

    missing = service.revision_state()
    assert missing.status == "missing"
    assert missing.revision == 0
    assert missing.indexed_source_revision == -1
    assert missing.current_source_revision == 0
    assert missing.revision_token == "0:-1:0:missing"

    built = service.rebuild_index("empty_source")
    ready = service.revision_state()
    assert ready.status == "ready"
    assert ready.revision == built.revision
    assert ready.indexed_source_revision == 0
    assert ready.current_source_revision == 0
    assert ready.revision_token == f"{built.revision}:0:0:ready"
    assert service.revision_state() == ready

    _base_ap(repository, name="AP-A", mac="74ad-cb9d-3320")
    stale = service.revision_state()
    assert stale.status == "stale"
    assert stale.revision == built.revision
    assert stale.indexed_source_revision == 0
    assert stale.current_source_revision > 0
    assert stale.revision_token == (
        f"{built.revision}:0:{stale.current_source_revision}:stale"
    )


def test_topology_projection_version_marks_legacy_index_stale_and_rebuilds(
    tmp_path: Path,
) -> None:
    database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-A", mac="74ad-cb9d-3320")
    built = service.rebuild_index("initial")

    with database.connect() as connection:
        connection.execute(
            "UPDATE ap_identity_index_state SET diagnostics_json = '{}' WHERE site_id = 'current'"
        )
        connection.commit()

    stale = service.revision_state()
    match = service.resolve_peer_mac("74ad-cb9d-332f")
    rebuilt = service.ensure_index("topology_projection_upgrade")

    assert stale.status == "stale"
    assert match.status == "unresolved"
    assert match.unresolved_reason == "identity_topology_projection_stale"
    assert rebuilt is not None
    assert rebuilt.revision == built.revision + 1
    assert service.revision_state().status == "ready"
    assert service.resolve_peer_mac("74ad-cb9d-332f").status == "matched"


def test_legacy_identity_state_schema_is_upgraded_before_new_columns_are_used(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "ALTER TABLE ap_identity_index_state DROP COLUMN source_revision"
        )
        connection.execute(
            "ALTER TABLE ap_identity_index_state DROP COLUMN actual_radio_alias_count"
        )
        connection.execute(
            "ALTER TABLE ap_identity_index_state DROP COLUMN actual_bssid_alias_count"
        )
        connection.execute(
            "ALTER TABLE ap_identity_index_state DROP COLUMN actual_bbssid_alias_count"
        )
        connection.execute(
            "ALTER TABLE ap_identity_index_state DROP COLUMN derived_alias_count"
        )
        connection.execute(
            "ALTER TABLE ap_identity_index_state DROP COLUMN ambiguous_alias_count"
        )
        connection.execute(
            "ALTER TABLE ap_identity_index_state DROP COLUMN build_duration_ms"
        )
        connection.execute(
            "ALTER TABLE ap_identity_index_state DROP COLUMN diagnostics_json"
        )
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(ap_identity_index_state)"
            ).fetchall()
        }
        row = connection.execute(
            "SELECT source_revision, revision FROM ap_identity_index_state WHERE site_id = 'current'"
        ).fetchone()

    assert {
        "source_revision",
        "actual_radio_alias_count",
        "actual_bssid_alias_count",
        "actual_bbssid_alias_count",
        "derived_alias_count",
        "ambiguous_alias_count",
        "build_duration_ms",
        "diagnostics_json",
    } <= columns
    assert row is not None
    assert row["source_revision"] == -1
    assert row["revision"] == 0
    with database.connect_readonly() as connection:
        names = {
            str(row["name"])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'ap_identity_%'
                """
            ).fetchall()
        }
    assert names >= {
        "ap_identity_entities",
        "ap_identity_mac_aliases",
        "ap_identity_h3c_prefixes",
        "ap_identity_conflicts",
        "ap_identity_index_state",
    }


def test_source_write_marks_index_stale_until_explicit_rebuild(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-A", mac="74ad-cb9d-3320")
    first = service.rebuild_index("initial")

    _base_ap(repository, name="AP-B", mac="74ad-cb9d-3340")

    stale = service.resolve_peer_mac("74ad-cb9d-332f")
    stale_batch = service.resolve_peer_macs(["74ad-cb9d-332f", "invalid"])
    assert stale.status == "unresolved"
    assert stale.unresolved_reason == "identity_index_stale"
    assert stale_batch.revision == first.revision
    assert stale_batch.index_status == "identity_index_stale"
    assert stale_batch.unresolved_count == 1
    assert stale_batch.invalid_count == 1
    assert stale_batch["74adcb9d332f"].identity_revision == first.revision
    assert service.index_state()["revision"] == first.revision

    service.rebuild_index("source_changed")
    assert service.resolve_peer_mac("74ad-cb9d-332f").status == "matched"


def test_source_revision_only_tracks_devices_used_as_fit_ap_controllers(
    tmp_path: Path,
) -> None:
    database, repository, service = _fixture(tmp_path)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                created_at, updated_at
            )
            VALUES ('switch-1', 'SW', 'H3C', 'Switch', '10.0.0.10', '', '')
            """
        )
        connection.execute(
            """
            INSERT INTO device_facts (
                device_uuid, model, software_version, collected_at, updated_at
            )
            VALUES ('switch-1', 'S5560', 'V7', '', '')
            """
        )
        connection.commit()
    initial_revision = service.repository.source_revision()

    with database.connect() as connection:
        connection.execute(
            "UPDATE devices SET name = 'SW-UPDATED' WHERE device_uuid = 'switch-1'"
        )
        connection.execute(
            "UPDATE device_facts SET model = 'S6520' WHERE device_uuid = 'switch-1'"
        )
        connection.commit()

    assert service.repository.source_revision() == initial_revision

    repository.replace_fit_ap_resources(
        "ac-1",
        [{"ap_uuid": "ap-1", "ap_name": "AP-1", "ap_mac": "74ad-cb9d-3320"}],
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                created_at, updated_at
            )
            VALUES ('ac-1', 'AC', '', 'AC', '10.0.0.1', '', '')
            """
        )
        connection.commit()
    before_vendor_update = service.repository.source_revision()

    with database.connect() as connection:
        connection.execute(
            "UPDATE devices SET device_vendor = 'H3C' WHERE device_uuid = 'ac-1'"
        )
        connection.execute(
            """
            INSERT INTO device_facts (
                device_uuid, model, software_version, collected_at, updated_at
            )
            VALUES ('ac-1', 'WX', 'V7', '', '')
            """
        )
        connection.commit()

    assert service.repository.source_revision() == before_vendor_update + 1


def test_source_revision_ignores_legacy_lldp_history_but_tracks_current_lldp(
    tmp_path: Path,
) -> None:
    database, _repository, service = _fixture(tmp_path)
    initial_revision = service.repository.source_revision()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_fit_ap_lldp_history (
                ac_device_uuid, ap_uuid, collected_at, created_at
            )
            VALUES ('ac-1', 'ap-1', '2026-08-16T00:00:00+00:00', '')
            """
        )
        connection.commit()
    assert service.repository.source_revision() == initial_revision

    with database.connect() as connection:
        connection.execute("DELETE FROM ac_fit_ap_lldp_history")
        connection.commit()
    assert service.repository.source_revision() == initial_revision

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO device_lldp_neighbors (
                device_uuid, local_interface, neighbor_mac,
                collected_at, updated_at
            )
            VALUES (
                'switch-1', 'GigabitEthernet1/0/1', '74ad-cb9d-3320',
                '2026-08-16T00:00:00+00:00', ''
            )
            """
        )
        connection.commit()

    assert service.repository.source_revision() == initial_revision + 1


def test_failed_build_preserves_previous_index(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-A", mac="74ad-cb9d-3320")
    first = service.rebuild_index("initial")

    def fail_builder(*_args, **_kwargs):
        raise RuntimeError("synthetic build failure")

    with pytest.raises(RuntimeError, match="synthetic build failure"):
        service.repository.rebuild_index(
            fail_builder,
            site_id="current",
            reason="failure",
        )

    state = service.index_state()
    assert state["revision"] == first.revision
    assert service.resolve_peer_mac("74ad-cb9d-332f").status == "matched"


def test_base_data_alone_resolves_exact_h3c_radio_alias(tmp_path: Path) -> None:
    database, repository, service = _fixture(tmp_path)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                created_at, updated_at
            )
            VALUES ('ac-h3c', 'AC', 'H3C', 'AC', '10.0.0.1', '', '')
            """
        )
        connection.commit()
    _base_ap(repository, name="AP0208", mac="74ad-cb9d-3320")

    built = service.rebuild_index("base_data_saved")
    match = service.resolve_peer_mac("74:ad:cb:9d:33:2f")

    assert built.ac_record_count == 0
    assert match.status == "matched"
    assert match.query_mac == "74adcb9d332f"
    assert match.query_mac_display == "74ad-cb9d-332f"
    assert match.effective_ap_name == "AP0208"
    assert match.effective_ap_mac == "74ad-cb9d-3320"
    assert match.station == "明珠广场"
    assert match.matched_alias_type == "h3c_r1_derived"
    assert match.matched_source == "base_data"
    assert match.match_rule == "h3c_physical_mac_to_r1_exact_v1"
    assert match.radio_id == 1


def test_field_peer_radio_resolves_to_physical_ap(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(
        repository,
        name="bc5a-3457-6d40",
        mac="bc5a-3457-6d40",
        station="云龙车辆段",
    )

    service.rebuild_index("field_peer_radio")
    match = service.resolve_peer_mac("bc5a-3457-6d4f")

    assert match.status == "matched"
    assert match.effective_ap_mac == "bc5a-3457-6d40"
    assert match.effective_ap_name == "bc5a-3457-6d40"
    assert match.station == "云龙车辆段"
    assert match.radio_id == 1


def test_ap_identity_uses_lldp_switch_station_without_base_record(tmp_path: Path) -> None:
    database, repository, service = _fixture(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-live",
                "ap_name": "AP-LIVE",
                "ap_mac": "74ad-cb9d-3320",
                "site": "",
            }
        ],
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                created_at, updated_at
            ) VALUES ('ac-1', 'AC-1', 'H3C', 'AC', '10.0.0.1', '', '')
            """
        )
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, station, station_id, device_type,
                primary_address, created_at, updated_at
            ) VALUES ('switch-live', 'SW-LIVE', '现场站', 'station:live', 'SWITCH', '10.0.0.10', '', '')
            """
        )
        connection.execute(
            """
            INSERT INTO device_lldp_neighbors (
                device_uuid, local_interface, neighbor_mac, collected_at,
                collect_run_uuid, updated_at
            ) VALUES ('switch-live', 'GigabitEthernet1/0/1', '74ad-cb9d-3320', '', 'run-1', '')
            """
        )
        connection.commit()

    service.rebuild_index("lldp_topology")
    match = service.resolve_peer_mac("74ad-cb9d-332f", ap_role="trackside")

    assert match.status == "matched"
    assert match.station == "现场站"
    assert match.station_source == "lldp_switch"
    assert match.topology_warning == ""


def test_ap_identity_keeps_same_station_lldp_evidence_from_multiple_switches(
    tmp_path: Path,
) -> None:
    database, repository, service = _fixture(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-live",
                "ap_name": "bc5a-3457-61e0",
                "ap_mac": "bc5a-3457-61e0",
                "site": "",
            }
        ],
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                created_at, updated_at
            ) VALUES ('ac-1', 'AC-1', 'H3C', 'AC', '10.0.0.1', '', '')
            """
        )
        connection.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, station, station_id, device_type,
                primary_address, created_at, updated_at
            ) VALUES (?, ?, '横溪站', 'station:hengxi', 'SWITCH', ?, '', '')
            """,
            [
                ("switch-hx-1", "HX_1", "10.0.0.11"),
                ("switch-hx-2", "HX_2", "10.0.0.12"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO device_lldp_neighbors (
                device_uuid, local_interface, neighbor_mac, collected_at,
                collect_run_uuid, updated_at
            ) VALUES (?, ?, 'bc5a-3457-61e0', '', ?, '')
            """,
            [
                ("switch-hx-1", "GigabitEthernet1/0/1", "run-old"),
                ("switch-hx-2", "GigabitEthernet1/0/2", "run-current"),
            ],
        )
        connection.commit()

    service.rebuild_index("same_station_multiple_switches")
    match = service.resolve_peer_mac("bc5a-3457-61ff", ap_role="trackside")

    assert match.status == "matched"
    assert match.effective_ap_name == "bc5a-3457-61e0"
    assert match.station == "横溪站"
    assert match.station_source == "lldp_switch"
    assert match.topology_warning == "topology_lldp_multiple_switches"


def test_offline_fit_ap_keeps_exact_h3c_radio2_alias(tmp_path: Path) -> None:
    database, repository, service = _fixture(tmp_path)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                created_at, updated_at
            )
            VALUES ('ac-h3c', 'AC', 'H3C', 'AC', '10.0.0.1', '', '')
            """
        )
        connection.commit()
    repository.replace_fit_ap_resources(
        "ac-h3c",
        [
            {
                "ap_uuid": "offline-ap",
                "ap_name": "AP-OFFLINE",
                "apid": "11",
                "ap_mac": "bc5a-3457-b5e0",
                "serial_number": "SN-OFFLINE",
                "ap_ip": "10.1.1.11",
                "state": "R/M",
            }
        ],
    )
    repository.replace_fit_ap_resources(
        "ac-h3c",
        [
            {
                "ap_name": "AP-OFFLINE",
                "apid": "11",
                "ap_mac": None,
                "serial_number": None,
                "ap_ip": None,
                "state": "I",
            }
        ],
    )

    service.rebuild_index("offline_fit_ap_refresh")
    match = service.resolve_peer_mac("bc5a-3457-b5ff")
    current = repository.list_fit_ap_resources("ac-h3c")[0]

    assert current["ap_uuid"] == "offline-ap"
    assert current["ap_mac"] == "bc5a-3457-b5e0"
    assert current["ap_ip"] is None
    assert match.status == "matched"
    assert match.effective_ap_name == "AP-OFFLINE"
    assert match.effective_ap_mac == "bc5a-3457-b5e0"
    assert match.matched_alias_type == "h3c_r2_derived"
    assert match.radio_id == 2


def test_base_data_h3c_alias_allows_unknown_vendor_but_rejects_non_h3c_and_non_physical_mac(
    tmp_path: Path,
) -> None:
    database, repository, service = _fixture(tmp_path)
    base = _base_ap(repository, name="AP-NO-VENDOR", mac="74ad-cb9d-3320")
    with database.connect() as connection:
        connection.execute(
            "UPDATE ap_extension_points SET ap_vendor = '' WHERE id = ?",
            (base["id"],),
        )
        connection.commit()
    repository.replace_fit_ap_resources(
        "zte-ac",
        [{"ap_uuid": "zte-ap", "ap_name": "ZTE-AP", "ap_mac": "0011-2233-4450"}],
    )
    repository.replace_fit_ap_resources(
        "h3c-ac",
        [
            {"ap_uuid": "radio-input", "ap_name": "RADIO", "ap_mac": "aabb-ccdd-eeff"},
            {"ap_uuid": "not-physical", "ap_name": "ODD", "ap_mac": "aabb-ccdd-eee1"},
        ],
    )
    with database.connect() as connection:
        connection.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 'AC', ?, '', '')
            """,
            (
                ("zte-ac", "ZTE AC", "ZTE", "10.0.0.2"),
                ("h3c-ac", "H3C AC", "H3C", "10.0.0.3"),
            ),
        )
        connection.commit()

    service.rebuild_index("vendor_and_physical_mac_guard")

    base_match = service.resolve_peer_mac("74ad-cb9d-332f")
    assert base_match.status == "matched"
    assert base_match.matched_source == "base_data"
    assert base_match.radio_id == 1
    assert service.resolve_peer_mac("0011-2233-445f").status == "unresolved"
    assert service.resolve_peer_mac("aabb-ccdd-efff").status == "unresolved"
    assert service.resolve_peer_mac("aabb-ccdd-eeef").status == "unresolved"


def test_peer_resolution_can_be_scoped_to_trackside_role(tmp_path: Path) -> None:
    database, repository, service = _fixture(tmp_path)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                created_at, updated_at
            )
            VALUES ('ac-h3c', 'AC', 'H3C', 'AC', '10.0.0.1', '', '')
            """
        )
        connection.commit()
    repository.replace_fit_ap_resources(
        "ac-h3c",
        [
            {
                "ap_uuid": "onboard-ap",
                "ap_name": "ONBOARD-AP",
                "ap_mac": "74ad-cb9d-3320",
                "site": "车载",
            }
        ],
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_fit_ap_metadata (
                ap_uuid, ap_name, belong_type, created_at, updated_at
            )
            VALUES (
                'onboard-ap', 'ONBOARD-AP', 'onboard',
                '2026-07-31T00:00:00', '2026-07-31T00:00:00'
            )
            """
        )
        connection.commit()
    service.rebuild_index("role_scope")

    assert service.resolve_peer_mac("74ad-cb9d-332f").status == "matched"
    assert (
        service.resolve_peer_mac("74ad-cb9d-332f", ap_role="trackside").status
        == "unresolved"
    )
    assert (
        service.resolve_peer_mac("74ad-cb9d-332f", ap_role="onboard").status
        == "matched"
    )
    assert (
        service.resolve_peer_macs(
            ["74ad-cb9d-332f"],
            ap_role="trackside",
        )["74adcb9d332f"].status
        == "unresolved"
    )
    assert (
        service.resolve_peer_macs(
            ["74ad-cb9d-332f"],
            ap_role="onboard",
        )["74adcb9d332f"].status
        == "matched"
    )


def test_same_h3c_prefix_without_exact_alias_is_unresolved(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-A", mac="4873-97cc-e0e0")
    _base_ap(repository, name="AP-B", mac="4873-97cc-e1e0")
    service.rebuild_index("base_data_saved")

    match = service.resolve_peer_mac("4873-97cc-e9af")

    assert match.status == "unresolved"
    assert match.candidates == ()
    assert match.unresolved_reason == "exact_alias_not_found"


def test_duplicate_exact_h3c_alias_is_ambiguous(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-A", mac="74ad-cb9d-3320")
    _base_ap(repository, name="AP-B", mac="74ad-cb9d-3330")
    service.rebuild_index("base_data_saved")

    match = service.resolve_peer_mac("74ad-cb9d-333f")

    assert match.status == "ambiguous"
    assert {row["ap_name"] for row in match.candidates} == {"AP-A", "AP-B"}


def test_mesh_peer_does_not_fall_back_to_prefix_name_or_base_ap_mac(
    tmp_path: Path,
) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP2011", mac="64:2f:c7:78:ed:a0")
    service.rebuild_index("base_data_saved")

    prefix_only = service.resolve_peer_mac(
        "642f-c778-ef5f",
        peer_name="AP2011",
    )
    exact_base = service.resolve_peer_mac(
        "642f-c778-eda0",
        peer_name="AP2011",
    )

    assert prefix_only.status == "unresolved"
    assert prefix_only.effective_ap_name == ""
    assert prefix_only.effective_ap_mac == ""
    assert exact_base.status == "unresolved"


def test_batch_query_preserves_peer_and_ap_semantics_with_one_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-A", mac="74ad-cb9d-3320")
    _base_ap(repository, name="AP-B", mac="74ad-cb9d-3330")
    built = service.rebuild_index("base_data_saved")
    single_ap_match = service.resolve_ap_mac("74ad-cb9d-3320")
    snapshot_calls = 0
    original_snapshot = service.repository.exact_alias_snapshot

    def counted_snapshot(*args, **kwargs):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(
        service.repository,
        "exact_alias_snapshot",
        counted_snapshot,
    )
    monkeypatch.setattr(
        service.repository,
        "exact_alias_rows",
        lambda *_args, **_kwargs: pytest.fail(
            "batch query must not issue one alias query per MAC"
        ),
    )
    monkeypatch.setattr(
        service.repository,
        "index_health",
        lambda **_kwargs: pytest.fail(
            "batch query must read health from the same snapshot"
        ),
    )

    peer_matches = service.resolve_peer_macs(
        [
            "74ad-cb9d-332f",
            "74ad-cb9d-333f",
            "74ad-cb9d-3320",
            "74:ad:cb:9d:33:2f",
            "invalid",
        ],
        ap_role="trackside",
    )
    ap_matches = service.resolve_ap_macs(["74ad-cb9d-3320", "74ad-cb9d-3320"])

    assert snapshot_calls == 2
    assert set(peer_matches) == {
        "74adcb9d332f",
        "74adcb9d333f",
        "74adcb9d3320",
    }
    assert peer_matches["74adcb9d332f"].status == "matched"
    assert peer_matches["74adcb9d333f"].status == "ambiguous"
    assert peer_matches["74adcb9d3320"].status == "unresolved"
    assert ap_matches["74adcb9d3320"].status == "matched"
    assert peer_matches.revision == built.revision
    assert peer_matches.index_status == "ready"
    assert peer_matches.requested_count == 5
    assert peer_matches.normalized_count == 4
    assert peer_matches.distinct_count == 3
    assert peer_matches.matched_count == 1
    assert peer_matches.unresolved_count == 1
    assert peer_matches.ambiguous_count == 1
    assert peer_matches.invalid_count == 1
    assert ap_matches.requested_count == 2
    assert ap_matches.normalized_count == 2
    assert ap_matches.distinct_count == 1
    assert ap_matches.matched_count == 1
    assert ap_matches["74adcb9d3320"] == single_ap_match
    assert {
        match.identity_revision
        for match in (*peer_matches.values(), *ap_matches.values())
    } == {built.revision}


def test_batch_query_counts_empty_and_invalid_input_without_database_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database, _repository, service = _fixture(tmp_path)
    monkeypatch.setattr(
        service.repository,
        "exact_alias_snapshot",
        lambda *_args, **_kwargs: pytest.fail(
            "empty or invalid batches must not query SQLite"
        ),
    )

    empty = service.resolve_peer_macs([])
    invalid = service.resolve_peer_macs([None, "", "not-a-mac"])

    assert dict(empty) == {}
    assert empty.index_status == "not_checked"
    assert empty.requested_count == 0
    assert empty.normalized_count == 0
    assert empty.distinct_count == 0
    assert empty.invalid_count == 0
    assert dict(invalid) == {}
    assert invalid.index_status == "not_checked"
    assert invalid.requested_count == 3
    assert invalid.normalized_count == 0
    assert invalid.distinct_count == 0
    assert invalid.invalid_count == 3


def test_large_batch_uses_one_repository_snapshot_instead_of_n_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database, _repository, service = _fixture(tmp_path)
    service.rebuild_index("empty_source")
    snapshot_calls = 0
    original_snapshot = service.repository.exact_alias_snapshot

    def counted_snapshot(*args, **kwargs):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(
        service.repository,
        "exact_alias_snapshot",
        counted_snapshot,
    )
    monkeypatch.setattr(
        service.repository,
        "exact_alias_rows",
        lambda *_args, **_kwargs: pytest.fail(
            "large batch must not issue one alias query per MAC"
        ),
    )
    macs = [f"{index:012x}" for index in range(1, 1002)]

    result = service.resolve_peer_macs(macs)

    assert snapshot_calls == 1
    assert result.requested_count == 1001
    assert result.normalized_count == 1001
    assert result.distinct_count == 1001
    assert result.unresolved_count == 1001
    assert result.index_status == "ready"


def test_ac_actual_radio_alias_wins_over_derived_prefix(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP0208", mac="4873-97cc-e0e0")
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-ac-0208",
                "ap_name": "AP0208",
                "ap_mac": "4873-97cc-e0e0",
                "site": "明珠广场",
                "rid1_bbssid": "4873-97cc-e9af",
            }
        ],
    )
    service.rebuild_index("ac_refresh_succeeded")

    match = service.resolve_peer_mac("48:73:97:cc:e9:af")

    assert match.status == "matched"
    assert match.matched_alias_type == "ac_bbssid"
    assert match.matched_source == "ac_runtime"
    assert match.match_rule == "actual_bbssid_exact"
    assert match.radio_id == 1
    assert match.effective_ap_mac == "4873-97cc-e0e0"


def test_same_name_different_mac_stays_as_two_physical_entities(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP0208", mac="4873-97cc-e0e0")
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-ac-0208",
                "ap_name": "AP0208",
                "ap_mac": "4873-97cc-e080",
                "site": "明珠广场",
                "rid1_bbssid": "4873-97cc-e9af",
            }
        ],
    )
    service.rebuild_index("ac_refresh_succeeded")

    match = service.resolve_peer_mac("487397cce9af")
    conflicts = service.list_conflicts()

    assert match.status == "matched"
    assert match.effective_ap_mac == "4873-97cc-e080"
    assert match.ac_ap_mac == "4873-97cc-e080"
    assert match.base_ap_mac == ""
    assert match.matched_source == "ac_runtime"
    assert not match.has_conflict
    assert match.data_quality_warning == ""
    assert conflicts == []


def test_base_data_match_survives_ac_disappearance(tmp_path: Path) -> None:
    database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP0208", mac="4873-97cc-e0e0")
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-ac-0208",
                "ap_name": "AP0208",
                "ap_mac": "4873-97cc-e0e0",
                "rid1_bbssid": "4873-97cc-e9af",
            }
        ],
    )
    service.rebuild_index("ac_refresh_succeeded")
    with database.connect() as connection:
        connection.execute(
            "DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ?",
            ("ac-1",),
        )
        connection.commit()

    service.rebuild_index("ac_resource_disappeared")
    match = service.resolve_peer_mac("4873-97cc-e0ef")

    assert match.status == "matched"
    assert match.matched_source == "base_data"
    assert match.effective_ap_name == "AP0208"


def test_same_mac_ac_and_base_merge_to_one_physical_entity(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-BASE", mac="0011-2233-4455")
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-ac-1",
                "ap_name": "AP-AC",
                "ap_mac": "00:11:22:33:44:55",
                "rid1_bbssid": "0011-2233-4a55",
            }
        ],
    )

    built = service.rebuild_index("ac_refresh_succeeded")
    match = service.resolve_mac("0011-2233-4a55")

    assert built.entity_count == 1
    assert match.status == "matched"
    assert match.effective_ap_name == "AP-AC"
    assert match.effective_ap_mac == "0011-2233-4455"
    assert match.base_ap_mac == "0011-2233-4455"


def test_legacy_cache_is_exact_only_and_not_counted_as_ac(tmp_path: Path) -> None:
    database, _repository, service = _fixture(tmp_path)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_fit_ap_optical (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, site, updated_at
            ) VALUES (
                'ac-legacy', 'legacy-ap-1', 'AP-LEGACY',
                '4873-97cc-e0e0', '历史站', '2026-07-30T00:00:00+00:00'
            )
            """
        )
        connection.commit()

    built = service.rebuild_index("legacy_compatibility_loaded")
    exact = service.resolve_mac("487397cce0e0")
    derived = service.resolve_mac("487397cce9af")

    assert built.ac_record_count == 0
    assert exact.status == "matched"
    assert exact.matched_alias_type == "legacy_mac"
    assert exact.matched_source == "legacy_cache"
    assert exact.station == "历史站"
    assert derived.status == "unresolved"


def test_legacy_cache_attaches_to_ac_without_overriding_effective_identity(
    tmp_path: Path,
) -> None:
    database, repository, service = _fixture(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-1",
                "ap_name": "AP-RUNTIME",
                "ap_mac": "0011-2233-4455",
                "site": "运行站",
            }
        ],
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_fit_ap_optical (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, site, updated_at
            ) VALUES (
                'ac-1', 'ap-1', 'AP-OLD',
                'aabb-ccdd-eeff', '历史站', '2026-07-29T00:00:00+00:00'
            )
            """
        )
        connection.commit()

    built = service.rebuild_index("ac_refresh_succeeded")
    match = service.resolve_mac("aabbccddeeff")

    assert built.entity_count == 1
    assert built.ac_record_count == 1
    assert match.status == "matched"
    assert match.matched_source == "legacy_cache"
    assert match.effective_ap_name == "AP-RUNTIME"
    assert match.effective_ap_mac == "0011-2233-4455"
    assert match.station == "运行站"


def test_actual_ac_bbssid_wins_over_other_entity_base_prefix(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-BASE", mac="4873-97cc-e0e0")
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-runtime",
                "ap_name": "AP-RUNTIME",
                "ap_mac": "0011-2233-4455",
                "rid1_bbssid": "4873-97cc-e9af",
            }
        ],
    )
    service.rebuild_index("ac_refresh_succeeded")

    match = service.resolve_mac("487397cce9af")

    assert match.status == "matched"
    assert match.effective_ap_name == "AP-RUNTIME"
    assert match.matched_alias_type == "ac_bbssid"
    assert match.match_rule == "actual_bbssid_exact"


def test_radio_evidence_backfill_survives_legacy_history_retirement(
    tmp_path: Path,
) -> None:
    database, repository, service = _fixture(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-runtime",
                "ap_name": "AP-RUNTIME",
                "ap_mac": "0011-2233-4455",
            }
        ],
    )
    with database.connect() as connection:
        source_revision_before_backfill = int(
            connection.execute(
                "SELECT revision FROM ap_identity_source_state WHERE site_id='current'"
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO ac_fit_ap_radio_history (
                ac_device_uuid, ap_uuid, ap_name, rid, bbssid,
                collected_at, created_at
            )
            VALUES (
                'ac-1', 'ap-runtime', 'AP-RUNTIME', 1,
                '4873-97cc-e9af', '2026-08-01T00:00:00+00:00',
                '2026-08-01T00:00:00+00:00'
            )
            """
        )
        connection.execute("DROP TABLE ap_identity_radio_evidence")
        connection.commit()

    database.initialize()
    with database.connect() as connection:
        source_revision_after_backfill = int(
            connection.execute(
                "SELECT revision FROM ap_identity_source_state WHERE site_id='current'"
            ).fetchone()[0]
        )
    service.rebuild_index("radio_evidence_backfill")
    before = service.resolve_peer_mac("487397cce9af")
    with database.connect() as connection:
        evidence = connection.execute(
            """
            SELECT ap_uuid, rid, bbssid
            FROM ap_identity_radio_evidence
            """
        ).fetchone()
        revision_before = connection.execute(
            "SELECT revision FROM ap_identity_source_state WHERE site_id='current'"
        ).fetchone()[0]
        connection.execute("DELETE FROM ac_fit_ap_radio_history")
        connection.commit()
        revision_after = connection.execute(
            "SELECT revision FROM ap_identity_source_state WHERE site_id='current'"
        ).fetchone()[0]

    service.rebuild_index("legacy_radio_history_retired")
    after = service.resolve_peer_mac("487397cce9af")

    assert tuple(evidence) == ("ap-runtime", 1, "4873-97cc-e9af")
    assert source_revision_after_backfill == source_revision_before_backfill
    assert revision_after == revision_before
    assert before.status == after.status == "matched"
    assert before.matched_entity_id == after.matched_entity_id
    assert before.matched_alias_type == after.matched_alias_type == "ac_bbssid"
    assert before.match_rule == after.match_rule == "actual_bbssid_exact"


def test_radio_evidence_backfills_from_verified_identity_aliases(
    tmp_path: Path,
) -> None:
    database, repository, service = _fixture(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-runtime",
                "ap_name": "AP-RUNTIME",
                "ap_mac": "0011-2233-4455",
            }
        ],
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_fit_ap_radio_history (
                ac_device_uuid, ap_uuid, ap_name, rid, bbssid,
                collected_at, created_at
            )
            VALUES (
                'ac-1', 'ap-runtime', 'AP-RUNTIME', 2,
                '4873-97cc-e9bf', '2026-08-01T00:00:00+00:00',
                '2026-08-01T00:00:00+00:00'
            )
            """
        )
        connection.execute("DROP TABLE ap_identity_radio_evidence")
        connection.commit()
    service.rebuild_index("legacy_radio_alias")

    with database.connect() as connection:
        connection.execute("DELETE FROM ac_fit_ap_radio_history")
        connection.commit()

    database.initialize()
    with database.connect() as connection:
        evidence = connection.execute(
            """
            SELECT ap_uuid, rid, bbssid
            FROM ap_identity_radio_evidence
            """
        ).fetchone()
    service.rebuild_index("verified_alias_fallback")
    match = service.resolve_peer_mac("487397cce9bf")

    assert tuple(evidence) == ("ap-runtime", 2, "4873-97cc-e9bf")
    assert match.status == "matched"
    assert match.matched_entity_id == "ac:ap-runtime"
    assert match.radio_id == 2


def test_radio_evidence_changes_only_for_semantic_bbssid_changes(
    tmp_path: Path,
) -> None:
    database, repository, _service = _fixture(tmp_path)

    def append(bbssid: str, collected_at: str) -> tuple[int, int, str, str]:
        with database.connect() as connection:
            repository._append_radio_history(
                connection,
                {
                    "ac_device_uuid": "ac-1",
                    "ap_uuid": "ap-runtime",
                    "ap_name": "AP-RUNTIME",
                    "rid1_bbssid": bbssid,
                    "collected_at": collected_at,
                },
            )
            connection.commit()
            revision = int(
                connection.execute(
                    "SELECT revision FROM ap_identity_source_state "
                    "WHERE site_id='current'"
                ).fetchone()[0]
            )
            history_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM fit_ap_radio_history "
                    "WHERE ap_uuid='ap-runtime' AND radio_id=1"
                ).fetchone()[0]
            )
            evidence = connection.execute(
                """
                SELECT bbssid, updated_at
                FROM ap_identity_radio_evidence
                WHERE ap_uuid='ap-runtime' AND rid=1
                """
            ).fetchone()
        return revision, history_count, str(evidence["bbssid"]), str(evidence["updated_at"])

    first = append("48:73:97:cc:e9:af", "2026-08-01T00:00:00+00:00")
    repeated = append("4873.97cc.e9af", "2026-08-01T00:01:00+00:00")
    changed = append("4873-97cc-e9bf", "2026-08-01T00:02:00+00:00")

    assert first[1:] == (0, "4873-97cc-e9af", first[3])
    assert repeated == first
    assert changed[0] == first[0] + 1
    assert changed[1] == 1
    assert changed[2] == "4873-97cc-e9bf"


def test_resolve_and_search_do_not_modify_persisted_index(tmp_path: Path) -> None:
    database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP0208", mac="4873-97cc-e0e0")
    service.rebuild_index("base_data_saved")
    before = hashlib.sha256(database.path.read_bytes()).hexdigest()

    assert service.resolve_peer_mac("487397cce0ef").status == "matched"
    assert service.search_aps("48:73:97:cc:e0:ef")[0]["ap_name"] == "AP0208"

    assert hashlib.sha256(database.path.read_bytes()).hexdigest() == before
