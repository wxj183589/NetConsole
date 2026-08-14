from __future__ import annotations

import hashlib
import ipaddress
import random
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import is_device_eligible_for_automatic_collection
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrStartRequest,
)
from netconsole.models.online_mr_models import (
    FpingConfig,
    IperfTrafficConfig,
    OnlineMrConnectionConfig,
    OnlineMrIntervals,
    OnlineMrRadioConfig,
    OnlineMrTaskToggles,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.fleet_ping import FleetPingSupervisor
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.concurrency_policy import (
    OnlineMrConcurrencyBudget,
    OnlineMrConcurrencyPolicy,
)
from netconsole.services.online_mr.errors import (
    OnlineMrApplicationError,
    OnlineMrQueryError,
)
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)


@dataclass(frozen=True)
class SchedulerCandidate:
    train_id: str
    rank: tuple[Any, ...]
    reason: str


class DeepMrCollectionScheduler:
    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        repository: GroundUnattendedRepository,
        application_service: OnlineMrApplicationService,
        query_service: OnlineMrQueryService,
        base_query: RailTransitBaseDataQueryService,
        fleet_ping: FleetPingSupervisor,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.application_service = application_service
        self.query_service = query_service
        self.base_query = base_query
        self.fleet_ping = fleet_ping
        self.policy = OnlineMrConcurrencyPolicy(application_service.task_service)
        self._lock = threading.RLock()
        self._stop_executor = ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="ground-mr-finalize"
        )
        self._stop_futures: dict[str, Future] = {}
        self._last_batch_at = 0.0

    def recover(self, run_id: str) -> None:
        try:
            self.application_service.recover_mappings(site_id=self.site_id)
        except OnlineMrApplicationError as exc:
            self.repository.add_event(
                run_id=run_id,
                event_type="deep_recovery_failed",
                severity="warning",
                title="Online MR 任务映射恢复失败",
                message=exc.message,
            )
        self._synchronize_operations(run_id, self.repository.get_profile())

    def tick(
        self, run_id: str, profile, trains: list[dict[str, Any]], *, paused: bool
    ) -> None:
        with self._lock:
            self._synchronize_operations(run_id, profile)
            operations = self._active_operations()
            self._request_required_stops(run_id, profile, trains, operations)
            self._collect_finished_stop_futures(run_id)
            if paused:
                return
            self._fill_slots(run_id, profile, trains, operations)

    def stop_all(
        self, run_id: str, *, reason: str, max_finalizing_mrs: int = 2
    ) -> None:
        with self._lock:
            allocations = self.policy.allocations(
                self.site_id, self._active_operations()
            )
            finalizing = sum(
                allocation.operation.phase
                in {
                    OnlineMrPhase.STOPPING_TRAFFIC,
                    OnlineMrPhase.STOPPING_COLLECTION,
                    OnlineMrPhase.FINALIZING,
                    OnlineMrPhase.PARSING,
                    OnlineMrPhase.PACKAGING,
                }
                for allocation in allocations
            ) + sum(not future.done() for future in self._stop_futures.values())
            for allocation in allocations:
                if allocation.automated:
                    if finalizing >= max(1, int(max_finalizing_mrs)):
                        break
                    self._submit_stop(
                        run_id, allocation.operation.controller_task_id, reason
                    )
                    finalizing += 1

    def has_active_automated(self) -> bool:
        return any(
            allocation.automated
            for allocation in self.policy.allocations(
                self.site_id, self._active_operations()
            )
        ) or any(not future.done() for future in self._stop_futures.values())

    def active_automated_operation_ids(self) -> list[str]:
        operation_ids = {
            allocation.operation.controller_task_id
            for allocation in self.policy.allocations(
                self.site_id, self._active_operations()
            )
            if allocation.automated
        }
        operation_ids.update(
            operation_id
            for operation_id, future in self._stop_futures.items()
            if not future.done()
        )
        return sorted(operation_ids)

    def close(self) -> None:
        self._stop_executor.shutdown(wait=True, cancel_futures=False)

    @staticmethod
    def ordered_candidates(
        trains: list[dict[str, Any]],
        *,
        queue_order: list[str],
        ping_loss_by_train: dict[str, float] | None = None,
    ) -> list[SchedulerCandidate]:
        ping_loss_by_train = ping_loss_by_train or {}
        queue_index = {train_id: index for index, train_id in enumerate(queue_order)}
        eligible = [row for row in trains if row.get("deep_collection_eligible")]
        first_round = [
            row for row in eligible if int(row.get("covered_rounds") or 0) == 0
        ]
        pool = first_round or eligible
        result = []
        for row in pool:
            pinned = bool(row.get("priority"))
            policy_priority = int(row.get("scheduling_priority") or 0)
            attempts = int(row.get("attempt_count") or 0)
            status = str(row.get("coverage_status") or "NOT_SEEN")
            if first_round:
                reason = (
                    "置顶列车今日尚未完成第一轮"
                    if pinned
                    else "今日从未进行深度采集"
                    if attempts == 0
                    else "今日部分结果等待补采"
                    if status == "PARTIAL"
                    else "今日第一轮尚未完成"
                )
                rank = (
                    0 if pinned else 1,
                    -policy_priority,
                    0 if attempts == 0 else 1,
                    0 if status == "PARTIAL" else 1,
                    attempts,
                    queue_index.get(row["train_id"], 10**9),
                )
            else:
                reason = "全部可采集列车已完成第一轮，进入后续轮次"
                rank = (
                    0 if pinned else 1,
                    -policy_priority,
                    attempts,
                    -float(ping_loss_by_train.get(row["train_id"], 0.0)),
                    queue_index.get(row["train_id"], 10**9),
                )
            result.append(SchedulerCandidate(row["train_id"], rank, reason))
        return sorted(result, key=lambda item: item.rank)

    def _fill_slots(self, run_id, profile, trains, operations) -> None:
        import time

        now_monotonic = time.monotonic()
        if now_monotonic - self._last_batch_at < profile.start_jitter_seconds:
            return
        allocations = self.policy.allocations(self.site_id, operations)
        active_auto_trains = {
            row["train_id"]
            for row in self.repository.list_deep_operations(run_id, active_only=True)
        }
        train_slots = max(0, profile.max_active_trains - len(active_auto_trains))
        mr_slots = max(0, profile.max_active_mrs - len(allocations))
        starting = sum(
            item.operation.phase
            in {
                OnlineMrPhase.VALIDATING,
                OnlineMrPhase.PREPARING_TASK,
                OnlineMrPhase.PREPARING_SESSION,
                OnlineMrPhase.CONNECTING,
                OnlineMrPhase.STARTING_COLLECTION,
            }
            for item in allocations
        )
        starting_slots = max(0, profile.max_starting_mrs - starting)
        if not mr_slots or not starting_slots:
            return
        queue = self._ensure_queue(run_id, trains)
        loss: dict[str, float] = {}
        for row in self.repository.list_ping_summaries(run_id):
            train_id = str(row.get("train_id") or "")
            loss[train_id] = max(
                loss.get(train_id, 0.0),
                float(row.get("loss_rate_percent") or 0),
            )
        candidates = self.ordered_candidates(
            trains, queue_order=queue, ping_loss_by_train=loss
        )
        candidates = sorted(
            candidates,
            key=lambda item: (
                0 if item.train_id in active_auto_trains else 1,
                item.rank,
            ),
        )
        active_devices = {str(item.operation.device_id) for item in allocations}
        train_by_id = {row["train_id"]: row for row in trains}
        started_in_batch = 0
        for candidate in candidates:
            if mr_slots <= 0 or starting_slots <= 0:
                break
            active_train = candidate.train_id in active_auto_trains
            if not active_train and train_slots <= 0:
                continue
            train = train_by_id[candidate.train_id]
            current_cycle = (
                dict(train.get("operations") or {})
                if str(train.get("coverage_status") or "") == "COLLECTING"
                else {}
            )
            endpoints = self._startable_endpoints(train, active_devices)
            if not endpoints:
                continue
            selected = endpoints[
                : min(
                    mr_slots,
                    starting_slots,
                    profile.start_batch_size - started_in_batch,
                )
            ]
            if not selected:
                break
            operations_by_end: dict[str, str] = {}
            failures = []
            for endpoint in selected:
                decision = self.policy.can_start(
                    site_id=self.site_id,
                    device_id=endpoint["device_id"],
                    operations=self._active_operations(),
                    budget=OnlineMrConcurrencyBudget(
                        max_active_mrs=profile.max_active_mrs,
                        max_starting_mrs=profile.max_starting_mrs,
                        max_finalizing_mrs=profile.max_finalizing_mrs,
                    ),
                    automated=True,
                )
                if not decision.allowed:
                    failures.append(decision.message)
                    continue
                try:
                    request = self._build_start_request(endpoint, profile)
                    self.repository.add_event(
                        run_id=run_id,
                        event_type="unattended_deep_fping_starting",
                        train_id=candidate.train_id,
                        mr_id=str(endpoint.get("mr_id") or ""),
                        title="无人值守深采 fping 正在启动",
                        details={
                            "site_id": self.site_id,
                            "run_id": run_id,
                            "train_id": candidate.train_id,
                            "mr_side": str(endpoint.get("endpoint") or ""),
                            "device_id": endpoint.get("device_id"),
                            "target_ip": request.config.fping.target,
                        },
                    )
                    operation = self.application_service.start_local_collection(request)
                    endpoint_code = str(endpoint.get("endpoint") or "")
                    operations_by_end[endpoint_code] = operation.controller_task_id
                    active_devices.add(str(endpoint["device_id"]))
                    self.repository.save_deep_operation(
                        {
                            "operation_id": operation.controller_task_id,
                            "site_id": self.site_id,
                            "run_id": run_id,
                            "train_id": candidate.train_id,
                            "mr_id": str(endpoint.get("mr_id") or ""),
                            "mr_position_code": endpoint_code,
                            "session_id": operation.session_id or "",
                            "state": "STARTING",
                            "started_at": operation.started_at
                            or datetime.now()
                            .astimezone()
                            .isoformat(timespec="milliseconds"),
                            "ended_at": "",
                            "stop_reason": "",
                            "error_summary": "",
                            "finalization_complete": 0,
                            "package_verified": 0,
                            "updated_at": datetime.now()
                            .astimezone()
                            .isoformat(timespec="milliseconds"),
                        }
                    )
                    started_in_batch += 1
                    mr_slots -= 1
                    starting_slots -= 1
                except (OnlineMrApplicationError, ValueError) as exc:
                    failures.append(str(exc))
            if operations_by_end:
                previous_operations = current_cycle
                previous_operations.update(operations_by_end)
                self.repository.update_train_run(
                    run_id,
                    candidate.train_id,
                    coverage_status="COLLECTING",
                    attempt_count=int(train.get("attempt_count") or 0)
                    + (0 if active_train or current_cycle else 1),
                    selection_reason=str(train.get("selection_reason") or "")
                    if active_train or current_cycle
                    else candidate.reason,
                    failure_reason="；".join(failures),
                    collection_started_at=str(train.get("collection_started_at") or "")
                    if active_train or current_cycle
                    else datetime.now().astimezone().isoformat(timespec="milliseconds"),
                    operations_json=previous_operations,
                )
                self.repository.add_event(
                    run_id=run_id,
                    event_type="deep_collection_started",
                    train_id=candidate.train_id,
                    title="无人值守深度 MR 采集已启动",
                    message=candidate.reason,
                    details={
                        "operations": operations_by_end,
                        "iperf_enabled": False,
                        "session_fping_enabled": True,
                        "fping_required": True,
                    },
                )
                if not active_train:
                    train_slots -= 1
                active_auto_trains.add(candidate.train_id)
            elif failures:
                self.repository.update_train_run(
                    run_id,
                    candidate.train_id,
                    failure_reason="；".join(failures),
                )
            if started_in_batch >= profile.start_batch_size:
                break
        if started_in_batch:
            self._last_batch_at = now_monotonic

    @staticmethod
    def _startable_endpoints(
        train: dict[str, Any], active_devices: set[str]
    ) -> list[dict[str, Any]]:
        current_cycle = (
            set((train.get("operations") or {}).keys())
            if str(train.get("coverage_status") or "") == "COLLECTING"
            else set()
        )
        return [
            row
            for row in train.get("endpoints", [])
            if row.get("device_id") is not None
            and row.get("management_ip")
            and str(row.get("device_id")) not in active_devices
            and str(row.get("endpoint") or "") not in current_cycle
        ]

    def _request_required_stops(self, run_id, profile, trains, operations) -> None:
        train_by_id = {row["train_id"]: row for row in trains}
        deep_rows = {
            row["operation_id"]: row
            for row in self.repository.list_deep_operations(run_id, active_only=True)
        }
        allocations = self.policy.allocations(self.site_id, operations)
        finalizing = sum(
            allocation.operation.phase
            in {
                OnlineMrPhase.STOPPING_TRAFFIC,
                OnlineMrPhase.STOPPING_COLLECTION,
                OnlineMrPhase.FINALIZING,
                OnlineMrPhase.PARSING,
                OnlineMrPhase.PACKAGING,
            }
            for allocation in allocations
        ) + sum(not future.done() for future in self._stop_futures.values())
        for allocation in allocations:
            if not allocation.automated:
                continue
            if finalizing >= profile.max_finalizing_mrs:
                break
            operation = allocation.operation
            deep = deep_rows.get(operation.controller_task_id)
            if deep is None:
                continue
            train = train_by_id.get(deep["train_id"])
            if train is None:
                continue
            eligibility = str(train.get("eligibility_status") or "")
            if eligibility in {"AC_STALE", "AC_UNKNOWN", "AP_UNMATCHED"}:
                continue
            if not train.get("deep_collection_eligible"):
                self._submit_stop(
                    run_id,
                    operation.controller_task_id,
                    eligibility.lower() or "left_mainline",
                )
                finalizing += 1
                continue
            if (
                float(operation.duration_minutes or 0)
                >= profile.preferred_collection_minutes
            ):
                self._submit_stop(
                    run_id, operation.controller_task_id, "preferred_duration_reached"
                )
                finalizing += 1

    def _submit_stop(self, run_id: str, operation_id: str, reason: str) -> None:
        if operation_id in self._stop_futures:
            return
        self._stop_futures[operation_id] = self._stop_executor.submit(
            self.application_service.stop_operation,
            operation_id,
            site_id=self.site_id,
            stop_reason=f"ground_unattended:{reason}",
        )
        self.repository.add_event(
            run_id=run_id,
            event_type="deep_collection_stop_requested",
            title="无人值守深度采集已请求正常停止",
            details={"operation_id": operation_id, "reason": reason},
        )

    def _collect_finished_stop_futures(self, run_id: str) -> None:
        for operation_id, future in tuple(self._stop_futures.items()):
            if not future.done():
                continue
            self._stop_futures.pop(operation_id, None)
            try:
                future.result()
            except Exception as exc:
                self.repository.add_event(
                    run_id=run_id,
                    event_type="deep_collection_stop_failed",
                    severity="error",
                    title="无人值守深度采集停止失败",
                    message=f"{exc.__class__.__name__}: {exc}",
                    details={"operation_id": operation_id},
                )

    def _synchronize_operations(self, run_id: str, profile) -> None:
        operations = {
            item.controller_task_id: item
            for item in self.application_service.list_operations(
                site_id=self.site_id, limit=1000
            )
        }
        deep_rows = self.repository.list_deep_operations(run_id)
        for row in deep_rows:
            operation = operations.get(row["operation_id"])
            if operation is None:
                if row["state"] not in {"COMPLETED", "PARTIAL", "FAILED"}:
                    self._mark_operation_partial(
                        row, "软件重启后无法恢复对应 Online MR 任务映射"
                    )
                continue
            if operation.phase is not OnlineMrPhase.TERMINAL:
                state = (
                    "FINALIZING"
                    if operation.phase
                    in {
                        OnlineMrPhase.STOPPING_TRAFFIC,
                        OnlineMrPhase.STOPPING_COLLECTION,
                        OnlineMrPhase.FINALIZING,
                        OnlineMrPhase.PARSING,
                        OnlineMrPhase.PACKAGING,
                    }
                    else "RUNNING"
                )
                if operation.phase in {
                    OnlineMrPhase.VALIDATING,
                    OnlineMrPhase.PREPARING_TASK,
                    OnlineMrPhase.PREPARING_SESSION,
                    OnlineMrPhase.CONNECTING,
                    OnlineMrPhase.STARTING_COLLECTION,
                }:
                    state = "STARTING"
                self.repository.save_deep_operation(
                    {
                        **row,
                        "session_id": operation.session_id or row.get("session_id", ""),
                        "state": state,
                        "updated_at": datetime.now()
                        .astimezone()
                        .isoformat(timespec="milliseconds"),
                        "finalization_complete": int(
                            bool(row.get("finalization_complete"))
                        ),
                        "package_verified": int(bool(row.get("package_verified"))),
                    }
                )
                if state == "RUNNING" and row.get("state") == "STARTING":
                    self._record_fping_started(run_id, row, operation)
                continue
            success, reason, session_id = self._verify_terminal_operation(
                operation, profile
            )
            self.repository.save_deep_operation(
                {
                    **row,
                    "session_id": session_id,
                    "state": "COMPLETED" if success else "PARTIAL",
                    "ended_at": operation.ended_at
                    or datetime.now().astimezone().isoformat(timespec="milliseconds"),
                    "stop_reason": operation.stop_reason,
                    "error_summary": reason,
                    "finalization_complete": int(success),
                    "package_verified": int(success),
                    "updated_at": datetime.now()
                    .astimezone()
                    .isoformat(timespec="milliseconds"),
                }
            )
        self._update_train_coverage(run_id, profile)

    def _verify_terminal_operation(self, operation, profile) -> tuple[bool, str, str]:
        if not operation.session_id:
            return False, operation.error_summary or "未创建 Online MR Session", ""
        try:
            detail = self.query_service.get_session(self.site_id, operation.session_id)
            collectors = self.query_service.list_collectors(
                self.site_id, operation.session_id
            )
            artifacts = self.query_service.list_artifacts(
                self.site_id, operation.session_id
            )
        except OnlineMrQueryError as exc:
            return False, exc.message, operation.session_id
        mesh = next((item for item in collectors if item.name == "mesh_link"), None)
        fping_samples = next(
            (
                item
                for item in artifacts
                if item.relative_name == "raw/fping_v5_samples.jsonl"
            ),
            None,
        )
        duration = float(detail.duration_minutes or operation.duration_minutes or 0)
        checks = {
            "duration": duration >= profile.minimum_valid_collection_minutes,
            "mesh_raw": bool(mesh and mesh.exists and mesh.size_bytes > 0),
            "fping_samples": bool(fping_samples and fping_samples.size_bytes > 0),
            "finalized": bool(detail.finalization_complete),
            "package": bool(detail.has_package and detail.package_reference),
            "integrity": str(detail.data_integrity) == "complete",
        }
        if all(checks.values()):
            return True, "", operation.session_id
        failed = "、".join(key for key, value in checks.items() if not value)
        return False, f"深度采集完成条件不足：{failed}", operation.session_id

    def _record_fping_started(self, run_id: str, row, operation) -> None:
        if not operation.session_id:
            return
        try:
            collectors = self.query_service.list_collectors(
                self.site_id, operation.session_id
            )
            preview = self.query_service.get_realtime_preview(
                self.site_id, operation.session_id
            )
        except OnlineMrQueryError:
            return
        fping = next((item for item in collectors if item.name == "fping_v5"), None)
        if fping is None or str(fping.status).lower() != "running":
            return
        self.repository.add_event(
            run_id=run_id,
            event_type="unattended_deep_fping_started",
            train_id=str(row.get("train_id") or ""),
            mr_id=str(row.get("mr_id") or ""),
            title="无人值守深采 fping 已进入运行态",
            details={
                "site_id": self.site_id,
                "run_id": run_id,
                "session_id": operation.session_id,
                "train_id": str(row.get("train_id") or ""),
                "mr_side": str(row.get("mr_position_code") or ""),
                "device_id": operation.device_id,
                "target_ip": str(preview.fping.get("target") or ""),
            },
        )

    def _update_train_coverage(self, run_id: str, profile) -> None:
        deep_rows = self.repository.list_deep_operations(run_id)
        by_train: dict[str, list[dict[str, Any]]] = {}
        for row in deep_rows:
            by_train.setdefault(row["train_id"], []).append(row)
        for train_id, rows in by_train.items():
            train = self.repository.get_train_run(run_id, train_id)
            if train is None:
                continue
            operations = train.get("operations") or {}
            current = [
                row for row in rows if row["operation_id"] in set(operations.values())
            ]
            expected_positions = {
                str(endpoint.get("endpoint") or "")
                for endpoint in train.get("endpoints", [])
                if endpoint.get("device_id") is not None
                and endpoint.get("management_ip")
                and endpoint.get("endpoint")
            }
            observed_positions = {
                str(row.get("mr_position_code") or "") for row in current
            }
            if expected_positions - observed_positions:
                continue
            if not current or any(
                row["state"] not in {"COMPLETED", "PARTIAL", "FAILED"}
                for row in current
            ):
                continue
            success = all(row["state"] == "COMPLETED" for row in current)
            duration = max(
                (
                    float(self._operation_duration(row["operation_id"]))
                    for row in current
                ),
                default=0.0,
            )
            sessions = {
                row["mr_position_code"]: row.get("session_id", "") for row in current
            }
            status = (
                "COVERED"
                if success and duration >= profile.minimum_valid_collection_minutes
                else "PARTIAL"
            )
            failure = "；".join(
                str(row.get("error_summary") or "")
                for row in current
                if row.get("error_summary")
            )
            self.repository.update_train_run(
                run_id,
                train_id,
                coverage_status=status,
                covered_rounds=int(train.get("covered_rounds") or 0)
                + (1 if status == "COVERED" else 0),
                valid_duration_minutes=duration,
                sessions_json=sessions,
                operations_json={},
                failure_reason=failure,
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="deep_collection_completed"
                if status == "COVERED"
                else "deep_collection_partial",
                severity="info" if status == "COVERED" else "warning",
                train_id=train_id,
                title="深度采集已完成"
                if status == "COVERED"
                else "深度采集得到部分结果",
                message=failure,
                details={"sessions": sessions, "duration_minutes": duration},
            )

    def _operation_duration(self, operation_id: str) -> float:
        try:
            return float(
                self.application_service.get_operation(
                    operation_id, site_id=self.site_id
                ).duration_minutes
                or 0
            )
        except OnlineMrApplicationError:
            return 0.0

    def _mark_operation_partial(self, row: dict[str, Any], reason: str) -> None:
        self.repository.save_deep_operation(
            {
                **row,
                "state": "PARTIAL",
                "ended_at": datetime.now()
                .astimezone()
                .isoformat(timespec="milliseconds"),
                "error_summary": reason,
                "finalization_complete": 0,
                "package_verified": 0,
                "updated_at": datetime.now()
                .astimezone()
                .isoformat(timespec="milliseconds"),
            }
        )

    def _ensure_queue(self, run_id: str, trains: list[dict[str, Any]]) -> list[str]:
        existing = self.repository.get_daily_queue(run_id)
        candidates = sorted(
            row["train_id"] for row in trains if row.get("deep_collection_eligible")
        )
        if existing:
            order = [str(value) for value in existing.get("queue_order", [])]
            missing = [value for value in candidates if value not in set(order)]
            if not missing:
                return order
            seed = int(existing["random_seed"])
            random.Random(f"{seed}:{','.join(missing)}").shuffle(missing)
            order.extend(missing)
            known = sorted(
                set(str(value) for value in existing.get("candidate_train_ids", []))
                | set(candidates)
            )
            self.repository.save_daily_queue(
                run_id=run_id,
                run_date=str(existing["run_date"]),
                random_seed=seed,
                candidate_train_ids=known,
                queue_order=order,
            )
            return order
        run = self.repository.get_run(run_id) or {}
        seed_bytes = hashlib.sha256(
            f"{self.site_id}:{run.get('run_date', '')}".encode("utf-8")
        ).digest()[:8]
        seed = int.from_bytes(seed_bytes, "big") & 0x7FFF_FFFF_FFFF_FFFF
        order = list(candidates)
        random.Random(seed).shuffle(order)
        self.repository.save_daily_queue(
            run_id=run_id,
            run_date=str(run.get("run_date") or ""),
            random_seed=seed,
            candidate_train_ids=candidates,
            queue_order=order,
        )
        return order

    def _build_start_request(
        self, endpoint: dict[str, Any], profile
    ) -> OnlineMrStartRequest:
        mr_id = str(endpoint.get("mr_id") or "")
        detail = self.base_query.get_mr(self.site_id, mr_id)
        if detail is None or detail.mr.device_id is None:
            raise ValueError("MR 基础资料不存在或未绑定设备")
        device = DeviceRepository(Database(self.paths.site_db_path(self.site_id))).get(
            detail.mr.device_id
        )
        if not is_device_eligible_for_automatic_collection(device):
            raise ValueError("MR 当前不参与本次调试，已退出无人值守自动任务")
        if device.ssh_enabled:
            protocol = "SSH"
            port = int(device.ssh_port or device.port or 22)
            username = str(device.ssh_username or device.username or "").strip()
            password = str(device.ssh_password or device.password or "")
        elif device.telnet_enabled:
            protocol = "Telnet"
            port = int(device.telnet_port or device.port or 23)
            username = str(device.telnet_username or device.username or "").strip()
            password = str(device.telnet_password or device.password or "")
        else:
            raise ValueError("MR 未配置可用 SSH/Telnet 连接")
        if not device.primary_address or not username or not password:
            raise ValueError("MR 缺少受控连接地址或凭据")
        fping_target = str(
            endpoint.get("management_ip")
            or detail.mr.management_ip
            or device.primary_address
            or ""
        ).strip()
        required_fping = self._required_fping_config(profile, fping_target)
        safe_name = re.sub(r'[\\/:*?"<>|]+', "_", detail.mr.name).strip(" ._") or "mr"
        config = OnlineMrConnectionConfig(
            site=self.site_id,
            mr_id=detail.mr.id,
            mr_name=detail.mr.name,
            safe_mr_name=f"{safe_name}__{detail.mr.device_id}",
            device_id=detail.mr.device_id,
            device_name=device.name,
            host=str(device.primary_address),
            protocol=protocol,
            port=port,
            username=username,
            password=password,
            intervals=OnlineMrIntervals(),
            tasks=OnlineMrTaskToggles(
                mesh_link=True,
                channel_busy=True,
                ap_radio_statistics=True,
                switch_history=True,
                interface_rate=True,
                wireless_status=False,
            ),
            radio=OnlineMrRadioConfig(),
            fping=required_fping,
            iperf=IperfTrafficConfig(
                enabled=False, server_ip="", preset_key="ground_unattended"
            ),
            duration_minutes=profile.maximum_collection_minutes,
            fping_required_before_collection=True,
        )
        return OnlineMrStartRequest(
            site_id=self.site_id,
            device_id=detail.mr.device_id,
            device_name=device.name,
            mr_name=detail.mr.name,
            config=config,
            executor_kind=OnlineMrExecutorKind.LOCAL,
            owner="ground_unattended",
        )

    @staticmethod
    def _required_fping_config(profile, target: str) -> FpingConfig:
        normalized_target = str(target or "").strip()
        try:
            ipaddress.ip_address(normalized_target)
        except ValueError:
            raise ValueError(
                "MR 管理 IP 无效，无法启动深度采集必需的 fping"
            ) from None
        deep_fping = profile.deep_fping
        return FpingConfig(
            enabled=True,
            target=normalized_target,
            preset_key=deep_fping.preset_key,
            preset_name=deep_fping.preset_name,
            packet_size=deep_fping.packet_size,
            interval_ms=deep_fping.interval_ms,
            loss_threshold_ms=deep_fping.timeout_ms,
            loss_warn_percent=deep_fping.loss_warn_percent,
            latency_warn_ms=deep_fping.latency_warn_ms,
        ).normalized()

    def _active_operations(self):
        return self.application_service.list_operations(
            site_id=self.site_id,
            states={OnlineMrMappingState.PENDING_SESSION, OnlineMrMappingState.LINKED},
            limit=1000,
        )


__all__ = ["DeepMrCollectionScheduler", "SchedulerCandidate"]
