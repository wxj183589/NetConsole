from __future__ import annotations

from netconsole.services.job_center.job_context import JobContext
from netconsole.services.traffic.local_adapter import (
    LocalTrafficAdapter,
    TASK_FPING,
    TASK_IPERF_CLIENT,
    TASK_IPERF_SERVER,
)


def _adapter(context: JobContext) -> LocalTrafficAdapter:
    return LocalTrafficAdapter(
        context.paths,
        site_name=str(context.params.get("site_name") or "demo"),
    )


def traffic_local_iperf_server(context: JobContext) -> dict[str, object]:
    return _adapter(context).execute_iperf_server(context)


def traffic_local_iperf_client(context: JobContext) -> dict[str, object]:
    return _adapter(context).execute_iperf_client(context)


def traffic_local_fping(context: JobContext) -> dict[str, object]:
    return _adapter(context).execute_high_frequency_ping(context)


HANDLERS = {
    TASK_IPERF_SERVER: traffic_local_iperf_server,
    TASK_IPERF_CLIENT: traffic_local_iperf_client,
    TASK_FPING: traffic_local_fping,
}


__all__ = ["HANDLERS"]
