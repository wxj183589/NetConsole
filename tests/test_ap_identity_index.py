from __future__ import annotations

import hashlib
from pathlib import Path

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


def test_base_data_alone_resolves_exact_h3c_radio_alias(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
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
    assert match.match_rule == "h3c_ap_mac_to_r1_exact"
    assert match.radio_id == 1


def test_same_h3c_prefix_without_exact_alias_is_unresolved(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-A", mac="4873-97cc-e0e0")
    _base_ap(repository, name="AP-B", mac="4873-97cc-e1e0")
    service.rebuild_index("base_data_saved")

    match = service.resolve_peer_mac("4873-97cc-e9af")

    assert match.status == "unresolved"
    assert match.candidates == ()


def test_duplicate_exact_h3c_alias_is_ambiguous(tmp_path: Path) -> None:
    _database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP-A", mac="74ad-cb9d-3320")
    _base_ap(repository, name="AP-B", mac="74ad-cb9d-3321")
    service.rebuild_index("base_data_saved")

    match = service.resolve_peer_mac("74ad-cb9d-332f")

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


def test_resolve_and_search_do_not_modify_persisted_index(tmp_path: Path) -> None:
    database, repository, service = _fixture(tmp_path)
    _base_ap(repository, name="AP0208", mac="4873-97cc-e0e0")
    service.rebuild_index("base_data_saved")
    before = hashlib.sha256(database.path.read_bytes()).hexdigest()

    assert service.resolve_peer_mac("487397cce0ef").status == "matched"
    assert service.search_aps("48:73:97:cc:e0:ef")[0]["ap_name"] == "AP0208"

    assert hashlib.sha256(database.path.read_bytes()).hexdigest() == before
