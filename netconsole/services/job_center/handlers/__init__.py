from __future__ import annotations

from netconsole.services.job_center.job_registry import JobHandler


def builtin_handlers() -> dict[str, JobHandler]:
    from netconsole.services.job_center.handlers import (
        ac_jobs,
        config_jobs,
        device_jobs,
        file_jobs,
        mesh_jobs,
        network_jobs,
        online_mr_jobs,
        rail_transit_jobs,
        snmp_jobs,
        wifi_survey_jobs,
    )

    registry: dict[str, JobHandler] = {}
    for handlers in (
        device_jobs.HANDLERS,
        ac_jobs.HANDLERS,
        config_jobs.HANDLERS,
        file_jobs.HANDLERS,
        mesh_jobs.HANDLERS,
        network_jobs.HANDLERS,
        online_mr_jobs.HANDLERS,
        rail_transit_jobs.HANDLERS,
        snmp_jobs.HANDLERS,
        wifi_survey_jobs.HANDLERS,
    ):
        duplicates = registry.keys() & handlers.keys()
        if duplicates:
            raise ValueError(f"后台任务类型重复分区：{', '.join(sorted(duplicates))}")
        registry.update(handlers)
    return registry


__all__ = ["builtin_handlers"]
