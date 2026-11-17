from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict, replace
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from netconsole.core.database import Database
from netconsole.core.device_credential_store import (
    CredentialFieldResolution, replace_device_credential_state,
)
from netconsole.models.device import Device, is_device_eligible_for_automatic_collection
from netconsole.models.ground_inventory import freeze_inventory, thaw_inventory
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.deep_scheduler import DeepMrCollectionScheduler
from netconsole.services.netmiko_connection import connection_targets
from scripts.dev.sql_read_sharing_profile_20261117 import (
    _COUNTERS, _audit_connections, _site_fixture,
)


def _count(function):
    counters = Counter()
    token = _COUNTERS.set(counters)
    try:
        with _audit_connections():
            result = function()
    finally:
        _COUNTERS.reset(token)
    return result, counters


@pytest.fixture
def assets(tmp_path):
    database = Database(tmp_path / "devices.sqlite")
    database.initialize()
    return DeviceRepository(database)


@pytest.fixture
def service(tmp_path):
    result, _ = _site_fixture(tmp_path, 2)
    return result


def test_device_empty_batch_opens_no_connection(assets):
    result, counts = _count(lambda: (assets.get_by_uuids([]), assets.inventory_metadata_by_uuids([])))
    assert result == ({}, {})
    assert counts["connections"] == counts["select_with"] == 0


@pytest.mark.parametrize("metadata", [False, True])
def test_device_batch_deduplicates_and_crosses_900_parameters_on_one_connection(assets, metadata):
    device = assets.create(Device(name="MR", primary_address="192.0.2.1"))
    keys = [str(device.device_uuid)] * 4 + [Device.new_uuid() for _ in range(901)]
    read = assets.inventory_metadata_by_uuids if metadata else assets.get_by_uuids
    result, counts = _count(lambda: read(iter(keys)))
    assert set(result) == {str(device.device_uuid)}
    assert counts["connections"] == 1
    assert counts["select_with"] == 6  # device + credential table/state per bounded batch
    assert counts["transaction"] == 1


@pytest.mark.parametrize("state", ["available", "needs_reentry", "key_file_missing"])
def test_batch_preserves_credentials_without_exposing_secrets_in_metadata(assets, state):
    device = assets.create(Device(name="MR", primary_address="192.0.2.1", ssh_enabled=True,
                                  ssh_username="synthetic", ssh_password="private-fixture"))
    key = str(device.device_uuid)
    with assets.database.connect() as conn:
        replace_device_credential_state(conn, key, "ssh_password",
                                        CredentialFieldResolution(state, "synthetic", "TEST"))
        conn.commit()
    expected = assets.get_by_uuid(key)
    actual = assets.get_by_uuids([key])[key]
    assert actual == expected
    metadata = assets.inventory_metadata_by_uuids([key])[key]
    assert metadata.connection_eligible == is_device_eligible_for_automatic_collection(expected)
    assert metadata.connection_ready == bool(metadata.connection_eligible and connection_targets(expected))
    assert set(asdict(metadata)) == {"backup_address", "system_name", "connection_eligible", "connection_ready"}
    assert "private-fixture" not in repr(metadata)
    with pytest.raises(FrozenInstanceError):
        metadata.system_name = "changed"


def test_batch_legacy_credentials_without_state_table(assets):
    device = assets.create(Device(name="MR", primary_address="192.0.2.1", ssh_enabled=True))
    key = str(device.device_uuid)
    with assets.database.connect() as conn:
        conn.execute("UPDATE devices SET username=?, password=? WHERE device_uuid=?",
                     ("legacy", "legacy-fixture", key))
        conn.execute("DROP TABLE device_credential_states")
        conn.commit()
    assert assets.get_by_uuids([key])[key] == assets.get_by_uuid(key)
    assert assets.inventory_metadata_by_uuids([key])[key].connection_ready


