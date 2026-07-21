from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.services.site_lifecycle import DEMO_MAX_BYTES, DEMO_SEED_VERSION, DemoSiteSeedService, SiteAuditService, SiteCleanupApplicationService
from netconsole.services.site_storage import SiteApplicationService, SiteRecord, SiteRegistryRepository, SiteStorageError


def _paths(tmp_path: Path) -> PathResolver:
    return PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data-root")


def test_demo_seed_is_managed_small_and_idempotent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    first = DemoSiteSeedService(paths).seed()
    second = DemoSiteSeedService(paths).seed()
    metadata = json.loads((paths.site_dir("demo") / "site_meta.json").read_text(encoding="utf-8"))
    audit = SiteAuditService(paths).audit_all(site_id="demo")

    assert first["status"] == "created"
    assert second["status"] == "already_current"
    assert metadata["managed_demo"] is True
    assert metadata["seed_version"] == DEMO_SEED_VERSION
    assert first["size_bytes"] < DEMO_MAX_BYTES
    assert audit["sites"][0]["classification"] == "managed_demo"
    assert audit["sites"][0]["task_count"] == 0


def test_demo_seed_uses_current_schema_without_legacy_credentials(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    DemoSiteSeedService(paths).seed()

    with Database(paths.site_db_path("demo")).connect() as connection:
        rows = connection.execute("SELECT name, snmp_v1_enabled, snmp_v2c_enabled, ssh_password, telnet_password FROM devices ORDER BY name").fetchall()

    assert [str(row["name"]) for row in rows] == ["AC", "SW01", "SW02", "列车01-MR-CT", "列车01-MR-TC"]
    assert all(int(row["snmp_v1_enabled"] or 0) == 0 and int(row["snmp_v2c_enabled"] or 0) == 0 for row in rows)
    assert all(not row["ssh_password"] and not row["telnet_password"] for row in rows)


def test_demo_rebuild_failure_restores_old_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    DemoSiteSeedService(paths).seed()
    database = paths.site_db_path("demo")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    audited = SiteAuditService(paths).audit_all(site_id="demo")["sites"][0]
    assert audited["safe_to_replace"] is True, audited

    def fail_register(*args, **kwargs):
        raise SiteStorageError("SITE_REGISTRY_CONFLICT", "测试注册失败")

    monkeypatch.setattr(SiteRegistryRepository, "register", fail_register)
    with pytest.raises(SiteStorageError, match="重建失败"):
        DemoSiteSeedService(paths).seed(replace=True, allow_user_data=True)

    assert database.is_file()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    rollback_files = list((paths.archive_dir / "demo-recycle").glob("*/rollback.json"))
    assert rollback_files


def test_audit_classifies_legacy_empty_shell_and_demo_data(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    manager = SiteManager(paths)
    manager.ensure_demo_site()
    manager.create_site("line-a", display_name="一号线")
    target = paths.ensure_site_dirs("宁波地铁10号线")
    SiteRegistryRepository(paths).register(SiteRecord("legacy-784dcd2b63e3", "宁波地铁10号线", target))
    Database(target / "db" / "devices.db").initialize()
    shell = paths.ensure_site_dirs("legacy-784dcd2b63e3")
    Database(shell / "db" / "devices.db").initialize()
    manager.switch_site("line-a")

    report = SiteAuditService(paths).audit_all()
    by_name = {item["site_id"]: item for item in report["sites"]}

    assert by_name["demo"]["classification"] == "legacy_demo"
    shell_item = next(item for item in report["sites"] if item["physical_path"].endswith("legacy-784dcd2b63e3"))
    assert shell_item["classification"] == "empty_shell"
    assert shell_item["can_delete"] is True
    assert shell_item["unique_business_data"] is False
    assert shell_item["duplicate_candidates"] == ["legacy-784dcd2b63e3"]


def test_cleanup_moves_empty_shell_and_updates_registry(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    manager = SiteManager(paths)
    manager.create_site("line-a", display_name="一号线")
    target = paths.ensure_site_dirs("宁波地铁10号线")
    SiteRegistryRepository(paths).register(SiteRecord("legacy-784dcd2b63e3", "宁波地铁10号线", target))
    Database(target / "db" / "devices.db").initialize()
    shell = paths.ensure_site_dirs("legacy-784dcd2b63e3")
    Database(shell / "db" / "devices.db").initialize()
    manager.switch_site("line-a")
    sites = SiteApplicationService(paths)
    sites.list_sites()
    SiteAuditService(paths).audit_all()

    cleanup = SiteCleanupApplicationService(paths)
    plan = cleanup.prepare_cleanup("legacy-d6f5fe256cadb4e1")
    result = cleanup.apply_cleanup(str(plan["cleanup_token"]))

    assert result["recoverable"] is True
    assert not shell.exists()
    assert not any(item["site_id"] == "legacy-d6f5fe256cadb4e1" for item in sites.list_sites())
    assert (paths.data_root / str(result["recycle_path"])).parent.joinpath("tombstone.json").is_file()

    restored = cleanup.restore_cleanup(str(plan["cleanup_token"]))
    assert restored["restored"] is True
    assert shell.is_dir()
    assert any(item["site_id"] == "legacy-d6f5fe256cadb4e1" for item in sites.list_sites())


def test_cleanup_blocks_external_database_reference(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    manager = SiteManager(paths)
    manager.create_site("line-a", display_name="一号线")
    shell = paths.ensure_site_dirs("legacy-shell")
    Database(shell / "db" / "devices.db").initialize()
    SiteRegistryRepository(paths).register(SiteRecord("legacy-shell-id", "迁移空壳", shell))
    with Database(paths.site_db_path("line-a")).connect() as connection:
        connection.execute("CREATE TABLE site_reference (site_id TEXT NOT NULL)")
        connection.execute("INSERT INTO site_reference(site_id) VALUES (?)", ("legacy-shell-id",))
        connection.commit()
    manager.switch_site("line-a")
    SiteAuditService(paths).audit_all()

    plan = SiteCleanupApplicationService(paths).prepare_cleanup("legacy-shell-id")
    assert plan["can_delete"] is False
    assert "其他局点数据库仍有引用" in plan["blocking_reasons"]


def test_cleanup_blocks_unknown_file_in_empty_legacy_site(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    manager = SiteManager(paths)
    manager.create_site("line-a", display_name="一号线")
    shell = paths.ensure_site_dirs("legacy-shell")
    Database(shell / "db" / "devices.db").initialize()
    (shell / "unique-config.json").write_text('{"owner":"user"}', encoding="utf-8")
    SiteRegistryRepository(paths).register(SiteRecord("legacy-shell-id", "迁移空壳", shell))
    manager.switch_site("line-a")

    report = SiteAuditService(paths).audit_all(site_id="legacy-shell-id")["sites"][0]
    plan = SiteCleanupApplicationService(paths).prepare_cleanup("legacy-shell-id")

    assert report["unknown_file_count"] == 1
    assert plan["can_delete"] is False
    assert "存在业务数据或原始文件" in plan["blocking_reasons"]


def test_cleanup_rejects_current_site_and_business_data(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    manager = SiteManager(paths)
    manager.create_site("line-a", display_name="一号线")
    SiteAuditService(paths).audit_all()
    plan = SiteCleanupApplicationService(paths).prepare_cleanup("line-a")
    assert plan["can_delete"] is False
    assert "当前局点" in plan["blocking_reasons"]
