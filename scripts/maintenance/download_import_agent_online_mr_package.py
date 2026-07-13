from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from pydantic import SecretStr

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_agent import OnlineMrAgentConnectionConfig
from netconsole.services.online_mr.agent_controller_service import (
    OnlineMrAgentControllerService,
)
from netconsole.services.online_mr.agent_http_client import (
    OnlineMrAgentClientError,
    OnlineMrAgentHttpClient,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="查询 Agent 已有 Online MR 采集包，并手工下载导入当前局点"
    )
    parser.add_argument("--agent-url", required=True, help="Agent HTTP 地址")
    parser.add_argument(
        "--token",
        default=os.environ.get("NETCONSOLE_AGENT_TOKEN", ""),
        help="Agent Token；也可使用 NETCONSOLE_AGENT_TOKEN 环境变量",
    )
    parser.add_argument("--package-id", default="", help="省略时只列出采集包")
    parser.add_argument(
        "--list-packages-with-match",
        action="store_true",
        help="只读同步采集包，并显示当前局点的设备 IP 候选与导入状态",
    )
    parser.add_argument(
        "--auto-resolve-by-ip",
        action="store_true",
        help="按 Agent 采集目标 IP 唯一匹配当前局点正式设备",
    )
    parser.add_argument("--site", default="", help="目标局点 ID")
    parser.add_argument("--site-name", default="", help="局点显示名，默认同 --site")
    parser.add_argument("--device-id", default="", help="目标设备 ID")
    parser.add_argument("--device-name", default="", help="目标设备名称")
    parser.add_argument("--mr-id", default="", help="可选 MR ID")
    parser.add_argument("--mr-name", default="", help="MR 名称")
    parser.add_argument("--expected-session-id", default="")
    parser.add_argument("--controller-task-id", default="")
    parser.add_argument(
        "--identity-match-policy",
        choices=("strict", "ip_match", "manual_override"),
        default="strict",
        help="Agent 来源身份与 Controller 正式身份的匹配策略",
    )
    parser.add_argument(
        "--expected-host", default="", help="ip_match 使用的正式设备 IP"
    )
    parser.add_argument(
        "--allow-identity-override",
        action="store_true",
        help="允许 manual_override 将 Agent 临时身份映射到指定正式设备",
    )
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-download-bytes", type=int, default=64 * 1024**3)
    return parser


def _missing_import_arguments(args: argparse.Namespace) -> list[str]:
    if args.auto_resolve_by_ip:
        return [] if str(args.site or "").strip() else ["--site"]
    return [
        option
        for option, value in (
            ("--site", args.site),
            ("--device-id", args.device_id),
            ("--device-name", args.device_name),
            ("--mr-name", args.mr_name),
        )
        if not str(value or "").strip()
    ]


