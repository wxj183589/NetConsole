from __future__ import annotations

import asyncio
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.models.agent import AgentAuthenticationType, AgentConfig, AgentRuntimeSnapshot, AgentStatus
from netconsole.repositories.agent_repository import AgentRepository
from netconsole.services.agent.credential_vault import SessionCredentialVault
from netconsole.services.agent.event_hub import AgentEventHub
from netconsole.services.agent.http_client import AgentClientError, AgentHttpClient, AgentProbeResult, normalize_agent_base_url


@dataclass(frozen=True)
class AgentControllerSettings:
    health_check_enabled: bool = True
    health_check_interval_seconds: float = 30.0
    health_check_concurrency: int = 4

    @classmethod
    def from_environment(cls) -> AgentControllerSettings:
        return cls(
            health_check_enabled=os.environ.get("NETCONSOLE_AGENT_HEALTH_ENABLED", "1") != "0",
            health_check_interval_seconds=max(5.0, float(os.environ.get("NETCONSOLE_AGENT_HEALTH_INTERVAL", "30"))),
            health_check_concurrency=max(1, min(int(os.environ.get("NETCONSOLE_AGENT_HEALTH_CONCURRENCY", "4")), 16)),
        )


class AgentControllerError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AgentControllerService:
    def __init__(
        self,
        *,
        paths: PathResolver | None = None,
        site_name: str = "demo",
        repository: AgentRepository | None = None,
        client: AgentHttpClient | None = None,
        credential_vault: SessionCredentialVault | None = None,
        event_hub: AgentEventHub | None = None,
        settings: AgentControllerSettings | None = None,
    ) -> None:
        self.paths = paths or PathResolver()
        self.site_name = str(site_name or "demo")
        self.repository = repository or AgentRepository(self.paths.site_agents_db_path(self.site_name))
        self.client = client or AgentHttpClient()
        self.credentials = credential_vault or SessionCredentialVault()
        self.events = event_hub or AgentEventHub()
        self.settings = settings or AgentControllerSettings.from_environment()
        self._health_task: asyncio.Task[None] | None = None

    def list_agents(self) -> list[dict[str, Any]]:
        return [self._record(config, runtime) for config, runtime in self.repository.list_with_runtime()]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        config = self._require_config(agent_id)
        return self._record(config, self.repository.get_runtime(agent_id))

    def create_agent(
        self,
        *,
        name: str,
        base_url: str,
        enabled: bool,
        authentication_type: AgentAuthenticationType,
        token: str = "",
        tags: list[str] | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        now = _utc_now()
        reference = ""
        if authentication_type is AgentAuthenticationType.TOKEN and token:
            reference = self.credentials.store(token)
        config = AgentConfig(
            agent_id=uuid.uuid4().hex,
            name=name.strip(),
            base_url=_normalize_url(base_url),
            enabled=enabled,
            authentication_type=authentication_type,
            credential_reference=reference,
            tags=_normalize_tags(tags or []),
            note=note.strip(),
            created_at=now,
            updated_at=now,
        )
        try:
            self.repository.create(config)
        except sqlite3.IntegrityError as exc:
            if reference:
                self.credentials.remove(reference)
            raise AgentControllerError("AGENT_ALREADY_EXISTS", "相同 Agent 地址已存在", status_code=409) from exc
        if not enabled:
            self.repository.save_runtime(_disabled_snapshot(config.agent_id, now))
        record = self.get_agent(config.agent_id)
        self.events.publish("agent.created", config.agent_id, record)
        return record

    def update_agent(self, agent_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        current = self._require_config(agent_id)
        authentication_type = AgentAuthenticationType(changes.get("authentication_type", current.authentication_type))
        reference = current.credential_reference
        new_reference = ""
        remove_after_update = ""
        token = str(changes.get("token") or "")
        if authentication_type is AgentAuthenticationType.NONE:
            remove_after_update = reference
            reference = ""
        elif token:
            new_reference = self.credentials.store(token)
            remove_after_update = reference
            reference = new_reference
        updated = AgentConfig(
            **{
                **asdict(current),
                "name": str(changes.get("name", current.name)).strip(),
                "base_url": _normalize_url(str(changes.get("base_url", current.base_url))),
                "enabled": bool(changes.get("enabled", current.enabled)),
                "authentication_type": authentication_type,
                "credential_reference": reference,
                "tags": _normalize_tags(changes.get("tags", current.tags)),
                "note": str(changes.get("note", current.note)).strip(),
                "updated_at": _utc_now(),
            }
        )
        try:
            self.repository.update(updated)
        except sqlite3.IntegrityError as exc:
            if new_reference:
                self.credentials.remove(new_reference)
            raise AgentControllerError("AGENT_ALREADY_EXISTS", "相同 Agent 地址已存在", status_code=409) from exc
        except Exception:
            if new_reference:
                self.credentials.remove(new_reference)
            raise
        if remove_after_update:
            self.credentials.remove(remove_after_update)
        if current.enabled and not updated.enabled:
            self.repository.save_runtime(_disabled_snapshot(agent_id, updated.updated_at))
            self.events.publish("agent.disabled", agent_id, self.get_agent(agent_id))
        elif not current.enabled and updated.enabled:
            self.repository.save_runtime(AgentRuntimeSnapshot(agent_id=agent_id, updated_at=updated.updated_at))
            self.events.publish("agent.enabled", agent_id, self.get_agent(agent_id))
        else:
            self.events.publish("agent.updated", agent_id, self.get_agent(agent_id))
        return self.get_agent(agent_id)

    def set_enabled(self, agent_id: str, enabled: bool) -> dict[str, Any]:
        current = self._require_config(agent_id)
        if current.enabled == enabled:
            return self.get_agent(agent_id)
        return self.update_agent(agent_id, {"enabled": enabled})

    def archive_agent(self, agent_id: str) -> bool:
        config = self.repository.get(agent_id, include_archived=True)
        if config is None:
            raise AgentControllerError("AGENT_NOT_FOUND", "Agent 不存在", status_code=404)
        if config.archived_at:
            return True
        now = _utc_now()
        if not self.repository.archive(agent_id, now):
            return False
        if config.credential_reference:
            self.credentials.remove(config.credential_reference)
        self.events.publish("agent.deleted", agent_id, {"agent_id": agent_id, "archived": True})
        return True

    async def probe_agent(
        self,
        agent_id: str,
        *,
        publish_probe: bool = True,
        persist_unchanged: bool = True,
        raise_on_failure: bool = False,
    ) -> dict[str, Any]:
        config = self._require_config(agent_id)
        if not config.enabled:
            snapshot = _disabled_snapshot(agent_id, _utc_now())
            self.repository.save_runtime(snapshot)
            return self._record(config, snapshot)
        previous = self.repository.get_runtime(agent_id)
        try:
            token = self._credential_for(config)
            snapshot = await self._probe_snapshot(config, token)
        except AgentControllerError as exc:
            now = _utc_now()
            snapshot = AgentRuntimeSnapshot(
                agent_id=agent_id,
                status=AgentStatus.UNAUTHORIZED,
                last_seen_at=previous.last_seen_at if previous else "",
                last_checked_at=now,
                version=previous.version if previous else "",
                platform=previous.platform if previous else "",
                architecture=previous.architecture if previous else "",
                capabilities=previous.capabilities if previous else {},
                last_error_code=exc.code,
                last_error_message=exc.message,
                updated_at=now,
            )
        changed = previous is None or _runtime_signature(previous) != _runtime_signature(snapshot)
        if persist_unchanged or changed:
            self.repository.save_runtime(snapshot)
        record = self._record(config, snapshot)
        if changed:
            self.events.publish("agent.status_changed", agent_id, record)
        if publish_probe:
            self.events.publish("agent.probe_completed", agent_id, record)
        if raise_on_failure and snapshot.status in {AgentStatus.OFFLINE, AgentStatus.UNAUTHORIZED}:
            code = snapshot.last_error_code or "AGENT_PROBE_FAILED"
            status_code = 401 if snapshot.status is AgentStatus.UNAUTHORIZED else 502
            if code == "AGENT_CREDENTIAL_REQUIRED":
                status_code = 409
            raise AgentControllerError(code, snapshot.last_error_message or "Agent 探测失败", status_code=status_code)
        return record

    async def probe_unsaved(self, *, base_url: str, authentication_type: AgentAuthenticationType, token: str = "") -> dict[str, Any]:
        if authentication_type is AgentAuthenticationType.TOKEN and not token:
            raise AgentControllerError("AGENT_CREDENTIAL_REQUIRED", "测试连接需要填写 Agent Token")
        try:
            result = await self.client.probe(base_url, token or None)
        except ValueError as exc:
            raise AgentControllerError("AGENT_URL_INVALID", str(exc), status_code=422) from exc
        except AgentClientError as exc:
            raise AgentControllerError(exc.code, exc.message, status_code=_client_status(exc)) from exc
        return _probe_result_dict(result)

    async def get_remote_status(self, agent_id: str) -> dict[str, Any]:
        config, token = self._remote_context(agent_id)
        return await self._read_remote(lambda: self.client.get_status(config.base_url, token))

    async def get_remote_tools(self, agent_id: str) -> dict[str, Any]:
        config, token = self._remote_context(agent_id)
        return await self._read_remote(lambda: self.client.get_tools_status(config.base_url, token))

    async def list_remote_tasks(self, agent_id: str) -> list[dict[str, Any]]:
        config, token = self._remote_context(agent_id)
        tasks = await self._read_remote(lambda: self.client.list_tasks(config.base_url, token))
        return [asdict(task) for task in tasks]

    async def get_remote_task(self, agent_id: str, task_id: str) -> dict[str, Any]:
        config, token = self._remote_context(agent_id)
        task = await self._read_remote(lambda: self.client.get_task(config.base_url, task_id, token))
        return asdict(task)

    async def get_remote_task_logs(self, agent_id: str, task_id: str, *, tail: int = 300) -> dict[str, Any]:
        config, token = self._remote_context(agent_id)
        lines = await self._read_remote(
            lambda: self.client.get_task_logs(config.base_url, task_id, tail=tail, token=token)
        )
        return {"task_id": task_id, "lines": list(lines)}

    async def list_remote_packages(self, agent_id: str) -> list[dict[str, Any]]:
        config, token = self._remote_context(agent_id)
        packages = await self._read_remote(lambda: self.client.list_packages(config.base_url, token))
        return list(packages)

    async def start(self) -> None:
        if not self.settings.health_check_enabled or self._health_task is not None:
            return
        self._health_task = asyncio.create_task(self._health_loop(), name="agent-health-check")

    async def stop(self) -> None:
        task, self._health_task = self._health_task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def run_health_check_once(self) -> None:
        enabled = [config for config in self.repository.list() if config.enabled]
        semaphore = asyncio.Semaphore(self.settings.health_check_concurrency)

        async def check(config: AgentConfig) -> None:
            async with semaphore:
                await self.probe_agent(config.agent_id, publish_probe=False, persist_unchanged=False)

        await asyncio.gather(*(check(config) for config in enabled), return_exceptions=True)

    async def _health_loop(self) -> None:
        while True:
            await self.run_health_check_once()
            await asyncio.sleep(self.settings.health_check_interval_seconds)

    async def _probe_snapshot(self, config: AgentConfig, token: str | None) -> AgentRuntimeSnapshot:
        now = _utc_now()
        try:
            result = await self.client.probe(config.base_url, token)
            return AgentRuntimeSnapshot(
                agent_id=config.agent_id,
                status=AgentStatus.ONLINE,
                last_seen_at=now,
                last_checked_at=now,
                latency_ms=result.latency_ms,
                version=result.version,
                platform=result.platform,
                architecture=result.architecture,
                capabilities=result.capabilities,
                updated_at=now,
            )
        except AgentClientError as exc:
            status = AgentStatus.UNAUTHORIZED if exc.code == "AGENT_UNAUTHORIZED" else AgentStatus.OFFLINE
            previous = self.repository.get_runtime(config.agent_id)
            return AgentRuntimeSnapshot(
                agent_id=config.agent_id,
                status=status,
                last_seen_at=previous.last_seen_at if previous else "",
                last_checked_at=now,
                version=previous.version if previous else "",
                platform=previous.platform if previous else "",
                architecture=previous.architecture if previous else "",
                capabilities=previous.capabilities if previous else {},
                last_error_code=exc.code,
                last_error_message=exc.message,
                updated_at=now,
            )

    def _credential_for(self, config: AgentConfig) -> str | None:
        if config.authentication_type is AgentAuthenticationType.NONE:
            return None
        value = self.credentials.get(config.credential_reference)
        if value is None:
            raise AgentControllerError("AGENT_CREDENTIAL_REQUIRED", "Agent Token 未加载，请重新编辑认证配置", status_code=409)
        return value

    def _remote_context(self, agent_id: str) -> tuple[AgentConfig, str | None]:
        config = self._require_config(agent_id)
        if not config.enabled:
            raise AgentControllerError("AGENT_DISABLED", "Agent 已禁用", status_code=409)
        return config, self._credential_for(config)

    @staticmethod
    async def _read_remote(operation):
        try:
            return await operation()
        except ValueError as exc:
            raise AgentControllerError("AGENT_REQUEST_INVALID", str(exc), status_code=422) from exc
        except AgentClientError as exc:
            raise AgentControllerError(exc.code, exc.message, status_code=_client_status(exc)) from exc

    def _require_config(self, agent_id: str) -> AgentConfig:
        config = self.repository.get(agent_id)
        if config is None:
            raise AgentControllerError("AGENT_NOT_FOUND", "Agent 不存在", status_code=404)
        return config

    def _record(self, config: AgentConfig, runtime: AgentRuntimeSnapshot | None) -> dict[str, Any]:
        snapshot = runtime or AgentRuntimeSnapshot(
            agent_id=config.agent_id,
            status=AgentStatus.UNKNOWN if config.enabled else AgentStatus.DISABLED,
        )
        status = snapshot.status if config.enabled else AgentStatus.DISABLED
        return {
            "agent_id": config.agent_id,
            "name": config.name,
            "base_url": config.base_url,
            "enabled": config.enabled,
            "authentication_type": config.authentication_type.value,
            "has_credential": self.credentials.contains(config.credential_reference),
            "tags": list(config.tags),
            "note": config.note,
            "created_at": config.created_at,
            "updated_at": config.updated_at,
            "status": status.value,
            "last_seen_at": snapshot.last_seen_at,
            "last_checked_at": snapshot.last_checked_at,
            "latency_ms": snapshot.latency_ms,
            "version": snapshot.version,
            "platform": snapshot.platform,
            "architecture": snapshot.architecture,
            "capabilities": dict(snapshot.capabilities),
            "last_error_code": snapshot.last_error_code,
            "last_error_message": snapshot.last_error_message,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _normalize_tags(values: list[str] | Any) -> list[str]:
    result: list[str] = []
    for value in values if isinstance(values, list) else []:
        text = str(value).strip()
        if text and text not in result:
            result.append(text[:40])
    return result[:20]


def _disabled_snapshot(agent_id: str, now: str) -> AgentRuntimeSnapshot:
    return AgentRuntimeSnapshot(agent_id=agent_id, status=AgentStatus.DISABLED, last_checked_at=now, updated_at=now)


def _runtime_signature(snapshot: AgentRuntimeSnapshot) -> tuple[Any, ...]:
    return (
        snapshot.status,
        snapshot.version,
        snapshot.platform,
        snapshot.architecture,
        snapshot.capabilities,
        snapshot.last_error_code,
        snapshot.last_error_message,
    )


def _probe_result_dict(result: AgentProbeResult) -> dict[str, Any]:
    return {
        "remote_agent_id": result.remote_agent_id,
        "remote_name": result.remote_name,
        "version": result.version,
        "platform": result.platform,
        "architecture": result.architecture,
        "capabilities": dict(result.capabilities),
        "latency_ms": result.latency_ms,
    }


def _client_status(error: AgentClientError) -> int:
    if error.code == "AGENT_UNAUTHORIZED":
        return 401
    if error.code in {"AGENT_RESPONSE_INCOMPATIBLE", "AGENT_VERSION_UNSUPPORTED", "AGENT_INVALID_JSON"}:
        return 422
    return 502


def _normalize_url(value: str) -> str:
    try:
        return normalize_agent_base_url(value)
    except ValueError as exc:
        raise AgentControllerError("AGENT_URL_INVALID", str(exc), status_code=422) from exc
