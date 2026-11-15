from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.parsers.h3c.arp_parser import ArpParseResult, ArpRecord, parse_h3c_arp
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ground_arp_repository import GroundArpRepository
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.online_mr_collector import NetmikoShellConnection
from netconsole.services.ground_unattended.arp_identity import GroundMrIdentityService


class ArpConnection(Protocol):
    def send_command(self, command: str, timeout: int) -> str: ...
    def close(self) -> None: ...


class GroundArpCollector:
    """Read-only switch ARP collector with failure-safe snapshot semantics."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        repository: GroundArpRepository,
        identity_service: GroundMrIdentityService,
        mr_provider: Callable[[], list[object]],
        connection_factory: Callable[[OnlineMrConnectionConfig], ArpConnection] = NetmikoShellConnection,
        now_provider: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id)
        self.repository = repository
        self.identity_service = identity_service
        self.mr_provider = mr_provider
        self.connection_factory = connection_factory
        self.now_provider = now_provider

    def collect(self, *, source_device_uuid: str, vlans: list[int]) -> dict[str, object]:
        started = self.now_provider().astimezone().isoformat(timespec="milliseconds")
        source = DeviceRepository(Database(self.paths.site_db_path(self.site_id))).get_by_uuid(str(source_device_uuid))
        if source is None:
            parse_result = ArpParseResult(status="FAILED", completeness="UNKNOWN", warnings=("ARP 源交换机不存在",))
            saved = self.repository.save_collection(
                source_device_uuid=str(source_device_uuid), source_device_name="",
                query_mode="VLAN" if vlans else "ALL", query_scope=_scope(vlans),
                requested_vlans=vlans, started_at=started, completed_at=started,
                parse_result=parse_result, error_message="ARP 源交换机不存在",
            )
            return saved
        return self.collect_from_device(source=source, vlans=vlans, started_at=started)

    def collect_from_device(self, *, source: Device, vlans: list[int], started_at: str = "") -> dict[str, object]:
        started = started_at or self.now_provider().astimezone().isoformat(timespec="milliseconds")
        scope = _scope(vlans)
        mode = "VLAN" if vlans else "ALL"
        outputs: list[ArpRecord] = []
        warnings: list[str] = []
        complete = True
        status = "SUCCESS"
        error = ""
        connection: ArpConnection | None = None
        try:
            config = self._connection_config(source, paths=self.paths, site_id=self.site_id)
            connection = self.connection_factory(config)
            try:
                connection.send_command("screen-length disable", config.command_timeout)
            except Exception:
                warnings.append("无法关闭分页，若回显含分页标记则按不完整快照处理")
            commands = [f"display arp vlan {vlan}" for vlan in vlans] if vlans else ["display arp"]
            for command in commands:
                try:
                    output = connection.send_command(command, config.command_timeout)
                except Exception as exc:
                    complete = False
                    status = "PARTIAL" if outputs else "FAILED"
                    error = f"{exc.__class__.__name__}: {exc}"
                    warnings.append(f"命令失败: {command}")
                    continue
                parsed = parse_h3c_arp(output)
                outputs.extend(parsed.records)
                warnings.extend(parsed.warnings)
                if not parsed.complete:
                    complete = False
                    status = "TRUNCATED" if parsed.status == "TRUNCATED" else "PARTIAL"
            if complete:
                parse_result = ArpParseResult(
                    records=tuple(_unique_records(outputs)), status="SUCCESS", completeness="COMPLETE",
                    header_detected=True,
                )
            else:
                parse_result = ArpParseResult(
                    records=tuple(_unique_records(outputs)), status=status,
                    completeness="INCOMPLETE", truncation_detected=status == "TRUNCATED",
                    header_detected=bool(outputs), warnings=tuple(dict.fromkeys(warnings)),
                )
        except Exception as exc:
            parse_result = ArpParseResult(
                records=tuple(_unique_records(outputs)), status="FAILED", completeness="UNKNOWN",
                header_detected=bool(outputs), warnings=tuple(dict.fromkeys(warnings)),
            )
            error = f"{exc.__class__.__name__}: {exc}"
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        completed = self.now_provider().astimezone().isoformat(timespec="milliseconds")
        saved = self.repository.save_collection(
            source_device_uuid=str(source.device_uuid or ""),
            source_device_name=str(source.name or source.system_name or ""),
            query_mode=mode, query_scope=scope, requested_vlans=vlans,
            started_at=started, completed_at=completed, parse_result=parse_result,
            error_message=error, raw_reference="",
        )
        collection_id = str(saved.get("collection_id") or "")
        identity = self.identity_service.apply_collection(
            collection_id=collection_id, records=parse_result.records, mrs=self.mr_provider()
        )
        self.repository.update_collection_stats(
            collection_id, matched_count=identity["matched_count"],
            conflict_count=identity["conflict_count"],
        )
        saved.update(identity)
        return saved

    @staticmethod
    def _connection_config(source: Device, *, paths: PathResolver, site_id: str) -> OnlineMrConnectionConfig:
        targets = tuple(connection_targets(source))
        if not targets:
            raise ValueError("ARP 源交换机没有可用的 SSH/Telnet 配置")
        first = targets[0]
        return OnlineMrConnectionConfig(
            site=site_id, mr_id=str(source.device_uuid or ""), mr_name=str(source.name or "SW"),
            safe_mr_name="ground-arp", device_id=source.id, device_name=str(source.name or "SW"),
            host=first.host, protocol=first.protocol, port=first.port,
            username=first.username, password=first.password, command_timeout=20,
            connection_targets=targets, paths=paths,
        )


def _scope(vlans: list[int]) -> str:
    return "ALL" if not vlans else "VLAN:" + ",".join(str(value) for value in sorted(set(vlans)))


def _unique_records(records: list[ArpRecord]) -> list[ArpRecord]:
    result: list[ArpRecord] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        key = (record.ip_address, record.mac_address, record.vlan, record.interface_name)
        if key not in seen:
            seen.add(key)
            result.append(record)
    return result


__all__ = ["GroundArpCollector"]
