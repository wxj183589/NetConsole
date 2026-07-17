from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_agent import (
    ONLINE_MR_AGENT_PACKAGE_REQUIRED_DIRECTORIES,
    OnlineMrAgentStatus,
    map_online_mr_agent_status,
    validate_online_mr_agent_package_entries,
)
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrTaskSessionMapping,
    calculate_duration_minutes,
)
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.online_mr.errors import OnlineMrApplicationErrorCode


_MAX_FILES = 50_000
_MAX_UNCOMPRESSED_SIZE = 64 * 1024 * 1024 * 1024
_MAX_JSON_SIZE = 16 * 1024 * 1024
_SENSITIVE_KEYS = {"credential", "password", "private_key", "secret", "token"}
_PUBLIC_JSON_FILES = {
    "agent_info.json",
    "manifest.json",
    "session_meta.json",
    "stop_reason.json",
    "system_info.json",
    "task.json",
    "target_snapshot.json",
}
_ACTIVE_AGENT_STATES = {
    OnlineMrAgentStatus.CREATED,
    OnlineMrAgentStatus.STARTING,
    OnlineMrAgentStatus.RUNNING,
    OnlineMrAgentStatus.STOPPING,
}


@dataclass(frozen=True)
class OnlineMrAgentPackageInspectResult:
    success: bool
    status: str
    session_id: str = ""
    agent_task_id: str = ""
    agent_id: str = ""
    package_status: str = ""
    data_integrity: str = "invalid"
    source_zip_sha256: str = ""
    root_prefix: str = ""
    files_count: int = 0
    total_size: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class OnlineMrAgentPackageImportResult:
    success: bool
    status: str
    session_id: str = ""
    agent_task_id: str = ""
    task_id: str = ""
    session_dir: Path | None = None
    package_status: str = ""
    data_integrity: str = "invalid"
    mapping_status: str = ""
    imported: bool = False
    already_imported: bool = False
    conflict: bool = False
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class _InspectedPackage:
    result: OnlineMrAgentPackageInspectResult
    members: dict[str, str]
    documents: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _IdentityResolution:
    match_method: str
    source: dict[str, str]
    resolved: dict[str, str]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class OnlineMrAgentPackageImporter:
    """校验并原子导入已下载的 Agent ZIP；调用者须在后台任务中执行。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def inspect_package(
        self,
        zip_path: str | Path,
        *,
        import_mode: str = "strict",
    ) -> OnlineMrAgentPackageInspectResult:
        return self._inspect_package(Path(zip_path), import_mode=import_mode).result

    def validate_package(
        self,
        zip_path: str | Path,
        *,
        import_mode: str = "strict",
    ) -> OnlineMrAgentPackageInspectResult:
        return self.inspect_package(zip_path, import_mode=import_mode)

    def compute_target_session_dir(
        self,
        *,
        site_id: str,
        device_id: int | str,
        device_name: str,
        session_id: str,
    ) -> Path:
        site = self._safe_component(site_id, "site_id")
        session = self._safe_component(session_id, "session_id")
        if not self.paths.site_dir(site).is_dir():
            raise ValueError("Online MR 局点不存在")
        safe_device = self._safe_device_folder_name(device_name, device_id)
        target = self.paths.online_mr_session_dir(site, safe_device, session).resolve()
        root = self.paths.online_mr_sessions_root(site, safe_device).resolve()
        self._require_within(root, self.paths.site_dir(site).resolve())
        self._require_within(target, root)
        return target

    def import_package(
        self,
        zip_path: str | Path,
        *,
        site_id: str,
        site_name: str = "",
        device_id: int | str,
        device_name: str,
        mr_id: str = "",
        mr_name: str,
        owner: str = "agent_import",
        controller_task_id: str | None = None,
        agent_task_id: str | None = None,
        expected_session_id: str | None = None,
        import_mode: str = "strict",
        identity_match_policy: str = "strict",
        expected_host: str = "",
        allow_identity_override: bool = False,
        agent_id: str = "",
        source_package_id: str = "",
    ) -> OnlineMrAgentPackageImportResult:
        source = Path(zip_path)
        inspected = self._inspect_package(source, import_mode=import_mode)
        if not inspected.result.success:
            return self._import_result(inspected.result)

        try:
            site = self._safe_component(site_id, "site_id")
            if not self.paths.site_dir(site).is_dir():
                raise ValueError("Online MR 局点不存在")
            session_id = self._safe_component(inspected.result.session_id, "session_id")
            expected = (
                self._safe_component(expected_session_id, "expected_session_id")
                if expected_session_id
                else ""
            )
            if expected and expected != session_id:
                raise ValueError("Agent package session_id 与预期不一致")
            package_task_id = inspected.result.agent_task_id
            selected_agent_task_id = (
                self._safe_component(agent_task_id, "agent_task_id")
                if agent_task_id
                else package_task_id
            )
            if package_task_id and selected_agent_task_id != package_task_id:
                raise ValueError("Agent package task_id 与预期不一致")
            selected_agent_id = str(agent_id or inspected.result.agent_id or "").strip()
            if (
                agent_id
                and inspected.result.agent_id
                and agent_id != inspected.result.agent_id
            ):
                raise ValueError("Agent package agent_id 与预期不一致")
            selected_task_id = (
                self._safe_component(controller_task_id, "controller_task_id")
                if controller_task_id
                else self._controller_task_id(
                    site, selected_agent_id, selected_agent_task_id, session_id
                )
            )
            target = self.compute_target_session_dir(
                site_id=site,
                device_id=device_id,
                device_name=device_name,
                session_id=session_id,
            )
        except ValueError as exc:
            return self._import_result(inspected.result, errors=(str(exc),))

        identity = self._resolve_identity(
            inspected.documents,
            site_id=site,
            site_name=site_name,
            device_id=device_id,
            device_name=device_name,
            mr_id=mr_id,
            mr_name=mr_name,
            identity_match_policy=identity_match_policy,
            expected_host=expected_host,
            allow_identity_override=allow_identity_override,
        )
        if identity.errors:
            return self._import_result(
                inspected.result, errors=identity.errors, warnings=identity.warnings
            )

        existing = self._existing_session(site, session_id)
        if existing is not None:
            if existing == target:
                return self._existing_result(
                    target,
                    inspected.result,
                    selected_task_id,
                    site,
                    warnings=identity.warnings,
                )
            return self._import_result(
                inspected.result,
                status="conflict",
                conflict=True,
                warnings=identity.warnings,
                errors=("同一局点已有相同 session_id 的其他会话目录",),
                session_dir=existing,
            )

        task_repository = TaskRepository(self.paths.site_tasks_db_path(site))
        mapping_repository = OnlineMrTaskSessionRepository(
            self.paths.site_tasks_db_path(site), site_id=site
        )
        existing_task = task_repository.get(selected_task_id)
        existing_mapping = mapping_repository.get_by_task(selected_task_id)
        session_mapping = mapping_repository.get_by_session(session_id)
        updating_existing = existing_task is not None or existing_mapping is not None
        update_allowed = (
            bool(controller_task_id)
            and existing_task is not None
            and existing_task.source == "agent"
            and existing_task.agent in {"", selected_agent_id}
            and existing_mapping is not None
            and existing_mapping.executor_kind is OnlineMrExecutorKind.AGENT
            and existing_mapping.session_id in {None, session_id}
            and (
                session_mapping is None
                or session_mapping.controller_task_id == selected_task_id
            )
            and existing_mapping.device_id in {"", str(device_id)}
            and (not mr_id or existing_mapping.mr_id in {"", str(mr_id)})
            and existing_mapping.agent_id in {"", selected_agent_id}
        )
        if (updating_existing and not update_allowed) or (
            not updating_existing and session_mapping is not None
        ):
            return self._import_result(
                inspected.result,
                status="conflict",
                conflict=True,
                warnings=identity.warnings,
                errors=("目标 Task 或 Session 映射已存在",),
            )

        import_id = uuid.uuid4().hex
        staging_root = (
            self.paths.site_imports_dir(site) / "online_mr" / f".{import_id}.tmp"
        ).resolve()
        staging_session = staging_root / "session"
        imports_root = (self.paths.site_imports_dir(site) / "online_mr").resolve()
        self._require_within(imports_root, self.paths.site_dir(site).resolve())
        self._require_within(staging_root, imports_root)
        warnings = tuple(
            dict.fromkeys((*inspected.result.warnings, *identity.warnings))
        )
        target_committed = False
        mapping_created = False
        mapping_updated = False
        try:
            staging_session.mkdir(parents=True, exist_ok=False)
            staged_package = staging_root / "source.zip"
            shutil.copy2(source, staged_package)
            if self._sha256(staged_package) != inspected.result.source_zip_sha256:
                raise ValueError("Agent package 在导入期间发生变化")
            self._extract(staged_package, inspected.members, staging_session)
            for directory in ONLINE_MR_AGENT_PACKAGE_REQUIRED_DIRECTORIES:
                (staging_session / directory).mkdir(parents=True, exist_ok=True)

            package_relative = f"outputs/{session_id}.zip"
            task_package_path = (
                (target / package_relative)
                .relative_to(self.paths.site_dir(site).resolve())
                .as_posix()
            )
            shutil.move(staged_package, staging_session / package_relative)
            now = utc_now_iso()
            documents = inspected.documents
            session_meta = dict(documents["session_meta.json"])
            source_identity = {
                **identity.source,
                "agent_task_id": selected_agent_task_id,
                "session_id": session_id,
            }
            resolved_identity = dict(identity.resolved)
            package_status = OnlineMrAgentStatus(inspected.result.package_status)
            data_integrity = inspected.result.data_integrity
            task_state, session_status, force_stopped = self._terminal_states(
                package_status
            )
            started_at = self._text(session_meta.get("started_at")) or self._text(
                documents["task.json"].get("start_time")
            )
            ended_at = (
                self._text(session_meta.get("ended_at"))
                or self._text(documents["task.json"].get("end_time"))
                or now
            )
            duration = self._duration_minutes(session_meta, started_at, ended_at)
            stop_reason = self._stop_reason(
                package_status, session_meta, documents["stop_reason.json"]
            )
            error_summary = self._error_summary(
                package_status,
                data_integrity,
                session_meta,
                documents["task.json"],
                warnings,
            )

            session_meta.update(
                {
                    "session_id": session_id,
                    "site": site,
                    "site_name": site_name or site,
                    "device_id": device_id,
                    "device_name": device_name,
                    "mr_id": mr_id or self._text(session_meta.get("mr_id")),
                    "mr_name": mr_name,
                    "status": session_status,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "duration_minutes": duration,
                    "stop_reason": stop_reason,
                    "force_stopped": force_stopped,
                    "finalization_complete": True,
                    "package_available": True,
                    "data_integrity": data_integrity,
                    "executor_kind": OnlineMrExecutorKind.AGENT.value,
                    "agent_id": selected_agent_id,
                    "agent_task_id": selected_agent_task_id,
                    "controller_task_id": selected_task_id,
                    "owner": owner,
                    "raw_log_path": "raw/collector_output_raw.log",
                    "finalization_warnings": list(warnings),
                    "import_context": {
                        "executor": OnlineMrExecutorKind.AGENT.value,
                        "match_method": identity.match_method,
                        "source": source_identity,
                        "resolved": resolved_identity,
                        "warnings": list(identity.warnings),
                    },
                }
            )
            self._write_json_atomic(staging_session / "session_meta.json", session_meta)
            import_manifest = {
                "import_id": import_id,
                "imported_at": now,
                "source_zip": source.name,
                "source_zip_sha256": inspected.result.source_zip_sha256,
                "source_package_id": str(source_package_id or ""),
                "package_relative_path": package_relative,
                "site_id": site,
                "site_name": site_name or site,
                "device_id": str(device_id),
                "device_name": device_name,
                "mr_id": str(mr_id or session_meta.get("mr_id") or ""),
                "mr_name": mr_name,
                "identity": {
                    "match_method": identity.match_method,
                    "source": source_identity,
                    "resolved": resolved_identity,
                    "warnings": list(identity.warnings),
                },
                "agent_id": selected_agent_id,
                "agent_task_id": selected_agent_task_id,
                "controller_task_id": selected_task_id,
                "session_id": session_id,
                "status": package_status.value,
                "data_integrity": data_integrity,
                "warnings": list(warnings),
                "files_count": inspected.result.files_count,
                "total_size": inspected.result.total_size,
            }
            self._write_json_atomic(
                staging_session / "import_manifest.json", import_manifest
            )

            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                self._cleanup_staging(staging_root, imports_root)
                return self._import_result(
                    inspected.result,
                    status="conflict",
                    conflict=True,
                    warnings=warnings,
                    errors=("目标会话目录在导入期间已被创建",),
                    session_dir=target,
                )
            os.replace(staging_session, target)
            target_committed = True
            self._cleanup_staging(staging_root, imports_root)

            mapping_values = {
                "session_id": session_id,
                "site_id": site,
                "device_id": str(device_id),
                "device_name": device_name,
                "mr_id": str(mr_id or session_meta.get("mr_id") or ""),
                "mr_name": mr_name,
                "executor_kind": OnlineMrExecutorKind.AGENT,
                "agent_id": selected_agent_id,
                "phase": OnlineMrPhase.TERMINAL,
                "mapping_state": OnlineMrMappingState.TERMINAL,
                "updated_at": now,
                "terminal_at": now,
                "started_at": started_at or None,
                "ended_at": ended_at,
                "duration_minutes": duration,
                "stop_reason": stop_reason,
                "force_stopped": force_stopped,
                "error_summary": error_summary,
                "error_code": (
                    OnlineMrApplicationErrorCode.AGENT_STATUS_FAILED.value
                    if task_state is TaskState.FAILED
                    else ""
                ),
                "error_message": error_summary,
            }
            if existing_mapping is None:
                mapping_record = OnlineMrTaskSessionMapping(
                    controller_task_id=selected_task_id,
                    created_at=now,
                    **mapping_values,
                )
                mapping_repository.create(mapping_record)
                mapping_created = True
            else:
                mapping_record = mapping_repository.save(
                    replace(existing_mapping, **mapping_values)
                )
                mapping_updated = True
            result_payload = {
                "session_id": session_id,
                "status": session_status,
                "stop_reason": stop_reason,
                "duration_minutes": duration,
                "executor_kind": OnlineMrExecutorKind.AGENT.value,
                "agent_task_id": selected_agent_task_id,
                "package_path": task_package_path,
                "data_integrity": data_integrity,
            }
            snapshot = TaskSnapshot(
                task_id=selected_task_id,
                task_type="online_mr_collection_start",
                task_name=f"Online MR - {device_name}",
                status=task_state,
                created_time=(
                    existing_task.created_time
                    if existing_task is not None
                    else self._text(documents["task.json"].get("created_at")) or now
                ),
                started_time=started_at,
                finished_time=ended_at,
                updated_time=now,
                progress=100,
                stage=OnlineMrPhase.TERMINAL.value,
                message="Agent Online MR 采集包已导入"
                if task_state is not TaskState.FAILED
                else "Agent Online MR 采集失败包已导入",
                owner=(
                    existing_task.owner
                    if existing_task is not None and existing_task.owner
                    else owner
                ),
                device=device_name,
                agent=selected_agent_id,
                result_path=task_package_path,
                error_message=error_summary if task_state is TaskState.FAILED else "",
                result=result_payload,
                source="agent",
                site_name=site,
            )
            event_type = {
                TaskState.COMPLETED: "finished",
                TaskState.FAILED: "error",
            }.get(task_state, "cancelled")
            event_payload: dict[str, Any] = {"result": result_payload}
            if error_summary:
                event_payload["error"] = error_summary
            if not task_repository.record(
                snapshot,
                TaskEvent(
                    event_id=f"agent-import-{selected_task_id}-{import_id}",
                    task_id=selected_task_id,
                    type=event_type,
                    time=now,
                    source="agent_import",
                    payload=event_payload,
                ),
                allowed_from={
                    TaskState.PENDING,
                    TaskState.STARTING,
                    TaskState.RUNNING,
                    TaskState.STOPPING,
                }
                if existing_task is not None
                else (),
            ):
                raise RuntimeError("任务状态已变化，拒绝覆盖现有终态")
        except Exception as exc:
            rollback_errors: list[str] = []
            try:
                if mapping_created:
                    mapping_repository.delete(selected_task_id)
                elif mapping_updated and existing_mapping is not None:
                    mapping_repository.save(existing_mapping)
            except Exception as rollback_exc:
                rollback_errors.append(
                    f"Mapping 回滚失败：{self._safe_error(rollback_exc)}"
                )
            try:
                if target_committed and not rollback_errors:
                    self._cleanup_import_failure(target, staging_root, imports_root)
                else:
                    self._cleanup_staging(staging_root, imports_root)
            except Exception as rollback_exc:
                rollback_errors.append(
                    f"文件回滚失败：{self._safe_error(rollback_exc)}"
                )
            return self._import_result(
                inspected.result,
                errors=(self._safe_error(exc), *rollback_errors),
                warnings=warnings,
            )

        return OnlineMrAgentPackageImportResult(
            success=True,
            status="imported",
            session_id=session_id,
            agent_task_id=selected_agent_task_id,
            task_id=selected_task_id,
            session_dir=target,
            package_status=inspected.result.package_status,
            data_integrity=inspected.result.data_integrity,
            mapping_status=OnlineMrMappingState.TERMINAL.value,
            imported=True,
            warnings=warnings,
        )

    def _inspect_package(self, source: Path, *, import_mode: str) -> _InspectedPackage:
        mode = str(import_mode or "strict").strip().lower()
        if mode not in {"strict", "partial"}:
            return self._failed_inspection(
                source, "import_mode 只支持 strict 或 partial"
            )
        if not source.is_file():
            return self._failed_inspection(source, "Agent package ZIP 不存在")
        try:
            source_hash = self._sha256(source)
        except OSError as exc:
            return self._failed_inspection(source, f"Agent package ZIP 无法读取：{exc}")
        errors: list[str] = []
        warnings: list[str] = []
        members: dict[str, str] = {}
        documents: dict[str, dict[str, Any]] = {}
        oversized_json: set[str] = set()
        root_prefix = ""
        total_size = 0
        session_id = ""
        agent_task_id = ""
        agent_id = ""
        package_status: OnlineMrAgentStatus | None = None
        data_integrity = "invalid"
        try:
            with zipfile.ZipFile(source) as archive:
                file_infos: list[tuple[zipfile.ZipInfo, str]] = []
                for info in archive.infolist():
                    normalized, issue = self._normalize_member(info.filename)
                    if issue:
                        errors.append(issue)
                        continue
                    if self._is_symlink(info):
                        errors.append(f"包内禁止符号链接：{info.filename}")
                        continue
                    if info.flag_bits & 0x1:
                        errors.append(f"包内禁止加密文件：{info.filename}")
                        continue
                    if info.is_dir():
                        continue
                    file_infos.append((info, normalized))
                    total_size += int(info.file_size)
                if len(file_infos) > _MAX_FILES:
                    errors.append(f"包内文件数超过上限：{len(file_infos)}")
                if total_size > _MAX_UNCOMPRESSED_SIZE:
                    errors.append(f"包解压后大小超过上限：{total_size}")

                root_prefix = self._root_prefix([name for _, name in file_infos])
                member_keys: set[str] = set()
                for info, normalized in file_infos:
                    relative = (
                        normalized[len(root_prefix) + 1 :]
                        if root_prefix
                        else normalized
                    )
                    key = relative.casefold()
                    if key in member_keys:
                        errors.append(f"包内存在重复路径：{relative}")
                        continue
                    member_keys.add(key)
                    members[relative] = info.filename
                    lowered = relative.casefold()
                    if lowered.endswith(".json") and info.file_size > _MAX_JSON_SIZE:
                        errors.append(f"包内 JSON 文件超过大小上限：{relative}")
                        oversized_json.add(relative)
                    if PurePosixPath(relative).name.casefold() == "stop.request":
                        errors.append(f"包内禁止文件：{relative}")
                    if lowered.endswith(
                        "meta/request.private.json"
                    ) or lowered.endswith(".tmp"):
                        errors.append(f"包内禁止文件：{relative}")

                errors.extend(validate_online_mr_agent_package_entries(members))
                for name in sorted(_PUBLIC_JSON_FILES):
                    source_name = members.get(name)
                    if source_name is None or name in oversized_json:
                        continue
                    try:
                        value = json.loads(
                            archive.read(source_name).decode("utf-8-sig")
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
                        errors.append(f"{name} 不是有效 UTF-8 JSON：{exc}")
                        continue
                    if not isinstance(value, dict):
                        errors.append(f"{name} 根对象必须是 JSON object")
                        continue
                    documents[name] = dict(value)
                    secret = self._find_secret(value)
                    if secret:
                        errors.append(f"{name} 包含非空敏感字段：{secret}")

                for relative, source_name in members.items():
                    if (
                        relative in _PUBLIC_JSON_FILES
                        or relative in oversized_json
                        or not relative.casefold().endswith(".json")
                    ):
                        continue
                    try:
                        raw_value = archive.read(source_name)
                        if not raw_value.strip():
                            continue
                        value = json.loads(raw_value.decode("utf-8-sig"))
                    except (UnicodeDecodeError, json.JSONDecodeError, KeyError):
                        continue
                    secret = self._find_secret(value)
                    if secret:
                        errors.append(f"{relative} 包含非空敏感字段：{secret}")

                session_meta = documents.get("session_meta.json", {})
                private_path = self._find_absolute_path(session_meta)
                if private_path:
                    errors.append(
                        f"session_meta.json 包含 Agent 私有绝对路径：{private_path}"
                    )
                session_id = self._text(session_meta.get("session_id"))
                try:
                    self._safe_component(session_id, "session_id")
                except ValueError as exc:
                    errors.append(str(exc))
                manifest = documents.get("manifest.json", {})
                task = documents.get("task.json", {})
                if (
                    self._text(manifest.get("package_type"))
                    != "netconsole_agent_collect_package"
                ):
                    errors.append("Agent package manifest 类型不符")
                task_type = self._text(
                    task.get("task_type") or manifest.get("task_type")
                )
                if task_type != "mr_realtime_collect":
                    errors.append(
                        f"Agent package task_type 不符：{task_type or '<empty>'}"
                    )
                statuses = {
                    self._text(value).lower()
                    for value in (
                        session_meta.get("status"),
                        task.get("status"),
                        manifest.get("status"),
                    )
                    if self._text(value)
                }
                if len(statuses) > 1:
                    errors.append("Agent package 各元数据 status 不一致")
                status_text = next(iter(statuses), "")
                try:
                    package_status = OnlineMrAgentStatus(status_text)
                except ValueError:
                    package_status = None
                    errors.append(
                        f"Agent package status 不支持：{status_text or '<empty>'}"
                    )
                if package_status in _ACTIVE_AGENT_STATES:
                    if mode == "strict":
                        errors.append(
                            f"strict 模式拒绝非终态 Agent package：{package_status.value}"
                        )
                    else:
                        warnings.append(
                            f"非终态 Agent package 按 partial 导入：{package_status.value}"
                        )
                if package_status in {
                    OnlineMrAgentStatus.STOPPED_WITH_WARNINGS,
                    OnlineMrAgentStatus.COMPLETED_WITH_WARNINGS,
                }:
                    warnings.append("Agent package 终态包含采集警告")

                declared_integrity = self._text(
                    session_meta.get("data_integrity")
                ).lower()
                if declared_integrity and declared_integrity not in {
                    "complete",
                    "partial",
                }:
                    errors.append(
                        f"Agent package data_integrity 不支持：{declared_integrity}"
                    )
                data_integrity = self._data_integrity(
                    package_status, session_meta, mode
                )
                if data_integrity == "partial":
                    warnings.append("Agent package 数据完整性为 partial")
                agent_info = documents.get("agent_info.json", {})
                task_ids = {
                    self._text(value)
                    for value in (task.get("task_id"), manifest.get("task_id"))
                    if self._text(value)
                }
                if len(task_ids) > 1:
                    errors.append("Agent package task_id 不一致")
                agent_task_id = next(iter(task_ids), "")
                agent_ids = {
                    self._text(value)
                    for value in (agent_info.get("agent_id"), manifest.get("agent_id"))
                    if self._text(value)
                }
                if len(agent_ids) > 1:
                    errors.append("Agent package agent_id 不一致")
                agent_id = next(iter(agent_ids), "")
                if not agent_task_id:
                    errors.append("Agent package 缺少 agent_task_id")
                if not agent_id:
                    errors.append("Agent package 缺少 agent_id")
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            return self._failed_inspection(
                source, f"Agent package ZIP 无法读取：{exc}", source_hash=source_hash
            )

        errors = list(dict.fromkeys(errors))
        warnings = list(dict.fromkeys(warnings))
        result = OnlineMrAgentPackageInspectResult(
            success=not errors,
            status="valid" if not errors else "invalid",
            session_id=session_id,
            agent_task_id=agent_task_id,
            agent_id=agent_id,
            package_status=package_status.value if package_status else "",
            data_integrity=data_integrity,
            source_zip_sha256=source_hash,
            root_prefix=root_prefix,
            files_count=len(members),
            total_size=total_size,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )
        return _InspectedPackage(result=result, members=members, documents=documents)

    def _existing_result(
        self,
        target: Path,
        inspected: OnlineMrAgentPackageInspectResult,
        task_id: str,
        site_id: str,
        *,
        warnings: tuple[str, ...],
    ) -> OnlineMrAgentPackageImportResult:
        manifest = self._read_json_file(target / "import_manifest.json")
        if manifest.get("source_zip_sha256") != inspected.source_zip_sha256:
            return self._import_result(
                inspected,
                status="conflict",
                conflict=True,
                session_dir=target,
                warnings=warnings,
                errors=("目标 session_id 已存在且采集包内容不同",),
            )
        existing_task_id = self._text(manifest.get("controller_task_id")) or task_id
        task = TaskRepository(self.paths.site_tasks_db_path(site_id)).get(
            existing_task_id
        )
        mapping = OnlineMrTaskSessionRepository(
            self.paths.site_tasks_db_path(site_id),
            site_id=site_id,
        ).get_by_session(inspected.session_id)
        package_relative = self._text(manifest.get("package_relative_path"))
        package = (target / package_relative).resolve()
        try:
            self._require_within(package, target)
            package_intact = (
                package_relative.endswith(".zip")
                and package.is_file()
                and self._sha256(package) == inspected.source_zip_sha256
            )
        except (OSError, ValueError):
            package_intact = False
        if (
            task is None
            or mapping is None
            or mapping.controller_task_id != existing_task_id
            or task.source != "agent"
            or task.status
            not in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
            or mapping.executor_kind is not OnlineMrExecutorKind.AGENT
            or mapping.mapping_state is not OnlineMrMappingState.TERMINAL
            or mapping.phase is not OnlineMrPhase.TERMINAL
            or mapping.session_id != inspected.session_id
            or not package_intact
        ):
            return self._import_result(
                inspected,
                status="conflict",
                conflict=True,
                session_dir=target,
                warnings=warnings,
                errors=("已有导入会话的 Task/Mapping 登记不完整",),
            )
        return OnlineMrAgentPackageImportResult(
            success=True,
            status="already_imported",
            session_id=inspected.session_id,
            agent_task_id=inspected.agent_task_id,
            task_id=existing_task_id,
            session_dir=target,
            package_status=inspected.package_status,
            data_integrity=inspected.data_integrity,
            mapping_status=mapping.mapping_state.value,
            already_imported=True,
            warnings=warnings,
        )

    @staticmethod
    def _terminal_states(status: OnlineMrAgentStatus) -> tuple[TaskState, str, bool]:
        if status in _ACTIVE_AGENT_STATES:
            return TaskState.CANCELLED, "ABORTED", False
        mapping = map_online_mr_agent_status(status, package_imported=True)
        if status is OnlineMrAgentStatus.FORCE_STOPPED:
            return mapping.task_state, "FORCED_STOPPED", True
        if status in {OnlineMrAgentStatus.ABORTED, OnlineMrAgentStatus.CANCELLED}:
            return mapping.task_state, "ABORTED", False
        if status is OnlineMrAgentStatus.FAILED:
            return mapping.task_state, "FAILED", False
        return mapping.task_state, "STOPPED", False

    @staticmethod
    def _data_integrity(
        status: OnlineMrAgentStatus | None,
        session_meta: dict[str, Any],
        import_mode: str,
    ) -> str:
        selected = str(session_meta.get("data_integrity") or "").strip().lower()
        if selected in {"complete", "partial"}:
            return selected
        if selected:
            return "invalid"
        if (
            status
            in {
                OnlineMrAgentStatus.FORCE_STOPPED,
                OnlineMrAgentStatus.FAILED,
                OnlineMrAgentStatus.ABORTED,
                OnlineMrAgentStatus.CANCELLED,
            }
            or status in _ACTIVE_AGENT_STATES
            or import_mode == "partial"
        ):
            return "partial"
        return "complete"

    @staticmethod
    def _stop_reason(
        status: OnlineMrAgentStatus,
        session_meta: dict[str, Any],
        stop_reason: dict[str, Any],
    ) -> str:
        value = str(
            session_meta.get("stop_reason") or stop_reason.get("reason") or ""
        ).strip()
        if (
            status is OnlineMrAgentStatus.FORCE_STOPPED
            and "force" not in value.casefold()
        ):
            return "force_stop"
        return value or (
            "runner_error" if status is OnlineMrAgentStatus.FAILED else status.value
        )

    @classmethod
    def _error_summary(
        cls,
        status: OnlineMrAgentStatus,
        data_integrity: str,
        session_meta: dict[str, Any],
        task: dict[str, Any],
        warnings: tuple[str, ...],
    ) -> str:
        values = [
            session_meta.get("error_summary"),
            session_meta.get("error_message"),
            task.get("error_message"),
        ]
        if status is OnlineMrAgentStatus.FORCE_STOPPED and not any(values):
            values.append("Agent 强停采集包按部分完整导入")
        if data_integrity == "partial" and not any(values):
            values.append("Agent 采集包数据完整性为 partial")
        if not any(values):
            values.extend(warnings)
        return cls._safe_error(
            "；".join(str(value) for value in values if str(value or "").strip())
        )

    @staticmethod
    def _duration_minutes(
        meta: dict[str, Any], started_at: str, ended_at: str
    ) -> float:
        try:
            value = float(meta.get("duration_minutes"))
            if value >= 0:
                return round(value, 3)
        except (TypeError, ValueError):
            pass
        return calculate_duration_minutes(started_at, ended_at)

    @classmethod
    def _resolve_identity(
        cls,
        documents: dict[str, dict[str, Any]],
        *,
        site_id: str,
        site_name: str,
        device_id: int | str,
        device_name: str,
        mr_id: str,
        mr_name: str,
        identity_match_policy: str,
        expected_host: str,
        allow_identity_override: bool,
    ) -> _IdentityResolution:
        policy = str(identity_match_policy or "strict").strip().lower()
        meta = documents.get("session_meta.json", {})
        source = {
            "site_id": cls._text(meta.get("site") or meta.get("site_id")),
            "device_id": cls._text(meta.get("device_id")),
            "device_name": cls._text(meta.get("device_name")),
            "mr_id": cls._text(meta.get("mr_id")),
            "mr_name": cls._text(meta.get("mr_name")),
            "host": cls._extract_source_host(documents),
        }
        resolved = {
            "site_id": str(site_id),
            "site_name": str(site_name or site_id),
            "device_id": str(device_id),
            "device_name": str(device_name),
            "mr_id": str(mr_id or ""),
            "mr_name": str(mr_name),
            "host": str(expected_host or "").strip(),
        }
        errors: list[str] = []
        warnings: list[str] = []
        if policy not in {"strict", "ip_match", "manual_override"}:
            errors.append(
                "identity_match_policy 只支持 strict、ip_match 或 manual_override"
            )
        package_site = source["site_id"]
        if package_site and package_site not in {site_id, site_name or site_id}:
            errors.append("Agent package 局点与目标局点不一致")
        comparisons = (
            ("device_id", source["device_id"], resolved["device_id"]),
            ("device_name", source["device_name"], resolved["device_name"]),
            ("mr_name", source["mr_name"], resolved["mr_name"]),
        )
        if resolved["mr_id"]:
            comparisons = (
                *comparisons,
                ("mr_id", source["mr_id"], resolved["mr_id"]),
            )
        mismatches = [
            (name, package_value, resolved_value)
            for name, package_value, resolved_value in comparisons
            if package_value != resolved_value
        ]
        match_method = "strict"
        if not errors and mismatches:
            if policy == "strict":
                errors.extend(
                    f"Agent package {name} 与导入目标不一致"
                    for name, _package_value, _resolved_value in mismatches
                )
            elif policy == "ip_match":
                source_host = cls._normalized_host(source["host"])
                target_host = cls._normalized_host(expected_host)
                if not source_host:
                    errors.append("Agent package 未提供采集目标 IP，无法按 IP 匹配")
                elif not target_host:
                    errors.append("未提供 expected_host，无法按 IP 匹配")
                elif source_host != target_host:
                    errors.append("Agent package 采集目标 IP 与 expected_host 不一致")
                else:
                    match_method = "ip_match"
                    warnings.append(
                        "Agent 包内设备身份与本地设备身份不一致，已按 IP 匹配导入"
                    )
            elif not allow_identity_override:
                errors.append("manual_override 必须显式设置 allow_identity_override")
            else:
                match_method = "manual_override"
                warnings.append(
                    "Agent 包内设备身份与本地设备身份不一致，已按手工指定目标导入"
                )
                if not source["host"]:
                    warnings.append("Agent 包未提供采集目标 IP，已按手工覆盖导入")
        return _IdentityResolution(
            match_method=match_method,
            source=source,
            resolved=resolved,
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(dict.fromkeys(errors)),
        )

    @classmethod
    def _extract_source_host(cls, documents: dict[str, dict[str, Any]]) -> str:
        meta = documents.get("session_meta.json", {})
        task = documents.get("task.json", {})
        target = documents.get("target_snapshot.json", {})
        candidates = (
            cls._text(meta.get("host")),
            cls._nested_text(meta, "target", "host"),
            cls._text(meta.get("device_host")),
            cls._text(meta.get("target_host")),
            cls._text(target.get("host")),
            cls._nested_text(task, "target", "host"),
            cls._text(task.get("host")),
            cls._nested_text(task, "request", "target", "host"),
            cls._nested_text(task, "params", "target", "host"),
        )
        return next((value for value in candidates if value), "")

    @classmethod
    def _nested_text(cls, value: object, *keys: str) -> str:
        current = value
        for key in keys:
            if not isinstance(current, dict):
                return ""
            current = current.get(key)
        return cls._text(current)

    @staticmethod
    def _normalized_host(value: object) -> str:
        return str(value or "").strip().rstrip(".").casefold()

    def _existing_session(self, site_id: str, session_id: str) -> Path | None:
        root = self.paths.online_mr_root(site_id)
        matches = [
            path.resolve()
            for path in root.glob(f"*/sessions/{session_id}")
            if path.is_dir()
        ]
        return matches[0] if matches else None

    @staticmethod
    def _controller_task_id(
        site_id: str, agent_id: str, agent_task_id: str, session_id: str
    ) -> str:
        value = uuid.uuid5(
            uuid.NAMESPACE_URL, f"{site_id}:{agent_id}:{agent_task_id}:{session_id}"
        ).hex
        return f"online_mr_agent_import_{value}"

    @staticmethod
    def _safe_device_folder_name(device_name: str, device_id: int | str) -> str:
        name = (
            re.sub(r'[\\/:*?"<>|]+', "_", str(device_name or "device")).strip(" ._")
            or "device"
        )
        identifier = OnlineMrAgentPackageImporter._safe_component(
            device_id, "device_id"
        )
        return f"{name}__{identifier}"

    @staticmethod
    def _safe_component(value: object, label: str) -> str:
        text = str(value or "").strip()
        if (
            not text
            or text in {".", ".."}
            or Path(text).name != text
            or "/" in text
            or "\\" in text
            or ":" in text
            or any(ord(char) < 32 for char in text)
        ):
            raise ValueError(f"{label} 不是安全的路径标识")
        return text

    @staticmethod
    def _normalize_member(value: str) -> tuple[str, str]:
        raw = str(value or "")
        windows = PureWindowsPath(raw)
        normalized = raw.replace("\\", "/")
        directory = normalized.endswith("/")
        trimmed = normalized[:-1] if directory else normalized
        parts = trimmed.split("/")
        if (
            not trimmed
            or "\x00" in raw
            or any(ord(char) < 32 for char in raw)
            or normalized.startswith("/")
            or normalized.startswith("//")
            or windows.is_absolute()
            or bool(windows.drive)
            or any(
                part in {"", ".", ".."}
                or ":" in part
                or part != part.strip()
                or part.endswith((" ", "."))
                or ntpath.isreserved(part)
                for part in parts
            )
        ):
            return "", f"不安全的包路径：{value}"
        return "/".join(parts) + ("/" if directory else ""), ""

    @staticmethod
    def _root_prefix(values: list[str]) -> str:
        parts = [PurePosixPath(value.rstrip("/")).parts for value in values]
        if (
            parts
            and all(len(item) > 1 for item in parts)
            and len({item[0].casefold() for item in parts}) == 1
        ):
            return parts[0][0]
        return ""

    @staticmethod
    def _is_symlink(info: zipfile.ZipInfo) -> bool:
        return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)

    @classmethod
    def _find_secret(cls, value: object, path: str = "") -> str:
        if isinstance(value, dict):
            for key, item in value.items():
                current = f"{path}.{key}" if path else str(key)
                normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
                tokens = {part for part in normalized_key.split("_") if part}
                if (
                    normalized_key in _SENSITIVE_KEYS or tokens & _SENSITIVE_KEYS
                ) and cls._has_value(item):
                    return current
                found = cls._find_secret(item, current)
                if found:
                    return found
        elif isinstance(value, list):
            for index, item in enumerate(value):
                found = cls._find_secret(item, f"{path}[{index}]")
                if found:
                    return found
        return ""

    @staticmethod
    def _has_value(value: object) -> bool:
        if isinstance(value, str) and value.strip() == "******":
            return False
        return value is not None and value != "" and value != [] and value != {}

    @classmethod
    def _find_absolute_path(cls, value: object, path: str = "") -> str:
        if isinstance(value, dict):
            for key, item in value.items():
                current = f"{path}.{key}" if path else str(key)
                found = cls._find_absolute_path(item, current)
                if found:
                    return found
        elif isinstance(value, list):
            for index, item in enumerate(value):
                found = cls._find_absolute_path(item, f"{path}[{index}]")
                if found:
                    return found
        elif isinstance(value, str):
            windows = PureWindowsPath(value)
            if value.startswith("/") or windows.is_absolute() or bool(windows.drive):
                return path or "<root>"
        return ""

    @staticmethod
    def _extract(source: Path, members: dict[str, str], target: Path) -> None:
        target_root = target.resolve()
        with zipfile.ZipFile(source) as archive:
            for relative, source_name in sorted(members.items()):
                destination = (target / PurePosixPath(relative)).resolve()
                OnlineMrAgentPackageImporter._require_within(destination, target_root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(source_name) as source_file,
                    destination.open("xb") as output,
                ):
                    shutil.copyfileobj(source_file, output, length=1024 * 1024)

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        try:
            temporary.write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _sha256(path: Path) -> str:
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest()

    @staticmethod
    def _require_within(path: Path, root: Path) -> None:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("导入路径超出允许目录") from exc

    @classmethod
    def _cleanup_staging(cls, staging_root: Path, imports_root: Path) -> None:
        if not staging_root.exists():
            return
        cls._require_within(staging_root, imports_root)
        shutil.rmtree(staging_root)

    @classmethod
    def _cleanup_import_failure(
        cls, target: Path, staging_root: Path, imports_root: Path
    ) -> None:
        if target.exists():
            sessions_root = target.parent.resolve()
            cls._require_within(target, sessions_root)
            shutil.rmtree(target)
        cls._cleanup_staging(staging_root, imports_root)

    @classmethod
    def _failed_inspection(
        cls,
        source: Path,
        error: str,
        *,
        source_hash: str = "",
    ) -> _InspectedPackage:
        result = OnlineMrAgentPackageInspectResult(
            success=False,
            status="invalid",
            source_zip_sha256=source_hash,
            errors=(cls._safe_error(error),),
        )
        return _InspectedPackage(result=result, members={}, documents={})

    @staticmethod
    def _import_result(
        inspected: OnlineMrAgentPackageInspectResult,
        *,
        status: str = "invalid",
        conflict: bool = False,
        warnings: tuple[str, ...] = (),
        errors: tuple[str, ...] = (),
        session_dir: Path | None = None,
    ) -> OnlineMrAgentPackageImportResult:
        return OnlineMrAgentPackageImportResult(
            success=False,
            status=status,
            session_id=inspected.session_id,
            agent_task_id=inspected.agent_task_id,
            session_dir=session_dir,
            package_status=inspected.package_status,
            data_integrity=inspected.data_integrity,
            conflict=conflict,
            warnings=tuple(dict.fromkeys((*inspected.warnings, *warnings))),
            errors=tuple(dict.fromkeys((*inspected.errors, *errors))),
        )

    @staticmethod
    def _text(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _safe_error(value: object) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ")
        return re.sub(r"(?i)(?:[a-z]:\\|/)[^ ]+", "<path>", text)[:500]


__all__ = [
    "OnlineMrAgentPackageImporter",
    "OnlineMrAgentPackageImportResult",
    "OnlineMrAgentPackageInspectResult",
]
