from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from netconsole.services.ap_identity import (
    ApIdentityCandidate,
    ApIdentityResolver,
    ApMatchResult,
    ApMatchStatus,
    ApObservation,
    candidate_from_extension_row,
    candidate_from_fit_ap_resource_row,
    is_mac_like,
    normalize_ap_name,
    normalize_mac,
)

from .ac_identity_models import AcApIdentityShadowItem, AcApIdentityShadowReport


OLD_MATCHED_STATUSES = {"matched_by_mac", "matched_by_name"}


@dataclass(frozen=True)
class _OldMatch:
    status: str
    match_key: str | None
    candidate_key: str | None

    @property
    def matched(self) -> bool:
        return self.status in OLD_MATCHED_STATUSES


class AcApIdentityAdapter:
    def __init__(self, resolver: ApIdentityResolver | None = None) -> None:
        self.resolver = resolver or ApIdentityResolver()

    def build_fit_ap_candidates(self, rows: Sequence[Mapping[str, object]]) -> tuple[ApIdentityCandidate, ...]:
        return tuple(candidate_from_fit_ap_resource_row(row) for row in rows)

    def build_extension_observations(self, rows: Sequence[Mapping[str, object]]) -> tuple[ApObservation, ...]:
        return tuple(self._observation_from_extension(row) for row in rows)

    def resolve_extension_to_fit_ap(
        self,
        extension_row: Mapping[str, object],
        candidates: Sequence[ApIdentityCandidate],
    ) -> ApMatchResult:
        return self.resolver.resolve(self._observation_from_extension(extension_row), candidates)

    def shadow_compare_extension_match(
        self,
        extension_rows: Sequence[Mapping[str, object]],
        fit_ap_rows: Sequence[Mapping[str, object]],
    ) -> AcApIdentityShadowReport:
        candidate_rows = self.build_fit_ap_candidates(fit_ap_rows)
        items: list[AcApIdentityShadowItem] = []
        for index, extension_row in enumerate(extension_rows, start=1):
            observation = self._observation_from_extension(extension_row)
            old_match = _old_match(extension_row, fit_ap_rows, candidate_rows)
            new_result = self.resolver.resolve(observation, candidate_rows)
            new_candidate_key = _candidate_key(new_result.candidate) if new_result.candidate else None
            identity_unchanged = bool(
                old_match.matched
                and new_result.status is ApMatchStatus.MATCHED
                and old_match.candidate_key
                and old_match.candidate_key == new_candidate_key
            )
            identity_changed = _identity_changed(old_match, new_result, new_candidate_key)
            warnings = [*new_result.warnings]
            if old_match.matched and new_result.status is ApMatchStatus.UNRESOLVED:
                warnings.append("旧逻辑已匹配，新 resolver 未解析")
            elif old_match.matched and new_result.status is ApMatchStatus.AMBIGUOUS:
                warnings.append("旧逻辑已匹配，新 resolver 返回歧义")
            elif not old_match.matched and new_result.status is ApMatchStatus.MATCHED:
                warnings.append("旧逻辑未匹配，新 resolver 发现候选；仅记录，不改变写入")
            if old_match.matched and identity_changed and new_result.status is ApMatchStatus.MATCHED:
                warnings.append("旧逻辑与新 resolver 的候选 identity 不一致")
            items.append(
                AcApIdentityShadowItem(
                    extension_ref=_extension_ref(extension_row, index),
                    old_status=old_match.status,
                    old_match_key=old_match.match_key,
                    new_status=new_result.status.value,
                    new_candidate_key=new_candidate_key,
                    identity_changed=identity_changed,
                    identity_unchanged=identity_unchanged,
                    name_only_match=old_match.status == "matched_by_name",
                    mac_like_name=is_mac_like(extension_row.get("ap_name")),
                    missing_ac_scope=not bool(observation.ac_uuid),
                    evidence=new_result.evidence,
                    warnings=tuple(dict.fromkeys(warnings)),
                )
            )
        return self.summarize_shadow_report(items)

    @staticmethod
    def summarize_shadow_report(items: Sequence[AcApIdentityShadowItem]) -> AcApIdentityShadowReport:
        rows = tuple(items)
        warnings = tuple(dict.fromkeys(warning for item in rows for warning in item.warnings))
        return AcApIdentityShadowReport(
            total=len(rows),
            matched=sum(item.new_status == ApMatchStatus.MATCHED.value for item in rows),
            unresolved=sum(item.new_status == ApMatchStatus.UNRESOLVED.value for item in rows),
            ambiguous=sum(item.new_status == ApMatchStatus.AMBIGUOUS.value for item in rows),
            identity_unchanged=sum(item.identity_unchanged for item in rows),
            identity_changed=sum(item.identity_changed for item in rows),
            name_only_matches=sum(item.name_only_match for item in rows),
            mac_like_names=sum(item.mac_like_name for item in rows),
            missing_ac_scope=sum(item.missing_ac_scope for item in rows),
            warnings=warnings,
            items=rows,
        )

    @staticmethod
    def _observation_from_extension(row: Mapping[str, object]) -> ApObservation:
        extension = candidate_from_extension_row(row)
        identity = extension.identity
        first_radio = extension.radios[0] if extension.radios else None
        return ApObservation(
            ap_uuid=identity.ap_uuid,
            ap_id=identity.ap_id,
            ap_mac=identity.ap_mac,
            ap_name=identity.ap_name,
            radio_mac=first_radio.radio_mac if first_radio else None,
            bssid=(first_radio.bssid or first_radio.bbssid) if first_radio else None,
            ac_uuid=identity.ac_uuid,
            site=extension.location.site,
            station=extension.location.station,
            section=extension.location.section,
            mileage=extension.location.mileage,
            source="ap_extension",
            source_ref=identity.source_ref,
            raw=row,
        )


