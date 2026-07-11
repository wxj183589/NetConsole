from __future__ import annotations

from dataclasses import asdict, dataclass

from netconsole.services.ap_identity import ApMatchEvidence


@dataclass(frozen=True)
class AcApIdentityShadowItem:
    extension_ref: str
    old_status: str
    old_match_key: str | None
    new_status: str
    new_candidate_key: str | None
    identity_changed: bool
    identity_unchanged: bool
    name_only_match: bool
    mac_like_name: bool
    missing_ac_scope: bool
    evidence: tuple[ApMatchEvidence, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "extension_ref": self.extension_ref,
            "old_status": self.old_status,
            "old_match_key": self.old_match_key,
            "new_status": self.new_status,
            "new_candidate_key": self.new_candidate_key,
            "identity_changed": self.identity_changed,
            "identity_unchanged": self.identity_unchanged,
            "name_only_match": self.name_only_match,
            "mac_like_name": self.mac_like_name,
            "missing_ac_scope": self.missing_ac_scope,
            "evidence": [asdict(item) for item in self.evidence],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AcApIdentityShadowReport:
    total: int = 0
    matched: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    identity_unchanged: int = 0
    identity_changed: int = 0
    name_only_matches: int = 0
    mac_like_names: int = 0
    missing_ac_scope: int = 0
    available: bool = True
    warnings: tuple[str, ...] = ()
    items: tuple[AcApIdentityShadowItem, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "total": self.total,
            "matched": self.matched,
            "unresolved": self.unresolved,
            "ambiguous": self.ambiguous,
            "identity_unchanged": self.identity_unchanged,
            "identity_changed": self.identity_changed,
            "name_only_matches": self.name_only_matches,
            "mac_like_names": self.mac_like_names,
            "missing_ac_scope": self.missing_ac_scope,
            "available": self.available,
            "warnings": list(self.warnings),
            "items": [item.to_payload() for item in self.items],
        }


@dataclass(frozen=True)
class AcOpticalIdentityShadowItem:
    optical_ref: str
    record_type: str
    old_ap_key: str | None
    new_status: str
    new_candidate_key: str | None
    identity_changed: bool
    identity_unchanged: bool
    name_only_match: bool
    mac_like_name: bool
    missing_ac_scope: bool
    interface_only: bool
    evidence: tuple[ApMatchEvidence, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "optical_ref": self.optical_ref,
            "record_type": self.record_type,
            "old_ap_key": self.old_ap_key,
            "new_status": self.new_status,
            "new_candidate_key": self.new_candidate_key,
            "identity_changed": self.identity_changed,
            "identity_unchanged": self.identity_unchanged,
            "name_only_match": self.name_only_match,
            "mac_like_name": self.mac_like_name,
            "missing_ac_scope": self.missing_ac_scope,
            "interface_only": self.interface_only,
            "evidence": [asdict(item) for item in self.evidence],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AcOpticalIdentityShadowReport:
    total: int = 0
    matched: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    identity_unchanged: int = 0
    identity_changed: int = 0
    ap_side_records: int = 0
    switch_side_records: int = 0
    interface_only_records: int = 0
    offline_records: int = 0
    name_only_matches: int = 0
    mac_like_names: int = 0
    missing_ac_scope: int = 0
    available: bool = True
    warnings: tuple[str, ...] = ()
    items: tuple[AcOpticalIdentityShadowItem, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "available": self.available,
            "total": self.total,
            "matched": self.matched,
            "unresolved": self.unresolved,
            "ambiguous": self.ambiguous,
            "identity_unchanged": self.identity_unchanged,
            "identity_changed": self.identity_changed,
            "ap_side_records": self.ap_side_records,
            "switch_side_records": self.switch_side_records,
            "interface_only_records": self.interface_only_records,
            "offline_records": self.offline_records,
            "name_only_matches": self.name_only_matches,
            "mac_like_names": self.mac_like_names,
            "missing_ac_scope": self.missing_ac_scope,
            "warnings": list(self.warnings),
            "items": [item.to_payload() for item in self.items],
        }
