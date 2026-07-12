from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass

from netconsole.services.ap_identity import (
    ApIdentityCandidate,
    ApIdentityResolver,
    ApMatchEvidence,
    ApMatchStatus,
    ApObservation,
    candidate_from_ap_entity_row,
    candidate_from_extension_row,
    candidate_from_fit_ap_resource_row,
    is_mac_like,
    normalize_ap_name,
    normalize_mac,
    observation_from_mesh_peer,
    observation_from_online_mr_sample,
)


_OBSERVATION_FIELDS = frozenset(
    {
        "peer_mac",
        "peer_radio_mac",
        "peer_name",
        "peer_ap_mac",
        "ap_mac",
        "ap_name",
        "radio_mac",
        "bssid",
        "bbssid",
        "ac_uuid",
        "device_uuid",
        "station",
        "section",
        "mileage",
        "source",
    }
)


@dataclass(frozen=True)
class MrMeshIdentityShadowItem:
    record_ref: str
    record_type: str
    old_peer_key: str | None
    old_ap_key: str | None
    peer_mac: str | None
    peer_radio_mac: str | None
    peer_name: str | None
    old_ap_mac: str | None
    old_ap_name: str | None
    new_status: str
    new_candidate_key: str | None
    identity_unchanged: bool
    identity_changed: bool
    peer_mac_equals_peer_radio_mac: bool
    peer_mac_equals_ap_mac: bool
    radio_or_bssid_only: bool
    name_only_match: bool
    mac_like_name: bool
    missing_ac_scope: bool
    duplicate_mac_fields: bool
    evidence: tuple[ApMatchEvidence, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evidence"] = [asdict(item) for item in self.evidence]
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class MrMeshIdentityShadowReport:
    available: bool = True
    total: int = 0
    matched: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    identity_unchanged: int = 0
    identity_changed: int = 0
    peer_mac_equals_peer_radio_mac: int = 0
    peer_mac_equals_ap_mac: int = 0
    radio_or_bssid_only_records: int = 0
    name_only_matches: int = 0
    mac_like_names: int = 0
    missing_ac_scope: int = 0
    duplicate_mac_field_records: int = 0
    warnings: tuple[str, ...] = ()
    items: tuple[MrMeshIdentityShadowItem, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "available": self.available,
            "total": self.total,
            "matched": self.matched,
            "unresolved": self.unresolved,
            "ambiguous": self.ambiguous,
            "identity_unchanged": self.identity_unchanged,
            "identity_changed": self.identity_changed,
            "peer_mac_equals_peer_radio_mac": self.peer_mac_equals_peer_radio_mac,
            "peer_mac_equals_ap_mac": self.peer_mac_equals_ap_mac,
            "radio_or_bssid_only_records": self.radio_or_bssid_only_records,
            "name_only_matches": self.name_only_matches,
            "mac_like_names": self.mac_like_names,
            "missing_ac_scope": self.missing_ac_scope,
            "duplicate_mac_field_records": self.duplicate_mac_field_records,
            "warnings": list(self.warnings),
            "items": [item.to_payload() for item in self.items],
        }


class MrMeshIdentityShadowService:
    def __init__(self, resolver: ApIdentityResolver | None = None) -> None:
        self.resolver = resolver or ApIdentityResolver()

    def build_candidates_from_fit_ap_resources(
        self,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[ApIdentityCandidate, ...]:
        return _build_candidates(rows, candidate_from_fit_ap_resource_row)

    def build_candidates_from_ap_entities(
        self,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[ApIdentityCandidate, ...]:
        return _build_candidates(rows, candidate_from_ap_entity_row)

    def build_candidates_from_ap_extensions(
        self,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[ApIdentityCandidate, ...]:
        return _build_candidates(rows, candidate_from_extension_row)

    def build_candidates(
        self,
        fit_ap_resources: Sequence[Mapping[str, object]] = (),
        ap_entities: Sequence[Mapping[str, object]] = (),
        ap_extensions: Sequence[Mapping[str, object]] = (),
    ) -> tuple[ApIdentityCandidate, ...]:
        candidates = (
            *self.build_candidates_from_fit_ap_resources(fit_ap_resources),
            *self.build_candidates_from_ap_entities(ap_entities),
            *self.build_candidates_from_ap_extensions(ap_extensions),
        )
        result: list[ApIdentityCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = _candidate_dedup_key(candidate)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            result.append(candidate)
        return tuple(result)

    def build_observation_from_mesh_link(self, row: Mapping[str, object]) -> ApObservation:
        return observation_from_mesh_peer(_observation_row(row))

    def build_observation_from_online_mr_summary(self, row: Mapping[str, object]) -> ApObservation:
        return observation_from_online_mr_sample(_observation_row(row))

    def build_observation_from_vehicle_mr_mapping(self, row: Mapping[str, object]) -> ApObservation:
        return observation_from_mesh_peer(_observation_row(row))

    def shadow_mesh_import_result(
        self,
        old_result: Mapping[str, object],
        candidates: Sequence[ApIdentityCandidate],
        rows: Sequence[Mapping[str, object]],
    ) -> MrMeshIdentityShadowReport:
        del old_result
        return self._shadow_rows("offline_mesh", rows, candidates, self.build_observation_from_mesh_link)

    def shadow_online_mr_parse_result(
        self,
        old_result: Mapping[str, object],
        candidates: Sequence[ApIdentityCandidate],
        rows: Sequence[Mapping[str, object]],
    ) -> MrMeshIdentityShadowReport:
        del old_result
        return self._shadow_rows("online_mr", rows, candidates, self.build_observation_from_online_mr_summary)

    def shadow_vehicle_mr_mapping_result(
        self,
        old_result: Mapping[str, object],
        candidates: Sequence[ApIdentityCandidate],
    ) -> MrMeshIdentityShadowReport:
        rows: list[dict[str, object]] = []
        for index, mapping in enumerate(old_result.get("mappings") or (), start=1):
            if not isinstance(mapping, Mapping):
                continue
            for field, car_end in (("tc1_peer_name", "TC1"), ("tc2_peer_name", "TC2")):
                peer_name = str(mapping.get(field) or "").strip()
                if not peer_name:
                    continue
                rows.append(
                    {
                        "peer_name": peer_name,
                        "source_ref": f"mapping:{index}:{car_end}",
                        "source": "vehicle_mr_mapping",
                        "vehicle_mr_car_end": car_end,
                    }
                )
        return self._shadow_rows("vehicle_mr", rows, candidates, self.build_observation_from_vehicle_mr_mapping)

    def _shadow_rows(
        self,
        record_type: str,
        rows: Sequence[Mapping[str, object]],
        candidates: Sequence[ApIdentityCandidate],
        observation_builder: Callable[[Mapping[str, object]], ApObservation],
    ) -> MrMeshIdentityShadowReport:
        items = tuple(
            self._shadow_item(record_type, row, index, candidates, observation_builder)
            for index, row in enumerate(rows, start=1)
        )
        return self.summarize_report(items)

    def _shadow_item(
        self,
        record_type: str,
        row: Mapping[str, object],
        index: int,
        candidates: Sequence[ApIdentityCandidate],
        observation_builder: Callable[[Mapping[str, object]], ApObservation],
    ) -> MrMeshIdentityShadowItem:
        normalized = _normalized_row(row)
        observation = observation_builder(normalized)
        result = self.resolver.resolve(observation, candidates)
        has_old_binding = _has_old_ap_binding(normalized)
        identity_unchanged = bool(
            has_old_binding
            and result.status is ApMatchStatus.MATCHED
            and result.candidate is not None
            and _old_binding_matches_candidate(normalized, result.candidate)
        )
        identity_changed = bool(
            (has_old_binding and not identity_unchanged)
            or (not has_old_binding and result.status is ApMatchStatus.MATCHED)
        )
        peer_mac = normalize_mac(observation.peer_mac)
        peer_radio_mac = normalize_mac(observation.peer_radio_mac)
        old_ap_mac = _old_ap_mac(normalized)
        peer_equals_radio = bool(peer_mac and peer_mac == peer_radio_mac)
        peer_equals_ap = bool(peer_mac and peer_mac == old_ap_mac)
        warnings = [*result.warnings]
        if peer_equals_ap:
            warnings.append("peer_mac 与旧 AP MAC 规范化后重复；仅记录，不改值")
        if record_type == "vehicle_mr":
            warnings.append("Vehicle MR mapping 的 Peer Name 是车端映射字段，仅作低置信 observation")
        if has_old_binding and result.status is ApMatchStatus.UNRESOLVED:
            warnings.append("旧逻辑已有 AP 映射，新 resolver 未解析")
        elif has_old_binding and result.status is ApMatchStatus.AMBIGUOUS:
            warnings.append("旧逻辑已有 AP 映射，新 resolver 返回歧义")
        elif not has_old_binding and result.status is ApMatchStatus.MATCHED:
            warnings.append("旧逻辑未绑定 AP，新 resolver 发现候选；仅记录，不写入")
        elif identity_changed and result.status is ApMatchStatus.MATCHED:
            warnings.append("旧 AP 映射与新 resolver 候选不一致")
        return MrMeshIdentityShadowItem(
            record_ref=_record_ref(normalized, record_type, index),
            record_type=record_type,
            old_peer_key=_old_peer_key(normalized),
            old_ap_key=_old_ap_key(normalized),
            peer_mac=peer_mac,
            peer_radio_mac=peer_radio_mac,
            peer_name=normalize_ap_name(normalized.get("peer_name")),
            old_ap_mac=old_ap_mac,
            old_ap_name=_old_ap_name(normalized),
            new_status=result.status.value,
            new_candidate_key=_candidate_key(result.candidate),
            identity_unchanged=identity_unchanged,
            identity_changed=identity_changed,
            peer_mac_equals_peer_radio_mac=peer_equals_radio,
            peer_mac_equals_ap_mac=peer_equals_ap,
            radio_or_bssid_only=_is_radio_or_bssid_only(observation),
            name_only_match=_is_name_only_match(observation, result.status),
            mac_like_name=is_mac_like(normalized.get("peer_name") or normalized.get("ap_name")),
            missing_ac_scope=not bool(observation.ac_uuid),
            duplicate_mac_fields=peer_equals_radio or peer_equals_ap,
            evidence=result.evidence,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def summarize_report(items: Sequence[MrMeshIdentityShadowItem]) -> MrMeshIdentityShadowReport:
        rows = tuple(items)
        return MrMeshIdentityShadowReport(
            total=len(rows),
            matched=sum(item.new_status == ApMatchStatus.MATCHED.value for item in rows),
            unresolved=sum(item.new_status == ApMatchStatus.UNRESOLVED.value for item in rows),
            ambiguous=sum(item.new_status == ApMatchStatus.AMBIGUOUS.value for item in rows),
            identity_unchanged=sum(item.identity_unchanged for item in rows),
            identity_changed=sum(item.identity_changed for item in rows),
            peer_mac_equals_peer_radio_mac=sum(item.peer_mac_equals_peer_radio_mac for item in rows),
            peer_mac_equals_ap_mac=sum(item.peer_mac_equals_ap_mac for item in rows),
            radio_or_bssid_only_records=sum(item.radio_or_bssid_only for item in rows),
            name_only_matches=sum(item.name_only_match for item in rows),
            mac_like_names=sum(item.mac_like_name for item in rows),
            missing_ac_scope=sum(item.missing_ac_scope for item in rows),
            duplicate_mac_field_records=sum(item.duplicate_mac_fields for item in rows),
            warnings=tuple(dict.fromkeys(warning for item in rows for warning in item.warnings)),
            items=rows,
        )


def unavailable_mr_mesh_identity_shadow(total: int, exc: Exception) -> dict[str, object]:
    return MrMeshIdentityShadowReport(
        available=False,
        total=total,
        warnings=(f"MR/Mesh identity shadow 不可用：{type(exc).__name__}: {exc}",),
    ).to_payload()


def _build_candidates(
    rows: Sequence[Mapping[str, object]],
    builder: Callable[[Mapping[str, object]], ApIdentityCandidate],
) -> tuple[ApIdentityCandidate, ...]:
    return tuple(builder(_normalized_row(row)) for row in rows)


def _normalized_row(row: Mapping[str, object]) -> dict[str, object]:
    result = dict(row)
    for key, value in tuple(result.items()):
        key_text = str(key).casefold()
        if "mac" not in key_text and "bssid" not in key_text:
            continue
        normalized = _normalize_mr_mesh_mac(value)
        if normalized:
            result[key] = normalized
    return result


def _observation_row(row: Mapping[str, object]) -> dict[str, object]:
    normalized = _normalized_row(row)
    return {key: value for key, value in normalized.items() if key in _OBSERVATION_FIELDS}


def _normalize_mr_mesh_mac(value: object) -> str | None:
    normalized = normalize_mac(value)
    if normalized:
        return normalized
    text = str(value or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}", text):
        return normalize_mac(text.replace("-", ""))
    return None


def _candidate_dedup_key(candidate: ApIdentityCandidate) -> str | None:
    identity = candidate.identity
    if identity.ap_uuid:
        return f"uuid:{identity.ap_uuid.casefold()}"
    mac = normalize_mac(identity.ap_mac)
    if mac:
        scope = identity.ac_uuid.casefold() if identity.ac_uuid else ""
        return f"mac:{scope}:{mac}"
    if identity.ac_uuid and identity.ap_id:
        return f"apid:{identity.ac_uuid.casefold()}:{identity.ap_id.casefold()}"
    name = normalize_ap_name(identity.ap_name)
    if name:
        scope = identity.ac_uuid.casefold() if identity.ac_uuid else ""
        return f"name:{scope}:{name.casefold()}"
    return None


def _candidate_key(candidate: ApIdentityCandidate | None) -> str | None:
    return _candidate_dedup_key(candidate) if candidate is not None else None


def _has_old_ap_binding(row: Mapping[str, object]) -> bool:
    if row.get("ap_uuid") or _old_ap_mac(row) or row.get("peer_ap_name") or row.get("ap_name"):
        return True
    source = str(row.get("belonging_source") or row.get("peer_resolve_source") or row.get("match_rule") or "").strip().casefold()
    return bool(_old_ap_name(row) and source and source != "unresolved")


def _old_ap_mac(row: Mapping[str, object]) -> str | None:
    return _normalize_mr_mesh_mac(row.get("peer_ap_mac") or row.get("ap_mac"))


def _old_ap_name(row: Mapping[str, object]) -> str | None:
    explicit = normalize_ap_name(row.get("peer_ap_name") or row.get("ap_name"))
    if explicit:
        return explicit
    source = str(row.get("belonging_source") or row.get("peer_resolve_source") or row.get("match_rule") or "").strip().casefold()
    if source and source != "unresolved":
        return normalize_ap_name(row.get("resolved_peer_name"))
    return None


def _old_ap_key(row: Mapping[str, object]) -> str | None:
    if not _has_old_ap_binding(row):
        return None
    ap_uuid = str(row.get("ap_uuid") or "").strip()
    if ap_uuid:
        return f"uuid:{ap_uuid.casefold()}"
    ap_mac = _old_ap_mac(row)
    if ap_mac:
        return f"mac:{ap_mac}"
    ap_name = _old_ap_name(row)
    return f"name:{ap_name.casefold()}" if ap_name else None


def _old_peer_key(row: Mapping[str, object]) -> str | None:
    peer_mac = _normalize_mr_mesh_mac(row.get("peer_mac") or row.get("peer_mac_normalized") or row.get("peer_mac_raw"))
    if peer_mac:
        return f"peer:{peer_mac}"
    peer_radio = _normalize_mr_mesh_mac(row.get("peer_radio_mac") or row.get("radio_mac") or row.get("bssid"))
    if peer_radio:
        return f"radio:{peer_radio}"
    peer_name = normalize_ap_name(row.get("peer_name"))
    return f"name:{peer_name.casefold()}" if peer_name else None


def _old_binding_matches_candidate(row: Mapping[str, object], candidate: ApIdentityCandidate) -> bool:
    identity = candidate.identity
    ap_uuid = str(row.get("ap_uuid") or "").strip()
    if ap_uuid:
        return ap_uuid.casefold() == str(identity.ap_uuid or "").casefold()
    ap_mac = _old_ap_mac(row)
    if ap_mac:
        return ap_mac == normalize_mac(identity.ap_mac)
    ap_name = _old_ap_name(row)
    if ap_name:
        return ap_name.casefold() == str(identity.ap_name or "").strip().casefold()
    return False


def _is_radio_or_bssid_only(observation: ApObservation) -> bool:
    return bool(
        any((observation.peer_radio_mac, observation.radio_mac, observation.bssid))
        and not any((observation.ap_uuid, observation.ap_id, observation.ap_mac, observation.ap_name, observation.peer_mac))
    )


def _is_name_only_match(observation: ApObservation, status: ApMatchStatus) -> bool:
    return bool(
        status is ApMatchStatus.MATCHED
        and observation.ap_name
        and not any(
            (
                observation.ap_uuid,
                observation.ap_id,
                observation.ap_mac,
                observation.peer_mac,
                observation.peer_radio_mac,
                observation.radio_mac,
                observation.bssid,
            )
        )
    )


def _record_ref(row: Mapping[str, object], record_type: str, index: int) -> str:
    explicit = str(row.get("source_ref") or row.get("id") or "").strip()
    if explicit:
        return explicit
    peer = _old_peer_key(row)
    return f"{record_type}:{peer or index}"
