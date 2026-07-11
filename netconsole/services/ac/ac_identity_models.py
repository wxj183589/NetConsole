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
