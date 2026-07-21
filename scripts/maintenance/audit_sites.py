from __future__ import annotations

import argparse
import json
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import data_root as default_data_root
from netconsole.services.site_lifecycle import SiteAuditService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读审计 NetConsole 局点、Legacy 残留和 Demo 数据")
    parser.add_argument("--data-root", type=Path, default=None, help="默认使用当前源码开发数据根")
    parser.add_argument("--site-id", help="可选，只审计一个 site_id 或目录名")
    parser.add_argument("--output", type=Path, help="审计 JSON 输出路径；默认写入数据根 migrations/site-audits")
    args = parser.parse_args(argv)

    paths = PathResolver(data_root=(args.data_root or default_data_root()).expanduser().resolve())
    report = SiteAuditService(paths).audit_all(site_id=args.site_id, output=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
