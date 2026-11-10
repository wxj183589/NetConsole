"""Reproducible synthetic Mesh benchmark; each measured stage owns a process.

Run as a module. Fixtures stay under the canonical test root and are retired
after each scale. JSON contains measurements, hashes and baseline provenance.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "37b0df95a3208d0d03380e76ccfe5419af1422f1"


def peak_mib():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "working",
                "page_peak",
                "page",
                "nonpage_peak",
                "nonpage",
                "pagefile",
                "pagefile_peak",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(Counters),
        ctypes.c_ulong,
    ]
    if not psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return round(counters.peak / 1024**2, 3)


def baseline_module(relative, name):
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:{relative}"], cwd=ROOT
    )
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / relative)
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def digest(value):
    sha = hashlib.sha256()
    for part in json.JSONEncoder(
        sort_keys=True, ensure_ascii=False, default=str
    ).iterencode(value):
        sha.update(part.encode("utf-8"))
    return sha.hexdigest()


def locations():
    from netconsole.services.rail_transit.mesh_ap_location_service import (
        MeshApLocation,
        MeshApLocationSnapshot,
    )

    return MeshApLocationSnapshot(
        [
            MeshApLocation(
                mac=f"{4096 + index // 2:012x}",
                alias_mac=f"{index + 1:012x}",
                name=f"AP-{index // 2}",
                station="synthetic",
                identity_status="matched",
            )
            for index in range(256)
        ]
    )


def child(args):
    from netconsole.services import mesh_quality_analysis as quality
    from netconsole.services.mesh_business_statistics import (
        build_mesh_business_statistics,
        iter_business_links,
    )

    database = args.root / f"chart-{args.records}.mesh.sqlite"
    result = {"stage": args.stage, "variant": args.variant, "records": args.records}
    if args.stage == "parser":
        from netconsole.parsers.mesh_log_parser import MeshLogParser

        started = time.perf_counter()
        info, records, issues = MeshLogParser().parse_file(args.root / "synthetic.log")
        result.update(
            seconds=time.perf_counter() - started,
            parsed=len(records),
            skipped=info.skipped_count,
            issues=len(issues),
            raw_sha256=info.file_hash,
        )
        result["digest"] = digest([record.__dict__ for record in records])
    elif args.stage == "quality":
        with sqlite3.connect(database) as conn:
            rows = list(iter_business_links(conn))
        # Same full input and complete report options in both versions.
        for row in rows:
            row["mr_rssi"] = row["local_rssi_db"]
            row["peer_rssi"] = row["peer_rssi_db"]
        module = (
            baseline_module(
                "src/netconsole/services/mesh_quality_analysis.py",
                "mesh_baseline_quality",
            )
            if args.variant == "before"
            else quality
        )
        original = module.build_peer_quality

        def measured_peer(*values, **kwargs):
            start = time.perf_counter()
            output = original(*values, **kwargs)
            result["peer_seconds"] = time.perf_counter() - start
            return output

        module.build_peer_quality = measured_peer
        started = time.perf_counter()
        report = module.build_quality_report(
            rows,
            [],
            [],
            "synthetic",
            "benchmark",
            module.MR_RAW_MESH_LOG,
            module.MeshQualityRules(),
            include_raw_evidence=False,
        )
        result.update(
            seconds=time.perf_counter() - started,
            counts={
                key: len(value)
                for key, value in report.__dict__.items()
                if isinstance(value, list)
            },
        )
        result["digest"] = digest({
            **report.__dict__,
            "overview": {key: value for key, value in report.overview.items() if key != "生成时间"},
        })
        result["digest_excluded_fields"] = ["overview.生成时间"]
        result["overview_counts"] = {key: value for key, value in report.overview.items() if isinstance(value, (int, float))}
    elif args.stage == "statistics":
        started = time.perf_counter()
        with sqlite3.connect(database) as conn:
            stats = build_mesh_business_statistics(
                iter_business_links(conn), quality.MeshQualityRules(), locations()
            )
        result.update(
            seconds=time.perf_counter() - started,
            summary=stats["summary"],
            digest=digest(stats),
        )
    elif args.stage == "query":
        from netconsole.core.paths import PathResolver
        from netconsole.services.rail_transit.mesh_analysis_query_service import (
            MeshAnalysisQueryService,
        )

        service = MeshAnalysisQueryService(
            PathResolver(app_root=ROOT, data_root=args.root),
            schedule_catalog_index=False,
        )
        context = types.SimpleNamespace(
            detail_db=database,
            detail_source_id=1,
            source_id=1,
            source={},
            site_id="synthetic",
            session_id="benchmark",
        )
        service._context = lambda *_: context
        service._ap_map = lambda *_: locations()
        mode = (
            "full" if args.variant == "before" or args.records <= 50_000 else "overview"
        )
        started = time.perf_counter()
        response = service.get_active_path_chart(
            "synthetic",
            "benchmark",
            resolution_mode=mode,
            max_points=2000,
            include_peer=False,
        )
        encoded = response.model_dump_json(exclude_none=True)
        result.update(
            seconds=time.perf_counter() - started,
            payload_bytes=len(encoded.encode("utf-8")),
            mode=mode,
            returned_points=response.returned_points,
        )
        (args.root / f"chart-{args.variant}.json").write_text(encoded, encoding="utf-8")
    elif args.stage == "export":
        from netconsole.services import mesh_link_detail_export as current_export

        module = (
            baseline_module(
                "src/netconsole/services/mesh_link_detail_export.py",
                "mesh_baseline_export",
            )
            if args.variant == "before"
            else current_export
        )
        from contextlib import closing
        from xlsxwriter.exceptions import FileSizeError
        from netconsole.repositories.mesh_mr_repository import MeshMrRepository
        from netconsole.services.rail_transit.mesh_ap_location_service import enrich_mesh_ap_location_row

        output = args.root / f"{args.variant}.xlsx"
        # Production core data chain: count, build order, identity enrichment,
        # complete Repository cursor and writer. Excludes Job/Artifact/UI save.
        started = time.perf_counter()
        repo = MeshMrRepository(database, read_only=True)
        snapshot = locations()
        total = repo.count_link_details({"source_file_id": 1})
        active = [enrich_mesh_ap_location_row(row, snapshot) for row in repo.query_active_link_build_order(1)]
        assert total == args.records and active
        result["build_order_rows"] = len(active)
        kwargs = {}
        if args.variant == "after":
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
                kwargs["business_statistics"] = build_mesh_business_statistics(
                    iter_business_links(conn, 1), quality.MeshQualityRules(), snapshot
                )
        rows = (enrich_mesh_ap_location_row(row, snapshot) for row in repo.iter_link_details({"source_file_id": 1}))
        try:
            module.export_mesh_link_details_xlsx(output, rows, active, total_rows=total, **kwargs)
            result.update(status="PASS", file_bytes=output.stat().st_size)
        except FileSizeError as exc:
            if args.variant != "before":
                raise
            result.update(status="FAIL", error=str(exc), file_bytes=None)
        result["seconds"] = time.perf_counter() - started
        result["peak_process_mib"] = peak_mib()
        if result["status"] == "PASS":
            from zipfile import ZipFile
            from xml.etree.ElementTree import iterparse
            with ZipFile(output) as archive:
                with archive.open("xl/worksheets/sheet1.xml") as sheet:
                    written = 0
                    for _, element in iterparse(sheet, events=("end",)):
                        if element.tag.endswith("}row"):
                            written += 1
                        element.clear()
                result["written_detail_rows"] = written - 1
                assert written - 1 == total
        output.unlink(missing_ok=True)
    result.setdefault("peak_process_mib", peak_mib())
    print(json.dumps(result, ensure_ascii=False), flush=True)


def fixture(root, records):
    from scripts.maintenance.benchmark_mesh_analysis_loading import _chart_fixture

    database = _chart_fixture(root, records)
    with sqlite3.connect(database) as conn:
        # 10 links/frame; one ACTIVE; 20-second residence; 256 peers / 128 physical APs.
        conn.execute(
            "UPDATE mesh_links SET peer_mac_raw = printf('%012x', ((sample_id-1)/20 + (id-1)%10)%256+1), "
            "peer_mac_normalized = printf('%012x', ((sample_id-1)/20 + (id-1)%10)%256+1), "
            "peer_radio_mac = printf('%012x', ((sample_id-1)/20 + (id-1)%10)%256+1), peer_ap_name = NULL, "
            "link_count = 1, local_tx_busy = 2, local_rx_busy = 4, peer_tx_busy = 3, peer_rx_busy = 5, "
            "duration_seconds = (sample_id-1)%20+1, duration_text = printf('0d 00h 00m %02ds', (sample_id-1)%20+1)"
        )
        conn.execute("""
            INSERT INTO active_points (link_id, sample_id, source_file_id, sample_time, radio,
              peer_mac_raw, peer_mac_normalized, peer_mac, local_rssi_db, peer_rssi_db,
              duration_text, duration_seconds, link_count, local_tx_busy, local_rx_busy)
            SELECT id, sample_id, source_file_id, sample_time, radio,
              peer_mac_raw, peer_mac_normalized, peer_mac_normalized, local_rssi_db, peer_rssi_db,
              duration_text, duration_seconds, link_count, local_tx_busy, local_rx_busy
            FROM mesh_links WHERE link_state = 'ACTIVE'
        """)
    base = datetime(2026, 7, 30, 10)
    with (root / "synthetic.log").open("w", encoding="utf-8", newline="\n") as out:
        for frame in range((records + 9) // 10):
            stamp = (base + timedelta(seconds=frame)).strftime("%Y/%m/%d %H:%M:%S")
            out.write(f"[1] {stamp} ({frame})\n")
            for slot in range(min(10, records - frame * 10)):
                peer = f"{(frame // 20 + slot) % 256 + 1:012x}"
                mac = "-".join(peer[index : index + 4] for index in (0, 4, 8))
                state = "Active" if slot == 0 else "Standy"
                out.write(
                    f"[1] {state} {mac} {stamp} 0d 00h 00m 03s 1 36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0\n"
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=["parser", "quality", "statistics", "query", "export"]
    )
    parser.add_argument("--variant", choices=["before", "after"], default="after")
    parser.add_argument("--records", type=int, default=50_000)
    parser.add_argument("--root", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".local-reports/mesh-business-benchmark.json",
    )
    parser.add_argument(
        "--scales", type=int, nargs="+", default=[50_000, 200_000, 500_000, 1_000_000]
    )
    parser.add_argument("--keep-chart-payloads", action="store_true")
    parser.add_argument("--stages", nargs="+", choices=["parser", "quality", "statistics", "query", "export"], default=["parser", "quality", "statistics", "query", "export"])
    args = parser.parse_args()
    if args.stage:
        child(args)
        return
    from netconsole.core.runtime_environment import test_data_root_base

    test_base = test_data_root_base(repository_root=ROOT).resolve()
    run_root = test_base / f"mesh-business-{uuid4().hex}"
    run_root.mkdir(parents=True)
    os.environ.update(
        NETCONSOLE_RUNTIME_MODE="test", NETCONSOLE_DATA_ROOT=str(run_root)
    )
    data = {
        "baseline": BASELINE,
        "platform": platform.platform(),
        "python": sys.version,
        "fixture": "synthetic; 10 links/frame, 1 ACTIVE, 256 peers, 20s residence",
        "root": str(run_root),
        "results": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for scale in args.scales:
        scale_root = run_root / str(scale)
        scale_root.mkdir()
        fixture(scale_root, scale)
        # sqlite connection context managers commit but do not close; retire
        # unreachable fixture-helper connections before Windows file cleanup.
        gc.collect()
        for stage in args.stages:
            for variant in ("after",) if stage == "statistics" else ("before", "after"):
                command = [
                    sys.executable,
                    "-m",
                    "scripts.maintenance.benchmark_mesh_business",
                    "--stage",
                    stage,
                    "--variant",
                    variant,
                    "--records",
                    str(scale),
                    "--root",
                    str(scale_root),
                ]
                process = subprocess.run(
                    command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
                )
                if process.returncode:
                    raise RuntimeError(process.stderr + process.stdout)
                measurement = json.loads(process.stdout.strip().splitlines()[-1])
                data["results"].append(measurement)
                args.output.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    f"{scale} {stage} {variant}: {measurement['seconds']:.3f}s; {measurement['peak_process_mib']:.1f} MiB",
                    flush=True,
                )
        for path in scale_root.iterdir():
            if (
                args.keep_chart_payloads
                and path.name.startswith("chart-")
                and path.suffix == ".json"
            ):
                continue
            if not path.is_file() or not path.resolve().is_relative_to(test_base):
                raise RuntimeError("Unexpected fixture path")
            path.unlink()
        if not args.keep_chart_payloads:
            scale_root.rmdir()
    if not args.keep_chart_payloads:
        run_root.rmdir()


if __name__ == "__main__":
    main()
