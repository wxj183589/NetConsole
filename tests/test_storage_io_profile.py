from pathlib import Path

from netconsole.core.storage_io import (
    StorageProfileDetector,
    detect_storage_profile,
)


def detector(payload: str) -> StorageProfileDetector:
    return StorageProfileDetector(command_runner=lambda _command, _timeout: payload)


def test_storage_media_mapping_uses_data_root_volume() -> None:
    path = Path("D:/NetConsoleData")
    detection = detector('[{"FriendlyName":"NVMe Samsung","BusType":"NVMe","MediaType":"4"}]').detect(path)
    assert detection.volume == "D:"
    assert detection.media_type == "NVME"
    assert detection.profile == "FAST_STORAGE"


def test_detector_queries_only_the_selected_data_root_disk() -> None:
    captured: list[str] = []

    def run(command, _timeout):
        captured.extend(command)
        return '[{"FriendlyName":"SAS Hard Disk","MediaType":"3"}]'

    detection = StorageProfileDetector(command_runner=run).detect("D:/NetConsoleData")

    assert detection.media_type == "HDD"
    script = captured[-1]
    assert "DriveLetter 'D'" in script
    assert "MSFT_PhysicalDisk" not in script


def test_hdd_and_raid_are_conservative() -> None:
    hdd = detector('[{"FriendlyName":"SAS Hard Disk","MediaType":"3"}]').detect("D:/NetConsoleData")
    raid = detector('[{"FriendlyName":"PERC H755 Virtual Disk","MediaType":"0"}]').detect("D:/NetConsoleData")
    assert hdd.profile == "CONSERVATIVE_STORAGE"
    assert hdd.media_type == "HDD"
    assert raid.profile == "CONSERVATIVE_STORAGE"
    assert raid.media_type == "RAID"


def test_unknown_and_command_failure_fall_back_to_conservative() -> None:
    unknown = detector('[{"FriendlyName":"Generic storage","MediaType":"0"}]').detect("D:/NetConsoleData")
    failed = StorageProfileDetector(command_runner=lambda _command, _timeout: (_ for _ in ()).throw(OSError("no CIM"))).detect("D:/NetConsoleData")
    assert unknown.profile == "CONSERVATIVE_STORAGE"
    assert unknown.media_type == "UNKNOWN"
    assert failed.profile == "CONSERVATIVE_STORAGE"


def test_manual_override_wins_over_detection() -> None:
    detection, fast = detect_storage_profile(
        "D:/NetConsoleData",
        mode="FAST",
        detector=detector('[{"FriendlyName":"SAS Hard Disk","MediaType":"3"}]'),
    )
    assert detection.media_type == "HDD"
    assert fast.name == "FAST_STORAGE"
    assert fast.profile_source == "MANUAL"