def test_collection_is_deeply_immutable_and_dto_copies_are_independent(service):
    collection = service.inventory_sync.collect()
    with pytest.raises(TypeError):
        collection.endpoints[0]["management_ip"] = "192.0.2.99"
    with pytest.raises(FrozenInstanceError):
        collection.revision = "changed"
    first = service.inventory_sync.current_mrs()
    first[0].management_ip = "192.0.2.99"
    assert service.inventory_sync.current_mrs()[0].management_ip != first[0].management_ip
    _, endpoints, _, _ = collection
    endpoints[0]["management_ip"] = "192.0.2.99"
    assert collection.endpoints[0]["management_ip"] != "192.0.2.99"


def test_source_revision_and_ttl_refresh_collection(service):
    sync = service.inventory_sync
    original = sync.collect()
    assert sync.collect() is original
    assets = DeviceRepository(Database(service.paths.site_db_path(service.site_id)))
    device = assets.get_by_uuid(original.mrs[0]["id"])
    device.system_name = "changed-sysname"
    assets.update(device)
    updated = sync.collect()
    assert updated.source_revision != original.source_revision
    assert updated.revision != original.revision
    assert any(row["source_hostname"] == "changed-sysname" for row in updated.endpoints)
    sync.collection_ttl = 0
    refreshed = sync.collect()
    assert refreshed is not updated
    assert refreshed.revision == updated.revision


def test_injected_reader_is_not_cached_across_calls(service):
    rows = service.inventory_sync.current_mrs()
    service.inventory_sync.base_query = SimpleNamespace(list_mesh_import_context_mrs=lambda _site: rows)
    first = service.inventory_sync.collect()
    rows[0].management_ip = "192.0.2.99"
    second = service.inventory_sync.collect()
    assert first.revision != second.revision


def test_source_change_during_collection_retries_before_publication(service, monkeypatch):
    sync = service.inventory_sync
    sync._collection = None
    revisions = iter(("before", "after", "after", "after"))
    monkeypatch.setattr(sync, "_source_revision", lambda: next(revisions))
    collect = Mock(wraps=sync._collect)
    monkeypatch.setattr(sync, "_collect", collect)
    result = sync.collect()
    assert collect.call_count == 2
    assert result.source_revision == "after"
    assert sync._collection is result


def test_unstable_source_does_not_publish_a_mixed_collection(service, monkeypatch):
    sync = service.inventory_sync
    sync._collection = None
    revisions = iter(str(index) for index in range(6))
    monkeypatch.setattr(sync, "_source_revision", lambda: next(revisions))
    collect = Mock(wraps=sync._collect)
    monkeypatch.setattr(sync, "_collect", collect)
    with pytest.raises(ValueError, match="SOURCE_UNSTABLE"):
        sync.collect()
    assert collect.call_count == 3
    assert sync._collection is None


def test_preview_and_sync_reuse_one_collection_and_reject_stale_or_wrong_site(service, monkeypatch):
    sync = service.inventory_sync
    sync._collection = None
    collect = Mock(wraps=sync._collect)
    monkeypatch.setattr(sync, "_collect", collect)
    collection = sync.collect()
    preview = sync.preview(collection=collection)
    sync.synchronize(collection=collection)
    assert collect.call_count == 1
    with pytest.raises(ValueError, match="SITE_MISMATCH"):
        sync.preview(collection=replace(collection, site_id="another-site"))
    state = service.repository.heartbeat_inventory_state()
    service.repository.apply_heartbeat_inventory_action("CLEAR_DEVICES", expected_revision=state["revision"])
    import hashlib
    revision = hashlib.sha256(f"SYNC:{preview['revision']}".encode()).hexdigest()
    with pytest.raises(ValueError, match="PREVIEW_STALE"):
        sync.synchronize(collection=collection, preview_revision=revision)


def test_cold_inventory_has_constant_device_reads(service, monkeypatch):
    sync = service.inventory_sync
    base_rows = sync.current_mrs()
    for size in (1, 4):
        sync.base_query = SimpleNamespace(list_mesh_import_context_mrs=lambda _site: base_rows[:size])
        monkeypatch.setattr(DeviceRepository, "get_by_uuid", Mock(side_effect=AssertionError("N+1")))
        result, counts = _count(sync.collect)
        assert len(result.endpoints) == size
        assert counts["connections"] == 1
        assert counts["select_with"] == 3


