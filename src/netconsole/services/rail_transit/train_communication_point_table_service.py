from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.rail_transit.car_network_diagnostic import (
    NODE_ORDER,
    CarNetworkNode,
    node_from_mapping,
)
from netconsole.services.rail_transit.train_identity import train_identity_matches


POINT_TABLE_CONFIGURED = "configured"
POINT_TABLE_MISSING = "missing"
POINT_TABLE_INVALID = "invalid"
MISSING_POINT_TABLE_REVISION = "missing"


@dataclass(frozen=True)
class TrainCommunicationPointTableInspection:
    status: str
    revision: str
    nodes: tuple[CarNetworkNode, ...] = ()
    missing_nodes: tuple[str, ...] = ()
    unconfigured_nodes: tuple[str, ...] = ()
    duplicate_nodes: tuple[str, ...] = ()
    row_count: int = 0
    message: str = ""

    @property
    def configured(self) -> bool:
        return self.status == POINT_TABLE_CONFIGURED


class TrainCommunicationPointTableService:
    """读取并校验 Qt 车内通信点表，不负责写入或执行检测。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def revision(self, site_id: str) -> str:
        path = self.paths.car_network_diagnostic_parsed_dir(site_id) / "point_table.json"
        return self._revision(path) if path.is_file() and not path.is_symlink() else MISSING_POINT_TABLE_REVISION

    def read_nodes(self, site_id: str) -> list[CarNetworkNode]:
        path = self.paths.car_network_diagnostic_parsed_dir(site_id) / "point_table.json"
        if not path.is_file() or path.is_symlink():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [node_from_mapping(item) for item in payload if isinstance(item, dict)]

    def inspect(
        self,
        site_id: str,
        train_id: str,
        *,
        train_no: str = "",
        display_name: str = "",
    ) -> TrainCommunicationPointTableInspection:
        path = self.paths.car_network_diagnostic_parsed_dir(site_id) / "point_table.json"
        if not path.is_file() or path.is_symlink():
            return TrainCommunicationPointTableInspection(
                status=POINT_TABLE_MISSING,
                revision=MISSING_POINT_TABLE_REVISION,
                message="检测点表未配置",
            )

        revision = self._revision(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return TrainCommunicationPointTableInspection(
                status=POINT_TABLE_INVALID,
                revision=revision,
                message="检测点表文件无法读取",
            )
        if not isinstance(payload, list):
            return TrainCommunicationPointTableInspection(
                status=POINT_TABLE_INVALID,
                revision=revision,
                message="检测点表格式无效",
            )

        nodes: list[CarNetworkNode] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                node = node_from_mapping(item)
            except (TypeError, ValueError, KeyError):
                continue
            if self._matches_train(node, train_id, train_no, display_name):
                nodes.append(node)

        if not nodes:
            return TrainCommunicationPointTableInspection(
                status=POINT_TABLE_MISSING,
                revision=revision,
                row_count=len(payload),
                message="当前列车未配置检测点表",
            )

        by_name: dict[str, CarNetworkNode] = {}
        duplicates: list[str] = []
        for node in nodes:
            name = node.normalized_name
            if name in by_name:
                duplicates.append(name)
            else:
                by_name[name] = node
        missing = tuple(name for name in NODE_ORDER if name not in by_name)
        unconfigured = tuple(name for name in NODE_ORDER if name in by_name and not self._has_endpoint(by_name[name]))
        duplicate_nodes = tuple(dict.fromkeys(duplicates))
        if missing or unconfigured or duplicate_nodes:
            reasons: list[str] = []
            if missing:
                reasons.append(f"缺少检测点：{', '.join(missing)}")
            if unconfigured:
                reasons.append(f"节点未关联设备或地址：{', '.join(unconfigured)}")
            if duplicate_nodes:
                reasons.append(f"检测点重复：{', '.join(duplicate_nodes)}")
            return TrainCommunicationPointTableInspection(
                status=POINT_TABLE_INVALID,
                revision=revision,
                nodes=tuple(nodes),
                missing_nodes=missing,
                unconfigured_nodes=unconfigured,
                duplicate_nodes=duplicate_nodes,
                row_count=len(payload),
                message="；".join(reasons),
            )
        return TrainCommunicationPointTableInspection(
            status=POINT_TABLE_CONFIGURED,
            revision=revision,
            nodes=tuple(nodes),
            row_count=len(payload),
            message="检测点表已配置",
        )

    @staticmethod
    def _matches_train(node: CarNetworkNode, train_id: str, train_no: str, display_name: str) -> bool:
        return train_identity_matches(
            (train_id, train_no, display_name),
            (node.train_id, node.train_no, node.display_name),
        )

    @classmethod
    def has_endpoint(cls, node: CarNetworkNode) -> bool:
        """Return whether a point has enough addressing data to be checked."""
        return cls._has_endpoint(node)

    @staticmethod
    def _has_endpoint(node: CarNetworkNode) -> bool:
        return bool(
            str(node.device_id or "").strip()
            or str(node.primary_address or "").strip()
            or str(node.backup_address or "").strip()
            or str(node.ip_vehicle or "").strip()
            or str(node.ip_uplink or "").strip()
            or str(node.ssh_host or "").strip()
        )

    @staticmethod
    def _revision(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return ""


__all__ = [
    "POINT_TABLE_CONFIGURED",
    "POINT_TABLE_INVALID",
    "POINT_TABLE_MISSING",
    "MISSING_POINT_TABLE_REVISION",
    "TrainCommunicationPointTableInspection",
    "TrainCommunicationPointTableService",
]
