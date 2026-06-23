from netconsole.services.data_disk_manager import clean_data_disk, scan_data_disk


def test_data_disk_manager_cleans_only_legacy_debug_debug_and_runtime_cache(tmp_path):
    data = tmp_path / "data"
    runtime = tmp_path / "runtime"
    db = data / "sites" / "demo" / "db" / "devices.db"
    report = data / "reports" / "report.xlsx"
    backup = data / "backups" / "backup.zip"
    site_report = data / "sites" / "demo" / "reports" / "site-report.xlsx"
    site_backup = data / "sites" / "demo" / "backups" / "site-backup.zip"
    site_export = data / "sites" / "demo" / "exports" / "devices.csv"
    legacy_debug = data / "sites" / "demo" / "raw" / "session.txt"
    file_download = data / "sites" / "demo" / "downloads" / "show.cfg"
    mesh_archive = data / "sites" / "demo" / "mesh" / "archive" / "mesh.zip"
    online_mr = data / "sites" / "demo" / "online_mr" / "MR-1" / "sessions" / "s1" / "collection.log"
    debug = data / "debug" / "debug.log"
    cache = runtime / "cache" / "offline.json"
    for path, text in (
        (db, "db"),
        (report, "report"),
        (backup, "backup"),
        (site_report, "site-report"),
        (site_backup, "site-backup"),
        (site_export, "site-export"),
        (legacy_debug, "legacy-debug"),
        (file_download, "file-download"),
        (mesh_archive, "mesh-archive"),
        (online_mr, "online-mr"),
        (debug, "debug"),
        (cache, "cache"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    before = {item.name: item for item in scan_data_disk(data, runtime)}
    removed = clean_data_disk(data, runtime, {"legacy_debug_data", "debug_logs", "runtime_cache"})

    assert before["database"].bytes == 2
    assert before["reports"].bytes >= len("site-report")
    assert before["backups"].bytes >= len("site-backup")
    assert before["exports"].bytes >= len("site-export")
    assert "raw_logs" not in before
    assert before["file_downloads"].cleanable is False
    assert before["mesh_archives"].cleanable is False
    assert before["online_mr_data"].cleanable is False
    assert before["legacy_debug_data"].cleanable is True
    assert removed["legacy_debug_data"] == len("legacy-debug")
    assert removed["debug_logs"] == 5
    assert removed["runtime_cache"] == 5
    assert db.exists()
    assert report.exists()
    assert backup.exists()
    assert site_report.exists()
    assert site_backup.exists()
    assert site_export.exists()
    assert file_download.exists()
    assert mesh_archive.exists()
    assert online_mr.exists()
    assert not legacy_debug.exists()
    assert not debug.exists()
    assert not cache.exists()


def test_data_disk_manager_refuses_protected_categories(tmp_path):
    try:
        clean_data_disk(tmp_path / "data", tmp_path / "runtime", {"database"})
    except ValueError as exc:
        assert "database" in str(exc)
    else:
        raise AssertionError("protected category cleanup must fail")