def test_ground_snapshot_cold_warm_commit_rollback_and_site_isolation(service):
    repo = service.repository
    first, cold = _count(lambda: repo.inventory_snapshot(force=True))
    second, warm = _count(repo.inventory_snapshot)
    assert first is second
    assert cold["connections"] == 1 and cold["select_with"] == 3
    assert warm["connections"] == warm["select_with"] == 0
    with pytest.raises(TypeError):
        first.trains[0]["endpoints"][0]["management_ip"] = "192.0.2.99"
    with pytest.raises(RuntimeError, match="rollback"):
        with repo._inventory_transaction() as conn:
            conn.execute("UPDATE ground_unattended_train_inventory SET train_name='rollback'")
            raise RuntimeError("rollback")
    assert repo.inventory_snapshot() is first
    repo.set_priority(first.trains[0]["train_id"], True)
    updated = repo.inventory_snapshot()
    assert updated.revision != first.revision
    other = GroundUnattendedRepository(repo.db_path, site_id="another-site")
    assert other.inventory_snapshot().trains == ()
    legacy = repo.list_inventory()
    legacy[0]["endpoints"].clear()
    assert repo.inventory_snapshot() is updated
    assert updated.trains[0]["endpoints"]


def test_external_repository_update_visible_after_bounded_refresh(service):
    repo = service.repository
    first = repo.inventory_snapshot()
    other = GroundUnattendedRepository(repo.db_path, site_id=repo.site_id)
    other.set_priority(first.trains[0]["train_id"], True)
    assert repo.inventory_snapshot() is first
    repo._inventory_loaded_at -= repo.inventory_snapshot_ttl + 0.01
    assert repo.inventory_snapshot().revision != first.revision


