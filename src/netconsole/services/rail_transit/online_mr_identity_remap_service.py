from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from netconsole.models.ap_identity_index import ApIdentityBatchResult, ApIdentityMatch
from netconsole.repositories.online_mr_diagnosis_repository import (
    OnlineMrDiagnosisRepository,
)
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import normalize_mac_key


@dataclass(frozen=True)
class OnlineMrIdentityRemapResult:
    revision: int
    index_status: str
    mapping_status: str
    requested_count: int
    distinct_count: int
    matched_count: int
    unresolved_count: int
    ambiguous_count: int
    invalid_count: int
    updated_rows: int
    fact_fingerprint_before: str
    fact_fingerprint_after: str


class OnlineMrIdentityRemapService:
    def __init__(
        self,
        repository: OnlineMrDiagnosisRepository,
        query_service: ApIdentityQueryService,
    ) -> None:
        self.repository = repository
        self.query_service = query_service

    def remap(self, session_id: str) -> OnlineMrIdentityRemapResult:
        fact_fingerprint = self.repository.identity_fact_fingerprint(session_id)
        observations = self.repository.load_identity_observations(session_id)
        query_values = self._query_values(observations)
        batch = self.query_service.resolve_peer_macs(
            query_values,
            ap_role="trackside",
        )
        updates, matched_updated_rows = self._build_updates(
            session_id,
            observations,
            batch,
        )
        mapping_status = _mapping_status(batch)
        mapped_at = datetime.now().isoformat(sep=" ", timespec="milliseconds")
        result = self.repository.apply_identity_projection(
            session_id,
            updates,
            {
                "identity_index_revision": batch.revision,
                "identity_index_status": batch.index_status,
                "identity_mapped_at": mapped_at,
                "identity_mapping_status": mapping_status,
                "identity_requested_count": batch.requested_count,
                "identity_distinct_count": batch.distinct_count,
                "identity_matched_count": batch.matched_count,
                "identity_unresolved_count": batch.unresolved_count,
                "identity_ambiguous_count": batch.ambiguous_count,
                "identity_invalid_count": batch.invalid_count,
            },
            expected_fact_fingerprint=fact_fingerprint,
            matched_updated_rows=matched_updated_rows,
        )
        return OnlineMrIdentityRemapResult(
            revision=batch.revision,
            index_status=batch.index_status,
            mapping_status=mapping_status,
            requested_count=batch.requested_count,
            distinct_count=batch.distinct_count,
            matched_count=batch.matched_count,
            unresolved_count=batch.unresolved_count,
            ambiguous_count=batch.ambiguous_count,
            invalid_count=batch.invalid_count,
            updated_rows=int(result["updated_rows"]),
            fact_fingerprint_before=str(result["fact_fingerprint_before"]),
            fact_fingerprint_after=str(result["fact_fingerprint_after"]),
        )

    @staticmethod
    def _query_values(
        observations: Mapping[str, Sequence[Mapping[str, object]]],
    ) -> list[object]:
        candidates: list[object] = []
        for row in observations.get("main_link_samples", ()):
            peer_mac = row.get("peer_mac") or row.get("peer_mac_normalized") or ""
            candidates.append(peer_mac)
            bssid = row.get("bssid") or ""
            if bssid and normalize_mac_key(bssid) != normalize_mac_key(peer_mac):
                candidates.append(bssid)
        for dataset in ("switch_history_events", "switch_realtime_events"):
            for row in observations.get(dataset, ()):
                for prefix in ("old", "new"):
                    peer_name = str(row.get(f"{prefix}_peer_name") or "")
                    peer_mac = row.get(f"{prefix}_peer_mac") or ""
                    if _is_empty_link(peer_name, peer_mac):
                        continue
                    candidates.append(peer_mac)
        values: list[object] = []
        seen_valid: set[str] = set()
        seen_invalid: set[str] = set()
        for candidate in candidates:
            key = normalize_mac_key(candidate)
            if key is not None:
                if key not in seen_valid:
                    seen_valid.add(key)
                    values.append(key)
                continue
            invalid_key = str(candidate or "").strip().casefold()
            if invalid_key not in seen_invalid:
                seen_invalid.add(invalid_key)
                values.append(candidate)
        return values

    @staticmethod
    def _build_updates(
        session_id: str,
        observations: Mapping[str, Sequence[Mapping[str, object]]],
        batch: ApIdentityBatchResult,
    ) -> tuple[dict[str, list[tuple[object, ...]]], int]:
        updates: dict[str, list[tuple[object, ...]]] = {
            "main_link_samples": [],
            "switch_history_events": [],
            "switch_realtime_events": [],
        }
        matched_updated_rows = 0
        for row in observations.get("main_link_samples", ()):
            candidates = (
                row.get("peer_mac") or row.get("peer_mac_normalized") or "",
                row.get("bssid") or "",
            )
            match = _select_match(batch, candidates)
            projection = _projection(match)
            if match.matched:
                matched_updated_rows += 1
            resolved_name = (
                match.effective_ap_name
                if match.matched
                else str(row.get("peer_name") or row.get("peer_mac") or "")
            )
            updates["main_link_samples"].append(
                (
                    resolved_name,
                    projection["ap_mac"],
                    projection["ap_mac"],
                    projection["radio_mac"],
                    projection["entity_id"],
                    batch.revision,
                    batch.index_status,
                    projection["status"],
                    projection["source"],
                    projection["reason"],
                    projection["alias_type"],
                    projection["radio_id"],
                    projection["match_rule"],
                    projection["confidence"],
                    projection["station"],
                    projection["section"],
                    projection["belong_type"],
                    projection["source"] or projection["match_rule"],
                    int(row["id"]),
                    session_id,
                )
            )

        for dataset in ("switch_history_events", "switch_realtime_events"):
            for row in observations.get(dataset, ()):
                endpoint_values: list[object] = []
                for prefix in ("old", "new"):
                    peer_name = str(row.get(f"{prefix}_peer_name") or "")
                    peer_mac = row.get(f"{prefix}_peer_mac") or ""
                    if _is_empty_link(peer_name, peer_mac):
                        projection = _empty_projection(batch.revision)
                    else:
                        match = _select_match(batch, (peer_mac,))
                        projection = _projection(match)
                        if match.matched:
                            matched_updated_rows += 1
                    endpoint_values.extend(
                        (
                            projection["station"],
                            projection["section"],
                            projection["entity_id"],
                            batch.revision,
                            projection["status"],
                            projection["source"],
                            projection["reason"],
                            projection["alias_type"],
                            projection["ap_name"],
                            projection["ap_mac"],
                            projection["radio_id"],
                            projection["match_rule"],
                            projection["confidence"],
                        )
                    )
                updates[dataset].append((*endpoint_values, int(row["id"]), session_id))
        return updates, matched_updated_rows