async def _run(args: argparse.Namespace) -> int:
    config = OnlineMrAgentConnectionConfig(
        base_url=args.agent_url,
        token=SecretStr(args.token),
        timeout_sec=args.timeout,
        max_download_bytes=args.max_download_bytes,
    )
    paths = PathResolver(data_root=args.data_root)
    service = OnlineMrAgentControllerService(
        paths,
        OnlineMrAgentHttpClient(config),
    )
    synchronized = None
    try:
        if args.list_packages_with_match or args.auto_resolve_by_ip:
            synchronized = await service.sync_agent_packages(site_id=args.site)
            ping = synchronized.ping
            status = synchronized.agent_status
            tools = synchronized.tools
            packages = synchronized.packages
        else:
            ping = await service.ping_agent()
            status = await service.get_agent_status()
            tools = await service.get_agent_tools()
            packages = await service.list_agent_packages()
    except OnlineMrAgentClientError as exc:
        print(f"Agent 查询失败 [{exc.code}]：{exc.message}")
        return 2

    print("Online MR Agent 采集包")
    print(
        f"- Agent：{status.agent_name or status.agent_id} "
        f"({status.version}, {status.os}/{status.arch})"
    )
    print(f"- Ping：{ping.status}")
    print(
        "- 工具："
        f"MR={'READY' if tools.mr_collector.ready else 'NOT_READY'}，"
        f"fping={'READY' if tools.fping.ready else 'NOT_READY'}，"
        f"iPerf3={'READY' if tools.iperf3.ready else 'NOT_READY'}"
    )
    if not packages:
        print("- 采集包：无")
    for item in packages:
        print(
            f"- {item.package_id or item.file_name or '<无 package_id>'} | "
            f"{item.task_type or 'unknown'} | "
            f"{item.status or 'unknown'} | {item.size} bytes | "
            f"{item.end_time or item.created_at or 'unknown'}"
        )
        if synchronized is not None:
            candidate = item.candidate_local_device
            print(
                "  来源："
                f"{item.source_device_id or '-'} / "
                f"{item.source_device_name or '-'} / {item.source_host or '-'}"
            )
            print(
                "  候选："
                f"{candidate.device_id if candidate else '-'} / "
                f"{candidate.device_name if candidate else '-'} | "
                f"匹配={item.candidate_match_method or '-'} | "
                f"导入={item.import_status.value}"
            )
            if item.resolution_message:
                print(f"  说明：{item.resolution_message}")

    package_id = str(args.package_id or "").strip()
    if not package_id:
        return 0
    selected = next((item for item in packages if item.package_id == package_id), None)
    if selected is None:
        print(
            "导入失败 [ONLINE_MR_AGENT_PACKAGE_NOT_READY]：包列表中不存在指定 package_id"
        )
        return 2
    if selected.task_type and selected.task_type != "mr_realtime_collect":
        print("导入失败 [ONLINE_MR_AGENT_PACKAGE_INVALID]：指定包不是 Online MR 采集包")
        return 2

    try:
        if args.auto_resolve_by_ip:
            result = await service.download_import_agent_package(
                package_id,
                site_id=args.site,
                site_name=args.site_name or args.site,
                owner="agent_package_sync",
                identity_match_policy=args.identity_match_policy,
                auto_resolve_by_ip=True,
            )
        else:
            result = await service.download_import_package(
                package_id,
                site_id=args.site,
                site_name=args.site_name or args.site,
                device_id=args.device_id,
                device_name=args.device_name,
                mr_id=args.mr_id,
                mr_name=args.mr_name,
                owner="manual_agent_import",
                expected_session_id=args.expected_session_id or None,
                controller_task_id=args.controller_task_id or None,
                agent_task_id=selected.task_id or None,
                agent_id=status.agent_id,
                identity_match_policy=args.identity_match_policy,
                expected_host=args.expected_host,
                allow_identity_override=args.allow_identity_override,
                source_package_id=selected.package_id,
            )
    except OnlineMrAgentClientError as exc:
        print(f"导入失败 [{exc.code}]：{exc.message}")
        return 2

    state = (
        "ALREADY_IMPORTED"
        if result.already_imported
        else "IMPORTED"
        if result.success
        else "CONFLICT"
        if result.conflict
        else "FAILED"
    )
    print(f"导入结果：{state}")
    print(f"- Task ID：{result.task_id or '-'}")
    print(f"- Session ID：{result.session_id or '-'}")
    print(f"- Session 目录：{result.session_dir or '-'}")
    print(f"- 下载 ZIP：{result.downloaded_path or '已清理'}")
    print(f"- 源 ZIP SHA-256：{result.source_zip_sha256 or '-'}")
    if result.session_dir:
        try:
            manifest = json.loads(
                (result.session_dir / "import_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            identity = manifest.get("identity") or {}
            source = identity.get("source") or {}
            resolved = identity.get("resolved") or {}
            print(
                "- Agent 包身份："
                f"{source.get('device_id') or '-'} / "
                f"{source.get('device_name') or '-'} / "
                f"{source.get('host') or '-'}"
            )
            print(
                "- 本地设备身份："
                f"{resolved.get('device_id') or '-'} / "
                f"{resolved.get('device_name') or '-'}"
            )
            print(f"- 匹配方式：{identity.get('match_method') or '-'}")
        except (OSError, json.JSONDecodeError, AttributeError):
            print("- 身份追溯：import_manifest.json 无法读取")
    if result.error_code:
        print(f"- 错误码：{result.error_code}")
    for warning in result.warnings:
        print(f"- 警告：{warning}")
    for error in result.errors:
        print(f"- 错误：{error}")
    if result.task_id:
        print(
            "- 验收命令：python -m scripts.maintenance.check_online_mr_session_state "
            f'--task-id "{result.task_id}"'
        )
    return 0 if result.success else 3


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.list_packages_with_match and not str(args.site or "").strip():
        parser.error("--list-packages-with-match 必须提供 --site")
    if args.auto_resolve_by_ip and args.identity_match_policy != "ip_match":
        parser.error("--auto-resolve-by-ip 必须使用 --identity-match-policy ip_match")
    if args.package_id:
        missing = _missing_import_arguments(args)
        if missing:
            parser.error(f"下载导入时必须提供：{', '.join(missing)}")
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError) as exc:
        print(f"手工下载导入失败：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
