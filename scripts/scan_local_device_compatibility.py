from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.device_compatibility.service import (
    DeviceCompatibilityService,
    scan_candidate_rows,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描本地已有设备资料并生成脱敏兼容性候选报告。")
    parser.add_argument("--input-json", type=Path, help="读取脱敏设备指纹 fixture，不访问本地数据根。")
    parser.add_argument("--output", type=Path, help="候选报告输出路径；默认写入数据根 temp/compatibility。")
    parser.add_argument("--full", action="store_true", help="全量复核已登记和未登记候选。")
    parser.add_argument("--report-only", action="store_true", help="只生成报告；当前为默认行为。")
    parser.add_argument("--apply", action="store_true", help="保留参数：必须人工确认命令/解析器/能力后才允许实现写入。")
    args = parser.parse_args()
    if args.apply:
        parser.error("--apply 尚未开放自动写入；请先人工确认 command_profile_id、parser_profile_id、capabilities 和 validation_level")

    paths = PathResolver()
    service = DeviceCompatibilityService(paths)
    if args.input_json:
        rows = json.loads(args.input_json.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit("input-json 必须是设备指纹对象数组")
        candidates = scan_candidate_rows(rows, service.profiles(), full=args.full)
    else:
        candidates = service.scan_local_candidates(full=args.full)

    output = args.output or (
        paths.temp_dir
        / "compatibility"
        / f"device-compatibility-candidates-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    output = output.resolve()
    paths.validate_runtime_write_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_type": "device_compatibility_candidates",
        "report_only": True,
        "candidate_count": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
        "redaction": {
            "omitted": [
                "site_name",
                "device_name",
                "device_uuid",
                "management_ip",
                "mac",
                "serial_number",
                "username",
                "password",
                "token",
                "raw_config",
                "raw_bootrom_text",
            ]
        },
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
