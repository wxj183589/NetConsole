from __future__ import annotations

import argparse
import asyncio
import os

from netconsole.services.agent.local_self_check import LocalAgentSelfCheck, LocalAgentSelfCheckReport


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="仅通过 localhost 验证 Agent fping/iPerf 生命周期")
    parser.add_argument("--agent-url", default="http://127.0.0.1:18080")
    parser.add_argument("--iperf-port", type=int, default=5201)
    parser.add_argument("--tcp-limit-mbps", type=float, default=2.0)
    parser.add_argument("--duration-sec", type=int, default=10)
    return parser


def _print_report(report: LocalAgentSelfCheckReport) -> None:
    print("Agent 本地联调 / 自检结果")
    print(f"- Agent 连接：{'通过' if report.agent_name else '失败'}")
    print(f"- Agent：{report.agent_name or '-'} / {report.agent_version or '-'}")
    print(
        "- 工具状态："
        + "，".join(
            f"{name}={'READY' if report.tool_ready.get(name) else 'NOT_READY'}"
            for name in ("mr_collector", "fping", "iperf3")
        )
    )
    print(
        f"- fping：{report.fping_status or '未执行'}，样本={report.fping_samples}，"
        f"日志行={report.fping_log_lines}，task_id={report.fping_task_id or '-'}"
    )
    print(
        f"- iPerf server：{report.iperf_server_status or '未执行'}，"
        f"task_id={report.iperf_server_task_id or '-'}"
    )
    print(
        f"- iPerf client：{report.iperf_client_status or '未执行'}，"
        f"日志行={report.iperf_client_log_lines}，task_id={report.iperf_client_task_id or '-'}"
    )
    print(f"- TCP 期望值：{report.tcp_requested_mbps:g} Mbps")
    for warning in report.warnings:
        print(f"- 警告：{warning}")
    for error in report.errors:
        print(f"- 失败：{error}")
    print(f"- 总体：{'PASSED' if report.passed else 'FAILED'}")


async def _run(args: argparse.Namespace) -> int:
    report = await LocalAgentSelfCheck().run(
        agent_url=args.agent_url,
        token=os.environ.get("NETCONSOLE_AGENT_TOKEN") or None,
        iperf_port=args.iperf_port,
        duration_sec=args.duration_sec,
        tcp_requested_mbps=args.tcp_limit_mbps,
    )
    _print_report(report)
    return 0 if report.passed else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError) as exc:
        print(f"Agent 本地自检失败：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
