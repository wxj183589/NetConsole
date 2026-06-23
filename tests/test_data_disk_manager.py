from netconsole.services.data_disk_manager import clean_data_disk, scan_data_disk


def test_data_disk_manager_cleans_only_raw_debug_and_runtime_cache(tmp_path):
    data = tmp_path / "data"
    runtime = tmp_path / "runtime"
    db = data / "sites" / "demo" / "db" / "devices.db"
    report = data / "reports" / "report.xlsx"
    backup = data / "backups" / "backup.zip"
    site_report = data / "sites" / "demo" / "reports" / "site-report.xlsx"
    site_backup = data / "sites" / "demo" / "backups" / "site-backup.zip"
    site_export = data / "sites" / "demo" / "exports" / "devices.csv"
    raw = data / "sites" / "demo" / "raw" / "session.txt"
    debug = data / "debug" / "debug.log"
    cache = runtime / "cache" / "offline.json"
    for path, text in (
        (db, "db"),
        (report, "report"),
        (backup, "backup"),
        (site_report, "site-report"),
        (site_backup, "site-backup"),
        (site_export, "site-export"),
        (raw, "raw"),
        (debug, "debug"),
        (cache, "cache"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    before = {item.name: item for item in scan_data_disk(data, runtime)}
    removed = clean_data_disk(data, runtime, {"raw_logs", "debug_logs", "runtime_cache"})

    assert before["database"].bytes == 2
    assert before["reports"].bytes >= len("site-report")
    assert before["backups"].bytes >= len("site-backup")
    assert before["exports"].bytes >= len("site-export")
    assert before["raw_logs"].cleanable is True
    assert removed["raw_logs"] == 3
    assert removed["debug_logs"] == 5
    assert removed["runtime_cache"] == 5
    assert db.exists()
    assert report.exists()
    assert backup.exists()
    assert site_report.exists()
    assert site_backup.exists()
    assert site_export.exists()
    assert not raw.exists()
    assert not debug.exists()
    assert not cache.exists()


def test_data_disk_manager_refuses_protected_categories(tmp_path):
    try:
        clean_data_disk(tmp_path / "data", tmp_path / "runtime", {"database"})
    except ValueError as exc:
        assert "database" in str(exc)
    else:
        raise AssertionError("protected category cleanup must fail")
