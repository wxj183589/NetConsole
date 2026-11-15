from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from netconsole.parsers.h3c.arp_parser import ArpRecord
from netconsole.repositories.ground_arp_repository import GroundArpRepository
from netconsole.utils.mac_utils import H3cMacDeriveError, derive_h3c_r1_mac, derive_h3c_r2_mac, normalize_mac


@dataclass(frozen=True)
class IdentityResolution:
    mr_uuid: str = ""
    status: str = "UNRESOLVED"
    matched_by: str = ""
    identity_mac: str = ""
    warning: str = ""


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return dict(dumper(mode="json"))
    return {name: getattr(value, name) for name in (
        "id", "mr_uuid", "device_uuid", "train_id", "train_no", "role",
        "management_ip", "backup_management_ip", "mac", "name",
    ) if hasattr(value, name)}


def _mr_uuid(mr: Mapping[str, Any]) -> str:
    return str(mr.get("mr_uuid") or mr.get("device_uuid") or mr.get("id") or "").strip()


def _ip_values(mr: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(mr.get(key) or "").strip()
        for key in ("management_ip", "backup_management_ip")
        if str(mr.get(key) or "").strip()
    ))


def _mac(value: object) -> str:
    try:
        return normalize_mac(str(value or ""))
    except ValueError:
        return ""


def _h3c_aliases(base: str) -> tuple[tuple[str, str], ...]:
    """Reuse the existing H3C AP radio rule only for an explicit base MAC.

    The legacy rule is valid for a confirmed physical/base MAC ending in 0;
    this guard prevents a generic last-nibble heuristic from becoming an MR
    identity algorithm.
    """

    if not base or not base.replace(":", "").upper().endswith("0"):
        return ()
    result: list[tuple[str, str]] = []
    for alias_type, builder in (("DERIVED_R1", derive_h3c_r1_mac), ("DERIVED_R2", derive_h3c_r2_mac)):
        try:
            alias = _mac(builder(base))
        except (H3cMacDeriveError, ValueError):
            continue
        if alias and alias != base:
            result.append((alias, alias_type))
    return tuple(result)


