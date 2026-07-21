from netconsole.services.data_disk_manager import clean_data_disk, scan_data_disk


def test_data_disk_manager_cleans_cache_without_touching_any_logs(tmp_path):
    data = tmp_path / "data"
    runtime = tmp_path / "runtime"
    db = data / "sites" / "demo" / "db" / "devices.db"
    config_center = data / "sites" / "demo" / "files" / "config_center" / "snapshots" / "SW1" / "running" / "a.txt"
    backup = data / "sites" / "demo" / "files" / "backups" / "backup.zip"
    file_download = data / "sites" / "demo" / "files" / "file_manager" / "downloads" / "SW1" / "show.cfg"
    rail_transit = data / "sites" / "demo" / "files" / "rail_transit" / "online_mr" / "MR-1" / "sessions" / "s1" / "raw" / "collection.log"
    network_tools = data / "sites" / "demo" / "files" / "network_tools" / "iperf" / "raw" / "client.log"
    site_cache = data / "sites" / "demo" / "cache" / "metrics" / "m.json"
    debug = data / "debug" / "debug.log"
    business_log = data / "sites" / "demo" / "files" / "rail_transit" / "online_mr" / "MR-1" / "sessions" / "s1" / "logs" / "collector.log"
    runtime_log = runtime / "logs" / "app.log"
    cache = runtime / "cache" / "offline.json"
    for path, text in (
        (db, "db"),
        (config_center, "config-center"),
        (backup, "backup"),
        (file_download, "file-download"),
        (rail_transit, "rail-transit"),
        (network_tools, "network-tools"),
        (site_cache, "site-cache"),
        (debug, "debug"),
        (business_log, "business-log"),
        (runtime_log, "runtime-log"),
        (cache, "cache"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    before = {item.name: item for item in scan_data_disk(data, runtime)}
    removed = clean_data_disk(data, runtime, {"cache"})

    assert before["database"].bytes == 2
    assert before["config_center"].bytes == len("config-center")
    assert before["backups"].bytes == len("backup")
    assert before["file_manager"].bytes == len("file-download")
    assert before["rail_transit"].bytes == len("rail-transit") + len("business-log")
    assert before["network_tools"].bytes == len("network-tools")
    assert before["cache"].cleanable is True
    assert before["debug_logs"].cleanable is False
    assert removed["cache"] == len("site-cache") + 5
    assert db.exists()
    assert backup.exists()
    assert config_center.exists()
    assert file_download.exists()
    assert rail_transit.exists()
    assert network_tools.exists()
    assert debug.exists()
    assert business_log.exists()
    assert runtime_log.exists()
    assert not site_cache.exists()
    assert not cache.exists()


def test_data_disk_manager_refuses_protected_categories(tmp_path):
    try:
        clean_data_disk(tmp_path / "data", tmp_path / "runtime", {"database"})
    except ValueError as exc:
        assert "database" in str(exc)
    else:
        raise AssertionError("protected category cleanup must fail")
