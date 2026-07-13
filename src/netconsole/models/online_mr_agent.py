from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from pydantic import Field, SecretStr

from netconsole.models.api.common import ApiModel
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrStartRequest,
)
from netconsole.models.task_state import TaskState


class OnlineMrAgentStatus(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    STOPPED_WITH_WARNINGS = "stopped_with_warnings"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    FORCE_STOPPED = "force_stopped"
    ABORTED = "aborted"
    CANCELLED = "cancelled"


class OnlineMrAgentConnectionConfig(ApiModel):
    base_url: str = Field(min_length=8, max_length=500)
    token: SecretStr = Field(default_factory=lambda: SecretStr(""))
    timeout_sec: float = Field(default=15.0, gt=0, le=300)
    verify_tls: bool = True
    user_agent: str = "NetConsole-OnlineMR"
    max_download_bytes: int = Field(default=64 * 1024**3, ge=1)
    download_chunk_size: int = Field(
        default=1024 * 1024,
        ge=64 * 1024,
        le=8 * 1024 * 1024,
    )


class OnlineMrAgentPingResponse(ApiModel):
    status: str
    time: str = ""


class OnlineMrAgentSystemStatus(ApiModel):
    agent_id: str = Field(min_length=1)
    agent_name: str = ""
    version: str = Field(min_length=1)
    os: str = Field(min_length=1)
    arch: str = Field(min_length=1)
    current_tasks: int = Field(default=0, ge=0)
    task_count: int = Field(default=0, ge=0)
    package_count: int = Field(default=0, ge=0)


class OnlineMrAgentToolStatus(ApiModel):
    exists: bool = False
    ready: bool = False
    version: str = ""
    warning: str = ""


class OnlineMrAgentToolsStatus(ApiModel):
    mr_collector: OnlineMrAgentToolStatus
    fping: OnlineMrAgentToolStatus
    iperf3: OnlineMrAgentToolStatus


class OnlineMrAgentTaskStatusResponse(ApiModel):
    task_id: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    status: OnlineMrAgentStatus
    created_at: str = ""
    start_time: str = ""
    end_time: str = ""
    package_id: str = ""
    package_download_url: str = ""
    error_code: str = ""
    error_message: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class OnlineMrAgentPackageInfo(ApiModel):
    package_id: str = ""
    task_id: str = ""
    session_id: str = ""
    task_type: str = ""
    created_at: str = ""
    start_time: str = ""
    end_time: str = ""
    size: int = Field(default=0, ge=0)
    status: str = ""
    file_name: str = ""
    package_download_url: str = ""
    source_zip_sha256: str = ""


class OnlineMrAgentImportStatus(StrEnum):
    NOT_IMPORTED = "not_imported"
    ALREADY_IMPORTED = "already_imported"
    CONFLICT = "conflict"
    IMPORTED = "imported"
    UNKNOWN = "unknown"


class OnlineMrAgentDeviceMatchStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"


class OnlineMrAgentDeviceCandidate(ApiModel):
    device_id: int | str
    device_name: str
    mr_id: str = ""
    mr_name: str
    host: str
    device_type: str = ""


class OnlineMrAgentDeviceResolution(ApiModel):
    status: OnlineMrAgentDeviceMatchStatus
    source_host: str = ""
    candidates: tuple[OnlineMrAgentDeviceCandidate, ...] = ()
    error_code: str = ""
    message: str = ""

    @property
    def candidate(self) -> OnlineMrAgentDeviceCandidate | None:
        return self.candidates[0] if self.status is OnlineMrAgentDeviceMatchStatus.MATCHED else None


class OnlineMrAgentSyncedPackage(ApiModel):
    package_id: str
    file_name: str = ""
    task_id: str = ""
    session_id: str = ""
    task_type: str = ""
    status: str = ""
    size: int = Field(default=0, ge=0)
    created_at: str = ""
    start_time: str = ""
    end_time: str = ""
    source_device_id: str = ""
    source_device_name: str = ""
    source_host: str = ""
    candidate_local_device: OnlineMrAgentDeviceCandidate | None = None
    candidate_local_devices: tuple[OnlineMrAgentDeviceCandidate, ...] = ()
    candidate_match_method: str = ""
    import_status: OnlineMrAgentImportStatus = OnlineMrAgentImportStatus.UNKNOWN
    resolution_code: str = ""
    resolution_message: str = ""


class OnlineMrAgentPackageSyncResult(ApiModel):
    profile_id: str = ""
    ping: OnlineMrAgentPingResponse
    agent_status: OnlineMrAgentSystemStatus
    tools: OnlineMrAgentToolsStatus
    packages: tuple[OnlineMrAgentSyncedPackage, ...] = ()


class OnlineMrAgentConnectionResult(ApiModel):
    profile_id: str = ""
    ping: OnlineMrAgentPingResponse
    agent_status: OnlineMrAgentSystemStatus
    tools: OnlineMrAgentToolsStatus


class OnlineMrAgentDownloadResult(ApiModel):
    package_id: str
    path: Path
    sha256: str
    size: int = Field(ge=0)
    content_type: str = ""


class OnlineMrAgentTarget(ApiModel):
    name: str = Field(min_length=1)
    host: str = Field(min_length=1)
    protocol: str = "ssh"
    port: int = Field(default=22, ge=1, le=65535)
    username: str = ""
    password: SecretStr = SecretStr("")


class OnlineMrAgentCollectionItems(ApiModel):
    terminal_monitor: bool = True
    mesh_link: bool = True
    channel_busy: bool = True
    ap_radio_statistics: bool = True
    switch_history: bool = True
    interface_rate: bool = True
    wireless_status: bool = False


class OnlineMrAgentIntervals(ApiModel):
    mesh_link: int = Field(default=1, ge=1)
    channel_busy: int = Field(default=9, ge=1)
    ap_radio_statistics: int = Field(default=10, ge=1)
    switch_history: int = Field(default=300, ge=1)
    interface_rate: int = Field(default=2, ge=1)
    wireless_status: int = Field(default=3, ge=1)


class OnlineMrAgentRadio(ApiModel):
    mesh_link_radio: int = Field(default=1, ge=1)
    channel_busy_radio: int = Field(default=1, ge=1)
    ap_radio_statistics_radio: int = Field(default=1, ge=1)
    wireless_status_radio: int = Field(default=1, ge=1)


class OnlineMrAgentFpingTarget(ApiModel):
    name: str = "Ping 1"
    host: str


class OnlineMrAgentFpingConfig(ApiModel):
    enabled: bool = False
    template: str = ""
    targets: tuple[OnlineMrAgentFpingTarget, ...] = ()
    packet_size: int = Field(default=64, ge=1, le=65507)
    interval_ms: int = Field(default=1000, ge=1)
    timeout_ms: int = Field(default=4000, ge=1)
    loss_alarm_percent: float = Field(default=10.0, ge=0, le=100)
    latency_alarm_ms: int = Field(default=4000, ge=1)


class OnlineMrAgentIperfConfig(ApiModel):
    enabled: bool = False
    server_host: str = ""
    server_port: int = Field(default=5201, ge=1, le=65535)
    protocol: str = "tcp"
    direction: str = "upload"
    duration_sec: int = Field(default=0, ge=0)
    parallel: int = Field(default=1, ge=1)
    bandwidth_mbps: float = Field(default=0.0, ge=0)
    threshold_mbps: float = Field(default=0.0, ge=0)
    reverse: bool = False
    bidirectional: bool = False
    report_interval: float = Field(default=1.0, gt=0)
    packet_length: int = Field(default=0, ge=0)


class OnlineMrAgentDisplayContext(ApiModel):
    site: str = ""
    station: str = ""
    section: str = ""
    direction: str = ""


class OnlineMrAgentStartRequest(ApiModel):
    agent_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    site_name: str = ""
    device_id: int | str
    device_name: str = Field(min_length=1)
    mr_id: str = ""
    mr_name: str = Field(min_length=1)
    owner: str = "local"
    executor_kind: OnlineMrExecutorKind = OnlineMrExecutorKind.AGENT
    target: OnlineMrAgentTarget
    items: OnlineMrAgentCollectionItems
    intervals: OnlineMrAgentIntervals
    radio: OnlineMrAgentRadio
    fping: OnlineMrAgentFpingConfig = Field(default_factory=OnlineMrAgentFpingConfig)
    iperf: OnlineMrAgentIperfConfig = Field(default_factory=OnlineMrAgentIperfConfig)
    display_context: OnlineMrAgentDisplayContext = Field(default_factory=OnlineMrAgentDisplayContext)
    duration_minutes: int | None = Field(default=None, ge=1)
    stop_strategy: str = "controller"
    auto_package_on_stop: bool = True

    @classmethod
    def from_application_request(
        cls,
        request: OnlineMrStartRequest,
        *,
        display_context: OnlineMrAgentDisplayContext | None = None,
    ) -> OnlineMrAgentStartRequest:
        if request.executor_kind is not OnlineMrExecutorKind.AGENT or not request.agent_id:
            raise ValueError("Online MR Agent 请求必须指定 executor=AGENT 和 agent_id")
        config = request.config
        fping = config.fping.normalized()
        iperf = config.iperf.normalized()
        threshold = (
            iperf.report_threshold_mbps
            or iperf.tcp_report_threshold_mbps
            or iperf.udp_report_threshold_mbps
            or 0.0
        )
        return cls(
            agent_id=request.agent_id,
            site_id=request.site_id,
            site_name=request.site_id,
            device_id=request.device_id,
            device_name=request.device_name,
            mr_id=config.mr_id,
            mr_name=request.mr_name,
            owner=request.owner,
            target=OnlineMrAgentTarget(
                name=request.device_name,
                host=config.host,
                protocol=config.protocol.lower(),
                port=config.port,
                username=config.username,
                password=SecretStr(config.password),
            ),
            items=OnlineMrAgentCollectionItems(
                terminal_monitor=True,
                mesh_link=config.tasks.mesh_link,
                channel_busy=config.tasks.channel_busy,
                ap_radio_statistics=config.tasks.ap_radio_statistics,
                switch_history=config.tasks.switch_history,
                interface_rate=config.tasks.interface_rate,
                wireless_status=config.tasks.wireless_status,
            ),
            intervals=OnlineMrAgentIntervals(
                mesh_link=config.intervals.mesh_link,
                channel_busy=config.intervals.channel_busy,
                ap_radio_statistics=config.intervals.ap_radio_statistics,
                switch_history=config.intervals.switch_history,
                interface_rate=config.intervals.interface_rate,
                wireless_status=config.intervals.wireless_status,
            ),
            radio=OnlineMrAgentRadio(
                channel_busy_radio=config.radio.channel_busy_radio,
                ap_radio_statistics_radio=config.radio.ap_radio_statistics_radio,
                wireless_status_radio=config.radio.wireless_status_radio,
            ),
            fping=OnlineMrAgentFpingConfig(
                enabled=fping.enabled,
                template=fping.preset_name,
                targets=(OnlineMrAgentFpingTarget(host=fping.target),) if fping.target else (),
                packet_size=fping.packet_size,
                interval_ms=fping.interval_ms,
                timeout_ms=fping.loss_threshold_ms,
                loss_alarm_percent=fping.loss_warn_percent,
                latency_alarm_ms=fping.latency_warn_ms,
            ),
            iperf=OnlineMrAgentIperfConfig(
                enabled=iperf.enabled,
                server_host=iperf.server_ip,
                server_port=iperf.port,
                protocol=iperf.protocol.lower(),
                direction=iperf.direction,
                duration_sec=iperf.duration_seconds,
                parallel=iperf.parallel,
                bandwidth_mbps=iperf.udp_bitrate_mbps or iperf.tcp_pacing_mbps or 0.0,
                threshold_mbps=threshold,
                reverse=iperf.direction.lower() in {"download", "reverse"},
                report_interval=iperf.interval_seconds,
                packet_length=iperf.packet_length or 0,
            ),
            display_context=display_context or OnlineMrAgentDisplayContext(site=request.site_id),
            duration_minutes=config.duration_minutes,
            stop_strategy="agent_duration" if config.duration_minutes else "controller",
        )

    def transport_payload(self) -> dict[str, object]:
        """构造未来 Agent HTTP 私有请求；返回值不得写入日志、事件或采集包。"""
        target = self.target.model_dump(mode="json", exclude={"password"})
        target.update(
            {
                "id": self.mr_id or str(self.device_id),
                "type": "mr",
                "password": self.target.password.get_secret_value(),
            }
        )
        return {
            "target": target,
            "session": {
                "site": self.site_id,
                "site_id": self.site_id,
                "site_name": self.site_name,
                "device_id": str(self.device_id),
                "device_name": self.device_name,
                "mr_id": self.mr_id,
                "mr_name": self.mr_name,
                "owner": self.owner,
                "executor": self.executor_kind.value,
                "agent_id": self.agent_id,
            },
            "items": self.items.model_dump(mode="json"),
            "intervals": self.intervals.model_dump(mode="json"),
            "radio": self.radio.model_dump(mode="json"),
            "fping": self.fping.model_dump(mode="json"),
            "iperf": self.iperf.model_dump(mode="json"),
            "display_context": self.display_context.model_dump(mode="json"),
            "duration_minutes": self.duration_minutes,
            "stop_strategy": self.stop_strategy,
            "auto_package_on_stop": self.auto_package_on_stop,
        }

    def public_payload(self) -> dict[str, object]:
        payload = self.transport_payload()
        payload["target"] = {key: value for key, value in dict(payload["target"]).items() if key != "password"}
        return payload


class OnlineMrAgentStartResponse(ApiModel):
    success: bool
    agent_task_id: str = ""
    session_id: str = ""
    task_type: str = "mr_realtime_collect"
    status: str = ""
    started_at: str | None = None
    message: str = ""
    error_code: str = ""
    error_message: str = ""


class OnlineMrAgentStatusResponse(OnlineMrAgentStartResponse):
    ended_at: str | None = None
    duration_minutes: float | None = None
    phase: str = ""
    collectors: dict[str, object] = Field(default_factory=dict)
    fping_status: dict[str, object] = Field(default_factory=dict)
    iperf_status: dict[str, object] = Field(default_factory=dict)
    package_status: str = ""
    package_id: str = ""
    package_download_url: str = ""
    error_summary: str = ""
    data_integrity: str = "unknown"


class OnlineMrAgentStopResponse(ApiModel):
    success: bool
    status: str = ""
    stop_reason: str = ""
    package_status: str = ""
    package_id: str = ""
    error_summary: str = ""


class OnlineMrAgentStateMapping(ApiModel):
    task_state: TaskState
    phase: OnlineMrPhase
    mapping_state: OnlineMrMappingState
    remote_terminal: bool = False
    controller_terminal: bool = False
    warning: bool = False
    force_stopped: bool = False
    package_required: bool = False
    data_integrity: str = "unknown"


def map_online_mr_agent_status(
    status: OnlineMrAgentStatus | str,
    *,
    package_imported: bool = False,
    package_failed: bool = False,
) -> OnlineMrAgentStateMapping:
    selected = OnlineMrAgentStatus(str(status).lower())
    active = {
        OnlineMrAgentStatus.CREATED: (TaskState.STARTING, OnlineMrPhase.PREPARING_TASK, OnlineMrMappingState.PENDING_SESSION),
        OnlineMrAgentStatus.STARTING: (TaskState.STARTING, OnlineMrPhase.STARTING_COLLECTION, OnlineMrMappingState.PENDING_SESSION),
        OnlineMrAgentStatus.RUNNING: (TaskState.RUNNING, OnlineMrPhase.COLLECTING, OnlineMrMappingState.LINKED),
        OnlineMrAgentStatus.STOPPING: (TaskState.STOPPING, OnlineMrPhase.STOPPING_TRAFFIC, OnlineMrMappingState.LINKED),
    }
    if selected in active:
        task_state, phase, mapping_state = active[selected]
        return OnlineMrAgentStateMapping(task_state=task_state, phase=phase, mapping_state=mapping_state)

    warning = selected in {OnlineMrAgentStatus.STOPPED_WITH_WARNINGS, OnlineMrAgentStatus.COMPLETED_WITH_WARNINGS}
    completed = selected in {
        OnlineMrAgentStatus.STOPPED,
        OnlineMrAgentStatus.STOPPED_WITH_WARNINGS,
        OnlineMrAgentStatus.COMPLETED,
        OnlineMrAgentStatus.COMPLETED_WITH_WARNINGS,
    }
    if completed and package_failed:
        return OnlineMrAgentStateMapping(
            task_state=TaskState.FAILED,
            phase=OnlineMrPhase.TERMINAL,
            mapping_state=OnlineMrMappingState.TERMINAL,
            remote_terminal=True,
            controller_terminal=True,
            warning=True,
        )
    if completed and not package_imported:
        return OnlineMrAgentStateMapping(
            task_state=TaskState.RUNNING,
            phase=OnlineMrPhase.FINALIZING,
            mapping_state=OnlineMrMappingState.LINKED,
            remote_terminal=True,
            warning=warning,
            package_required=True,
        )
    if completed:
        return OnlineMrAgentStateMapping(
            task_state=TaskState.COMPLETED,
            phase=OnlineMrPhase.TERMINAL,
            mapping_state=OnlineMrMappingState.TERMINAL,
            remote_terminal=True,
            controller_terminal=True,
            warning=warning,
            data_integrity="unknown" if warning else "complete",
        )
    if selected is OnlineMrAgentStatus.FAILED:
        task_state, integrity = TaskState.FAILED, "unknown"
    elif selected is OnlineMrAgentStatus.FORCE_STOPPED:
        task_state, integrity = TaskState.CANCELLED, "partial"
    else:
        task_state, integrity = TaskState.CANCELLED, "unknown"
    return OnlineMrAgentStateMapping(
        task_state=task_state,
        phase=OnlineMrPhase.TERMINAL,
        mapping_state=OnlineMrMappingState.TERMINAL,
        remote_terminal=True,
        controller_terminal=True,
        warning=selected in {OnlineMrAgentStatus.FORCE_STOPPED, OnlineMrAgentStatus.ABORTED},
        force_stopped=selected is OnlineMrAgentStatus.FORCE_STOPPED,
        data_integrity=integrity,
    )


ONLINE_MR_AGENT_PACKAGE_REQUIRED_DIRECTORIES = frozenset({"raw", "parsed", "view", "logs", "outputs"})
ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES = frozenset(
    {
        "session_meta.json",
        "manifest.json",
        "task.json",
        "stop_reason.json",
        "agent_info.json",
        "system_info.json",
        *(f"raw/{name}" for name in (
            "init_raw.log",
            "config_collect_raw.log",
            "terminal_monitor_raw.log",
            "mesh_link_raw.log",
            "channel_busy_raw.log",
            "ap_radio_statistics_raw.log",
            "switch_history_latest.log",
            "interface_rate_raw.log",
            "wireless_status_raw.log",
            "collector_output_raw.log",
            "fping_v5_raw.log",
            "fping_v5_samples.jsonl",
            "fping_v5_final_summary.json",
            "iperf_client_raw.log",
        )),
    }
)


def validate_online_mr_agent_package_entries(entries: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    issues: list[str] = []
    for raw in entries:
        raw_value = str(raw or "").replace("\\", "/").strip()
        value = raw_value.strip("/")
        parts = PurePosixPath(value).parts
        if not value or raw_value.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", value):
            issues.append(f"不安全的包路径：{raw}")
            continue
        if not value.endswith("/"):
            normalized.append(value)
    roots = {PurePosixPath(value).parts[0] for value in normalized if len(PurePosixPath(value).parts) > 1}
    if len(roots) == 1 and all(len(PurePosixPath(value).parts) > 1 for value in normalized):
        root = next(iter(roots))
        normalized = [value[len(root) + 1 :] for value in normalized]
    values = set(normalized)
    for required in sorted(ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES - values):
        issues.append(f"缺少必须文件：{required}")
    for value in sorted(values):
        lowered = value.lower()
        if lowered == "stop.request" or lowered == "meta/request.private.json" or lowered.endswith(".tmp"):
            issues.append(f"包内禁止文件：{value}")
    return tuple(issues)


__all__ = [name for name in globals() if name.startswith("OnlineMr") or name.startswith("ONLINE_MR")]