def _select_match(
    batch: ApIdentityBatchResult,
    candidates: Sequence[object],
) -> ApIdentityMatch:
    matches: list[ApIdentityMatch] = []
    saw_invalid = False
    for candidate in candidates:
        key = normalize_mac_key(candidate)
        if key is None:
            saw_invalid = True
            continue
        match = batch.matches.get(key)
        if match is not None:
            matches.append(match)
    for status in ("matched", "ambiguous", "unresolved"):
        for match in matches:
            if match.status == status:
                return match
    reason = "invalid_peer_mac" if saw_invalid else "exact_alias_not_found"
    return ApIdentityMatch(
        status="invalid" if saw_invalid else "unresolved",
        identity_revision=batch.revision,
        unresolved_reason=reason,
    )


def _projection(match: ApIdentityMatch) -> dict[str, object]:
    matched = match.matched
    return {
        "entity_id": match.matched_entity_id if matched else "",
        "status": match.status,
        "source": match.matched_source if matched else "",
        "reason": match.unresolved_reason,
        "alias_type": match.matched_alias_type if matched else "",
        "ap_name": match.effective_ap_name if matched else "",
        "ap_mac": match.effective_ap_mac if matched else "",
        "radio_mac": match.query_mac if matched else "",
        "radio_id": match.radio_id if matched else None,
        "match_rule": match.match_rule if matched else "",
        "confidence": match.match_confidence if matched else 0,
        "station": (match.station or "-") if matched else "-",
        "section": (match.section or "-") if matched else "-",
        "belong_type": (match.belong_type or "unknown") if matched else "unknown",
    }


def _empty_projection(revision: int) -> dict[str, object]:
    return {
        "entity_id": "",
        "status": "empty",
        "source": "",
        "reason": "empty_link",
        "alias_type": "",
        "ap_name": "",
        "ap_mac": "",
        "radio_mac": "",
        "radio_id": None,
        "match_rule": "empty_link",
        "confidence": 0,
        "station": "-",
        "section": "-",
        "belong_type": "empty",
        "identity_revision": revision,
    }


def _is_empty_link(peer_name: object, peer_mac: object) -> bool:
    name = str(peer_name or "").strip().casefold()
    mac = str(peer_mac or "").strip().casefold()
    return name in {"空链路", "empty", "empty link"} or mac in {
        "0000-0000-0000",
        "00:00:00:00:00:00",
        "000000000000",
    }


def _mapping_status(batch: ApIdentityBatchResult) -> str:
    if batch.index_status != "ready":
        return "index_unavailable"
    if batch.ambiguous_count or batch.unresolved_count or batch.invalid_count:
        return "partial"
    return "mapped"


__all__ = ["OnlineMrIdentityRemapResult", "OnlineMrIdentityRemapService"]