def _old_match(
    extension_row: Mapping[str, object],
    fit_ap_rows: Sequence[Mapping[str, object]],
    candidates: Sequence[ApIdentityCandidate],
) -> _OldMatch:
    extension_mac = normalize_mac(extension_row.get("ap_mac_norm") or extension_row.get("ap_mac_display") or extension_row.get("ap_mac"))
    if extension_mac:
        indexes = [index for index, row in enumerate(fit_ap_rows) if normalize_mac(row.get("ap_mac")) == extension_mac]
        if indexes:
            candidate_key = _candidate_key(candidates[indexes[0]]) if len(indexes) == 1 else None
            return _OldMatch("matched_by_mac", f"mac:{extension_mac}", candidate_key)
        return _OldMatch("extension_not_online", f"mac:{extension_mac}", None)

    extension_name = str(extension_row.get("ap_name") or "").strip().casefold()
    if extension_name:
        indexes = [
            index
            for index, row in enumerate(fit_ap_rows)
            if str(row.get("ap_name") or "").strip().casefold() == extension_name
        ]
        if indexes:
            candidate_key = _candidate_key(candidates[indexes[0]]) if len(indexes) == 1 else None
            return _OldMatch("matched_by_name", f"name:{extension_name}", candidate_key)
    return _OldMatch("unbound_no_mac", None, None)


def _identity_changed(old_match: _OldMatch, new_result: ApMatchResult, new_candidate_key: str | None) -> bool:
    if old_match.matched != (new_result.status is ApMatchStatus.MATCHED):
        return True
    if old_match.matched and new_result.status is ApMatchStatus.MATCHED:
        return bool(old_match.candidate_key and new_candidate_key and old_match.candidate_key != new_candidate_key)
    return new_result.status is ApMatchStatus.AMBIGUOUS and old_match.matched


def _candidate_key(candidate: ApIdentityCandidate | None) -> str | None:
    if candidate is None:
        return None
    identity = candidate.identity
    if identity.ap_uuid:
        return f"uuid:{identity.ap_uuid.casefold()}"
    if identity.ac_uuid and identity.ap_id:
        return f"apid:{identity.ac_uuid.casefold()}:{identity.ap_id.casefold()}"
    ap_mac = normalize_mac(identity.ap_mac)
    if ap_mac:
        return f"mac:{ap_mac}"
    ap_name = normalize_ap_name(identity.ap_name)
    if identity.ac_uuid and ap_name:
        return f"name:{identity.ac_uuid.casefold()}:{ap_name.casefold()}"
    return f"name:{ap_name.casefold()}" if ap_name else None


def _extension_ref(row: Mapping[str, object], index: int) -> str:
    if row.get("id") not in (None, ""):
        return f"row:{row.get('id')}"
    source_parts = [str(row.get(key) or "").strip() for key in ("source_file", "source_sheet", "source_row")]
    if any(source_parts):
        return ":".join(part or "-" for part in source_parts)
    ap_mac = normalize_mac(row.get("ap_mac_norm") or row.get("ap_mac_display") or row.get("ap_mac"))
    if ap_mac:
        return f"mac:{ap_mac}"
    ap_name = normalize_ap_name(row.get("ap_name"))
    return f"name:{ap_name}" if ap_name else f"index:{index}"