def test_concurrent_snapshot_load_cannot_overwrite_commit_invalidation(service, monkeypatch):
    repo = service.repository
    first = repo.inventory_snapshot()
    loaded, release, writing = threading.Event(), threading.Event(), threading.Event()
    original = repo._list_inventory

    def delayed(conn, **kwargs):
        result = original(conn, **kwargs)
        loaded.set()
        assert release.wait(5)
        return result

    def write():
        writing.set()
        repo.set_priority(first.trains[0]["train_id"], True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        monkeypatch.setattr(repo, "_list_inventory", delayed)
        read = pool.submit(repo.inventory_snapshot, force=True)
        assert loaded.wait(5)
        update = pool.submit(write)
        assert writing.wait(5)
        release.set()
        read.result(timeout=5)
        update.result(timeout=5)
    assert repo.inventory_snapshot().revision != first.revision


def test_heartbeat_and_syslog_share_snapshot_without_reconfigure_or_sql(service, monkeypatch):
    repo = service.repository
    heartbeat = service.supervisor.heartbeat
    receiver = service.supervisor.syslog_receiver
    snapshot = repo.inventory_snapshot(force=True)
    heartbeat._configure_heartbeat_targets("heartbeat-resident", snapshot=snapshot)
    receiver.refresh_inventory(snapshot=snapshot)
    configure = Mock(wraps=heartbeat._heartbeat_engine.configure_targets)
    reconcile = Mock(wraps=heartbeat._train_connectivity.reconcile_targets)
    monkeypatch.setattr(heartbeat._heartbeat_engine, "configure_targets", configure)
    monkeypatch.setattr(heartbeat._train_connectivity, "reconcile_targets", reconcile)
    indexes = receiver._inventory_identity_indexes

    def repeat():
        for _ in range(10):
            targets = heartbeat._configure_heartbeat_targets("heartbeat-resident", snapshot=snapshot)
            receiver.refresh_inventory(snapshot=snapshot)
        return targets

    targets, counts = _count(repeat)
    assert counts["connections"] == counts["select_with"] == 0
    assert all(len(target.management_ips) == 2 for target in targets)
    assert receiver._inventory_identity_indexes is indexes
    configure.assert_not_called()
    reconcile.assert_not_called()
    with pytest.raises(ValueError, match="SITE_MISMATCH"):
        heartbeat._configure_heartbeat_targets("heartbeat-resident", snapshot=replace(snapshot, site_id="other"))
    with pytest.raises(ValueError, match="SITE_MISMATCH"):
        receiver.refresh_inventory(snapshot=replace(snapshot, site_id="other"))


def test_syslog_revision_backup_identity_conflict_and_no_sql_resolution(service):
    repo, receiver = service.repository, service.supervisor.syslog_receiver
    old = repo.inventory_snapshot(force=True)
    receiver.refresh_inventory(snapshot=old)
    trains = thaw_inventory(old.trains)
    endpoint = trains[0]["endpoints"][0]
    hostname = endpoint["source_hostname"]
    backup = endpoint["backup_management_ip"]
    result, counts = _count(lambda: [receiver._resolve_identity(backup, hostname) for _ in range(1000)])
    assert all(status == "VERIFIED" for _, status in result)
    assert counts["connections"] == counts["select_with"] == 0
    endpoint["backup_management_ip"] = "192.0.2.99"
    trains[1]["endpoints"][0]["source_hostname"] = hostname
    changed = replace(old, trains=freeze_inventory(trains), active_trains=freeze_inventory(trains),
                      revision="changed", loaded_at=old.loaded_at + 1)
    receiver.refresh_inventory(snapshot=changed)
    assert backup not in receiver._endpoint_by_ip
    assert receiver._resolve_identity("192.0.2.99", hostname)[1] == "VERIFIED"
    assert receiver._resolve_identity("203.0.113.99", hostname)[1] == "UNIDENTIFIED"
    assert receiver._resolve_identity(trains[0]["endpoints"][1]["management_ip"], hostname)[1] == "IDENTITY_CONFLICT"
    indexes = receiver._inventory_identity_indexes
    receiver.refresh_inventory(snapshot=old)
    assert receiver._inventory_identity_indexes is indexes  # late old publication is rejected


def test_deep_scheduler_rechecks_fresh_device_eligibility(service, monkeypatch):
    scheduler = object.__new__(DeepMrCollectionScheduler)
    scheduler.paths, scheduler.site_id = service.paths, service.site_id
    scheduler.inventory_sync = service.inventory_sync
    collection = scheduler.inventory_sync.collect()
    mr = collection.mrs[0]
    assets = DeviceRepository(Database(service.paths.site_db_path(service.site_id)))
    device = assets.get(int(mr["device_id"]))
    device.work_scope_status = "excluded"
    assets.update(device)
    # Even an explicitly stale static identity cannot authorize a connection.
    monkeypatch.setattr(scheduler.inventory_sync, "collect", lambda: collection)
    with pytest.raises(ValueError, match="不参与"):
        scheduler._build_start_request({"mr_id": mr["id"]}, SimpleNamespace())


def test_deep_scheduler_rechecks_fresh_credentials(service, monkeypatch):
    scheduler = object.__new__(DeepMrCollectionScheduler)
    scheduler.paths, scheduler.site_id = service.paths, service.site_id
    scheduler.inventory_sync = service.inventory_sync
    collection = scheduler.inventory_sync.collect()
    mr = collection.mrs[0]
    assets = DeviceRepository(Database(service.paths.site_db_path(service.site_id)))
    device = assets.get(int(mr["device_id"]))
    device.ssh_password = None
    device.password = None
    device.credential_clear_fields = ("ssh_password",)
    assets.update(device)
    monkeypatch.setattr(scheduler.inventory_sync, "collect", lambda: collection)
    with pytest.raises(ValueError, match="凭据"):
        scheduler._build_start_request({"mr_id": mr["id"]}, SimpleNamespace())
