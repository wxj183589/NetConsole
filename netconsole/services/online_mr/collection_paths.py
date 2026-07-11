from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OnlineMrCollectionPaths:
    session_dir: Path
    raw_dir: Path
    init_raw: Path
    config_collect_raw: Path
    terminal_monitor_raw: Path
    mesh_link_raw: Path
    ap_radio_statistics_raw: Path
    channel_busy_raw: Path
    switch_history_latest: Path
    wireless_status_raw: Path
    interface_rate_raw: Path
    collector_output_raw: Path
    fping_v5_raw: Path
    fping_v5_samples: Path
    fping_v5_final_summary: Path
    iperf_client_raw: Path
    session_meta: Path
    package_path: Path
    package_tmp_path: Path

    @classmethod
    def from_session_dir(cls, session_dir: Path) -> "OnlineMrCollectionPaths":
        root = Path(session_dir)
        raw = root / "raw"
        package = root / "outputs" / f"{root.name}.zip"
        return cls(
            session_dir=root,
            raw_dir=raw,
            init_raw=raw / "init_raw.log",
            config_collect_raw=raw / "config_collect_raw.log",
            terminal_monitor_raw=raw / "terminal_monitor_raw.log",
            mesh_link_raw=raw / "mesh_link_raw.log",
            ap_radio_statistics_raw=raw / "ap_radio_statistics_raw.log",
            channel_busy_raw=raw / "channel_busy_raw.log",
            switch_history_latest=raw / "switch_history_latest.log",
            wireless_status_raw=raw / "wireless_status_raw.log",
            interface_rate_raw=raw / "interface_rate_raw.log",
            collector_output_raw=raw / "collector_output_raw.log",
            fping_v5_raw=raw / "fping_v5_raw.log",
            fping_v5_samples=raw / "fping_v5_samples.jsonl",
            fping_v5_final_summary=raw / "fping_v5_final_summary.json",
            iperf_client_raw=raw / "iperf_client_raw.log",
            session_meta=root / "session_meta.json",
            package_path=package,
            package_tmp_path=package.with_suffix(f"{package.suffix}.tmp"),
        )
