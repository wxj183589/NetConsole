from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from netconsole.core.ping.fping_v5_runner import check_fping_v5_available, run_fping_v5_json
from netconsole.core.ping.fping_v5_stats import FpingV5Stats


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local fping v5 JSON smoke check.")
    parser.add_argument("--target", default="127.0.0.1")
    parser.add_argument("--period-ms", type=int, default=100)
    parser.add_argument("--timeout-ms", type=int, default=100)
    parser.add_argument("--count-json", type=int, default=20)
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / ".local" / "runtime" / "smoke" / "fping_v5"),
    )
    parser.add_argument("--fping-path", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_slug = args.target.replace(".", "_").replace(":", "_")
    raw_log = output_dir / f"fping_v5_raw_{target_slug}_{args.period_ms}ms.log"
    samples_jsonl = output_dir / f"fping_v5_samples_{target_slug}_{args.period_ms}ms.jsonl"
    summary_json = output_dir / f"fping_v5_summary_{target_slug}_{args.period_ms}ms.json"
    check_log = output_dir / "fping_v5_check.log"

    fping_path = Path(args.fping_path) if args.fping_path else None
    check = check_fping_v5_available(PROJECT_ROOT, fping_path)
    check_log.write_text(json.dumps(check.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("FPING_V5_CHECK")
    print(json.dumps(check.as_dict(), ensure_ascii=False, indent=2))
    if not check.available:
        return 2

    stats = FpingV5Stats()
    started_at = datetime.now().isoformat(timespec="seconds")
    json_count = 0
    print("FPING_V5_RUN")
    print(
        json.dumps(
            {
                "target": args.target,
                "period_ms": args.period_ms,
                "timeout_ms": args.timeout_ms,
                "count_json": args.count_json,
                "raw_log": str(raw_log),
                "samples_jsonl": str(samples_jsonl),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    for sample in run_fping_v5_json(
        target=args.target,
        period_ms=args.period_ms,
        timeout_ms=args.timeout_ms,
        count_json=args.count_json,
        output_jsonl_path=samples_jsonl,
        output_raw_log_path=raw_log,
        project_root=PROJECT_ROOT,
        fping_path=fping_path,
    ):
        json_count += 1
        stats.add(sample)
        if sample.raw_type in {"resp", "timeout"}:
            print(
                f"SAMPLE {json_count}: type={sample.raw_type} seq={sample.seq} "
                f"ok={sample.ok} rtt_ms={sample.rtt_ms} ts={sample.ts}"
            )
        else:
            print(f"SAMPLE {json_count}: type={sample.raw_type} ts={sample.ts}")

    ended_at = datetime.now().isoformat(timespec="seconds")
    summary = {
        "target": args.target,
        "period_ms": args.period_ms,
        "timeout_ms": args.timeout_ms,
        "json_count": json_count,
        **stats.as_dict(),
        "fping_path": check.fping_path,
        "started_at": started_at,
        "ended_at": ended_at,
        "raw_log": str(raw_log),
        "samples_jsonl": str(samples_jsonl),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FPING_V5_SUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if json_count > 0 and stats.sent_count > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