class GroundMrIdentityService:
    """Build and query a durable, site-bounded MR identity index."""

    def __init__(self, repository: GroundArpRepository) -> None:
        self.repository = repository

    def register_mr_registry(self, mrs: Iterable[object]) -> None:
        for item in mrs:
            mr = _mapping(item)
            uuid = _mr_uuid(mr)
            base = _mac(mr.get("mac"))
            if not uuid or not base:
                continue
            self._save_registry_relation(mr, base, "BASE")
            for alias, alias_type in _h3c_aliases(base):
                self._save_registry_relation(mr, alias, alias_type)

    def _save_registry_relation(self, mr: Mapping[str, Any], mac: str, alias_type: str) -> None:
        existing = self.repository.find_identity_relations(identity_mac=mac, confirmed_only=True)
        other = [row for row in existing if str(row.get("mr_uuid") or "") != _mr_uuid(mr)]
        status = "CONFLICT" if other else "CONFIRMED"
        if other:
            self.repository.save_conflict(
                conflict_type="MAC_MULTIPLE_MR",
                conflict_key=f"MAC_MULTIPLE_MR:{mac}",
                mac_address=mac,
                details={"mac": mac, "mr_uuids": sorted({str(row.get("mr_uuid") or "") for row in existing} | {_mr_uuid(mr)})},
            )
        self.repository.save_identity_relation(
            mr=mr, identity_mac=mac, alias_type=alias_type, source="DEVICE_REGISTRY",
            confirmation_status=status, management_ip=str(mr.get("management_ip") or ""),
        )

    def apply_collection(
        self,
        *,
        collection_id: str,
        records: Iterable[ArpRecord],
        mrs: Iterable[object],
    ) -> dict[str, int]:
        mr_rows = [_mapping(item) for item in mrs]
        self.register_mr_registry(mr_rows)
        by_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for mr in mr_rows:
            for ip in _ip_values(mr):
                by_ip[ip].append(mr)
        matched = conflicts = 0
        for record in records:
            candidates = by_ip.get(record.ip_address, [])
            mac = _mac(record.mac_address)
            if not mac:
                continue
            if len(candidates) != 1:
                if len(candidates) > 1:
                    conflicts += 1
                    self._conflict(
                        collection_id, "IP_MULTIPLE_MR", f"IP_MULTIPLE_MR:{record.ip_address}",
                        record, candidates,
                    )
                continue
            mr = candidates[0]
            uuid = _mr_uuid(mr)
            confirmed_by_mac = self.repository.find_identity_relations(identity_mac=mac, confirmed_only=True)
            other = [row for row in confirmed_by_mac if str(row.get("mr_uuid") or "") != uuid]
            if other:
                conflicts += 1
                self._conflict(
                    collection_id, "MAC_MULTIPLE_MR", f"MAC_MULTIPLE_MR:{mac}",
                    record, [mr], extra={"existing_mr_uuids": [str(row.get("mr_uuid") or "") for row in other]},
                )
                self.repository.save_identity_relation(
                    mr=mr, identity_mac=mac, alias_type="ARP_OBSERVED", source="ARP",
                    confirmation_status="CONFLICT", management_ip=record.ip_address,
                    collection_id=collection_id, details={"reason": "MAC already confirmed to another MR"},
                )
                continue
            existing_for_mr = self.repository.find_identity_relations(mr_uuid=uuid, confirmed_only=True)
            base = _mac(mr.get("mac"))
            aliases = {base: "BASE", **dict(_h3c_aliases(base))}
            alias_type = aliases.get(mac, "ARP_IP_CONFIRMED")
            known_same_mr = {str(row.get("identity_mac") or "") for row in existing_for_mr}
            if known_same_mr and mac not in known_same_mr and alias_type == "ARP_IP_CONFIRMED":
                conflicts += 1
                self._conflict(
                    collection_id, "MR_MAC_CHANGED", f"MR_MAC_CHANGED:{uuid}:{mac}",
                    record, [mr], extra={"confirmed_macs": sorted(known_same_mr)},
                )
                self.repository.save_identity_relation(
                    mr=mr, identity_mac=mac, alias_type="ARP_OBSERVED", source="ARP",
                    confirmation_status="CONFLICT", management_ip=record.ip_address,
                    collection_id=collection_id, details={"reason": "different MAC for confirmed MR"},
                )
                continue
            matched += 1
            self.repository.save_identity_relation(
                mr=mr, identity_mac=mac, alias_type=alias_type, source="ARP",
                confirmation_status="CONFIRMED", management_ip=record.ip_address,
                collection_id=collection_id, details={"vlan": record.vlan, "interface": record.interface_name},
            )
        return {"matched_count": matched, "conflict_count": conflicts}

    def _conflict(
        self, collection_id: str, conflict_type: str, key: str, record: ArpRecord,
        mrs: Iterable[Mapping[str, Any]], *, extra: Mapping[str, Any] | None = None,
    ) -> None:
        self.repository.save_conflict(
            conflict_type=conflict_type, conflict_key=key,
            ip_address=record.ip_address, mac_address=_mac(record.mac_address),
            collection_id=collection_id,
            details={
                "ip": record.ip_address, "mac": _mac(record.mac_address),
                "mr_uuids": [_mr_uuid(mr) for mr in mrs], **dict(extra or {}),
            },
        )

    def resolve_peer(self, peer_mac: str, mrs: Iterable[object] = ()) -> IdentityResolution:
        mac = _mac(peer_mac)
        if not mac:
            return IdentityResolution(warning="Peer MAC 为空或格式无效")
        rows = self.repository.find_identity_relations(identity_mac=mac, confirmed_only=True)
        mr_ids = sorted({str(row.get("mr_uuid") or "") for row in rows if row.get("mr_uuid")})
        if len(mr_ids) == 1:
            return IdentityResolution(mr_uuid=mr_ids[0], status="CONFIRMED", matched_by="CONFIRMED_MAC", identity_mac=mac)
        if len(mr_ids) > 1:
            return IdentityResolution(status="CONFLICT", matched_by="CONFIRMED_MAC", identity_mac=mac, warning="MAC 已确认到多个 MR")
        mr_rows = [_mapping(item) for item in mrs]
        candidates: list[str] = []
        for mr in mr_rows:
            base = _mac(mr.get("mac"))
            aliases = {base, *(alias for alias, _ in _h3c_aliases(base))}
            if mac in aliases and _mr_uuid(mr):
                candidates.append(_mr_uuid(mr))
        candidates = sorted(set(candidates))
        if len(candidates) == 1:
            return IdentityResolution(mr_uuid=candidates[0], status="CONFIRMED", matched_by="REGISTRY_MAC_RULE", identity_mac=mac)
        if len(candidates) > 1:
            return IdentityResolution(status="CONFLICT", matched_by="REGISTRY_MAC_RULE", identity_mac=mac, warning="H3C MAC 规则候选不唯一")
        return IdentityResolution(identity_mac=mac, warning="未找到精确确认的 MR 身份")


__all__ = ["GroundMrIdentityService", "IdentityResolution"]
