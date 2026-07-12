from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from netconsole.services.mesh_link_detail_export import export_mesh_link_details_xlsx


def _rows(total: int):
    peers = ["bc5a3457af8f", "bc5a3457cc7f", "bc5a3457d4bf"]
    states = ["ACTIVE", "STANDBY", "STANDBY"]
    for index in range(total):
        peer_index = index % len(peers)
        second = index % 3600
        yield {
            "id": index + 1,
            "record_seq": index + 1,
            "source_file_id": 1,
            "sample_time": f"2026-07-05 13:{second // 60:02d}:{second % 60:02d}.690",
            "radio": 1,
            "link_state": states[peer_index],
            "peer_mac_normalized": peers[peer_index],
            "peer_mac_raw": f"{peers[peer_index][:4]}-{peers[peer_index][4:8]}-{peers[peer_index][8:]}",
            "peer_ap_mac": f"{peers[peer_index][:4]}-{peers[peer_index][4:8]}-{peers[peer_index][8:-1]}0",
            "peer_ap_name": f"测试AP-{peer_index + 1}",
            "peer_site": "测试站",
            "belong_section": "测试区间",
            "belong_type": "station",
            "peer_radio": f"radio{peer_index + 1}",
            "establish_time": "2026-07-05 13:00:00.690",
            "duration_text": "0d 00h 00m 02s",
            "link_count": 1,
            "metrics_json": (
                "{"
                f"\"local_rssi_db\": {30 + peer_index},"
                f"\"peer_rssi_db\": {32 + peer_index},"
                "\"local_cpu_percent\": 20,"
                "\"peer_cpu_percent\": 22,"
                "\"local_tx_busy\": 1,"
                "\"peer_tx_busy\": 3,"
                "\"local_rx_busy\": 2,"
                "\"peer_rx_busy\": 4"
                "}"
            ),
            "local_noise_dbm": -90,
            "peer_noise_dbm": -94,
            "archived_filename": "benchmark_meshlog.log.gz",
            "source_line_number": index + 100,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark MR mesh link detail xlsx export")
    parser.add_argument("--rows", type=int, default=120000, help="模拟链路明细行数")
    parser.add_argument("--output", type=Path, default=None, help="输出 xlsx 路径")
    args = parser.parse_args()
    output = args.output or Path(tempfile.gettempdir()) / f"netconsole_mesh_link_export_{args.rows}.xlsx"
    last = 0

    def progress(done: int, total: int, _stage: str) -> None:
        nonlocal last
        if done - last >= 10000 or done >= total:
            last = done
            print(f"progress {done}/{total}", flush=True)

    started = time.perf_counter()
    export_mesh_link_details_xlsx(
        output,
        _rows(args.rows),
        [],
        total_rows=args.rows,
        source_files=[{"archived_filename": "benchmark_meshlog.log.gz"}],
        event_rows=[],
        analysis_params={},
        export_context={"site_name": "benchmark", "mr_name": "benchmark", "exported_at": "2026-07-09 00:00:00"},
        progress_callback=progress,
    )
    elapsed = time.perf_counter() - started
    print(f"output={output}")
    print(f"rows={args.rows}")
    print(f"elapsed_seconds={elapsed:.3f}")
    print(f"size_mb={output.stat().st_size / 1024 / 1024:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
