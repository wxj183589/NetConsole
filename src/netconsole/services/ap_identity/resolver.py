from __future__ import annotations

from collections.abc import Callable, Sequence

from .models import (
    ApIdentityCandidate,
    ApMatchEvidence,
    ApMatchResult,
    ApMatchStatus,
    ApObservation,
    CanonicalApRadioIdentity,
)
from .normalizers import normalize_ap_name, normalize_identifier, normalize_mac, normalize_mileage


PEER_MAC_DUPLICATE_WARNING = "peer_mac 与 peer_radio_mac 规范化后重复"


class ApIdentityResolver:
    def resolve(
        self,
        observation: ApObservation,
        candidates: Sequence[ApIdentityCandidate],
    ) -> ApMatchResult:
        candidate_rows = tuple(candidates)
        base_evidence, warnings = _observation_warnings(observation)
        strategies = (
            self._match_ap_uuid,
            self._match_scoped_ap_id,
            self._match_scoped_ap_mac,
            self._match_ap_mac,
            self._match_radio_mac,
            self._match_bssid,
            self._match_peer_radio,
        )
        for strategy in strategies:
            matched, evidence = strategy(observation, candidate_rows)
            if not matched:
                continue
            return _result_for_matches(matched, (*base_evidence, *evidence), warnings, observation)

        return ApMatchResult(status=ApMatchStatus.UNRESOLVED, evidence=base_evidence, warnings=warnings)

    @staticmethod
    def _match_ap_uuid(observation: ApObservation, candidates: tuple[ApIdentityCandidate, ...]):
        value = _key(observation.ap_uuid)
        return _identity_matches(candidates, "ap_uuid", value, lambda item: _key(item.identity.ap_uuid), 100, "ap_uuid 精确匹配")

    @staticmethod
    def _match_scoped_ap_id(observation: ApObservation, candidates: tuple[ApIdentityCandidate, ...]):
        ac_uuid = _key(observation.ac_uuid)
        ap_id = _key(observation.ap_id)
        if not ac_uuid or not ap_id:
            return (), ()
        return _matches(
            candidates,
            "ac_uuid+ap_id",
            f"{ac_uuid}:{ap_id}",
            lambda item: f"{_key(item.identity.ac_uuid)}:{_key(item.identity.ap_id)}" if _key(item.identity.ac_uuid) and _key(item.identity.ap_id) else None,
            98,
            "AC 作用域内 APID 精确匹配",
        )

    @staticmethod
    def _match_scoped_ap_mac(observation: ApObservation, candidates: tuple[ApIdentityCandidate, ...]):
        ac_uuid = _key(observation.ac_uuid)
        ap_mac = normalize_mac(observation.ap_mac)
        if not ac_uuid or not ap_mac:
            return (), ()
        return _matches(
            candidates,
            "ac_uuid+ap_mac",
            f"{ac_uuid}:{ap_mac}",
            lambda item: f"{_key(item.identity.ac_uuid)}:{normalize_mac(item.identity.ap_mac)}" if _key(item.identity.ac_uuid) and normalize_mac(item.identity.ap_mac) else None,
            96,
            "AC 作用域内 AP MAC 精确匹配",
        )

    @staticmethod
    def _match_ap_mac(observation: ApObservation, candidates: tuple[ApIdentityCandidate, ...]):
        return _identity_matches(candidates, "ap_mac", normalize_mac(observation.ap_mac), lambda item: normalize_mac(item.identity.ap_mac), 92, "AP MAC 精确匹配")

    @staticmethod
    def _match_radio_mac(observation: ApObservation, candidates: tuple[ApIdentityCandidate, ...]):
        return _radio_matches(candidates, "radio_mac", normalize_mac(observation.radio_mac), lambda radio: (normalize_mac(radio.radio_mac),), 90, "显式 Radio MAC 映射")

    @staticmethod
    def _match_bssid(observation: ApObservation, candidates: tuple[ApIdentityCandidate, ...]):
        return _radio_matches(
            candidates,
            "bssid",
            normalize_mac(observation.bssid),
            lambda radio: (normalize_mac(radio.bssid), normalize_mac(radio.bbssid)),
            90,
            "显式 BSSID/BBSSID 映射",
        )

    @staticmethod
    def _match_peer_radio(observation: ApObservation, candidates: tuple[ApIdentityCandidate, ...]):
        for field, value in (("peer_radio_mac", observation.peer_radio_mac), ("peer_mac", observation.peer_mac)):
            normalized = normalize_mac(value)
            matched, evidence = _radio_matches(
                candidates,
                field,
                normalized,
                lambda radio: (normalize_mac(radio.radio_mac), normalize_mac(radio.bssid), normalize_mac(radio.bbssid)),
                80,
                "Peer observation 命中显式 Radio/BSSID 映射",
            )
            if matched:
                return matched, evidence
        return (), ()

def _result_for_matches(
    matches: tuple[ApIdentityCandidate, ...],
    evidence: tuple[ApMatchEvidence, ...],
    warnings: tuple[str, ...],
    observation: ApObservation,
) -> ApMatchResult:
    if len(matches) != 1:
        return ApMatchResult(status=ApMatchStatus.AMBIGUOUS, candidates=matches, evidence=evidence, warnings=warnings)
    candidate = matches[0]
    return ApMatchResult(
        status=ApMatchStatus.MATCHED,
        candidate=candidate,
        candidates=matches,
        evidence=(*evidence, *_location_evidence(observation, candidate)),
        warnings=warnings,
    )


def _identity_matches(
    candidates: tuple[ApIdentityCandidate, ...],
    field: str,
    observation_value: str | None,
    candidate_value: Callable[[ApIdentityCandidate], str | None],
    confidence: int,
    reason: str,
):
    return _matches(candidates, field, observation_value, candidate_value, confidence, reason)


def _radio_matches(
    candidates: tuple[ApIdentityCandidate, ...],
    field: str,
    observation_value: str | None,
    radio_values: Callable[[CanonicalApRadioIdentity], tuple[str | None, ...]],
    confidence: int,
    reason: str,
):
    if not observation_value:
        return (), ()
    matched = tuple(
        candidate
        for candidate in candidates
        if any(observation_value in {value for value in radio_values(radio) if value} for radio in candidate.radios)
    )
    evidence = tuple(
        ApMatchEvidence(field, observation_value, observation_value, confidence, reason)
        for _candidate in matched
    )
    return matched, evidence


def _matches(
    candidates: tuple[ApIdentityCandidate, ...],
    field: str,
    observation_value: str | None,
    candidate_value: Callable[[ApIdentityCandidate], str | None],
    confidence: int,
    reason: str,
):
    if not observation_value:
        return (), ()
    matched = tuple(candidate for candidate in candidates if candidate_value(candidate) == observation_value)
    evidence = tuple(
        ApMatchEvidence(field, observation_value, candidate_value(candidate) or "", confidence, reason)
        for candidate in matched
    )
    return matched, evidence


def _location_evidence(observation: ApObservation, candidate: ApIdentityCandidate) -> tuple[ApMatchEvidence, ...]:
    result: list[ApMatchEvidence] = []
    fields = (
        ("site", normalize_ap_name(observation.site), normalize_ap_name(candidate.location.site)),
        ("station", normalize_ap_name(observation.station), normalize_ap_name(candidate.location.station)),
        ("section", normalize_ap_name(observation.section), normalize_ap_name(candidate.location.section)),
        ("mileage", normalize_mileage(observation.mileage), normalize_mileage(candidate.location.mileage)),
    )
    for field, observed, expected in fields:
        if observed and expected and observed.casefold() == expected.casefold():
            result.append(ApMatchEvidence(field, observed, expected, 10, "位置字段仅作为辅助证据"))
    return tuple(result)


def _observation_warnings(observation: ApObservation) -> tuple[tuple[ApMatchEvidence, ...], tuple[str, ...]]:
    peer_mac = normalize_mac(observation.peer_mac)
    peer_radio_mac = normalize_mac(observation.peer_radio_mac)
    if not peer_mac or peer_mac != peer_radio_mac:
        return (), ()
    evidence = ApMatchEvidence(
        field="peer_mac+peer_radio_mac",
        observation_value=peer_mac,
        candidate_value=peer_radio_mac,
        confidence=0,
        reason="两个 observation 字段规范化后重复，仅记录提示",
    )
    return (evidence,), (PEER_MAC_DUPLICATE_WARNING,)


def _key(value: object) -> str | None:
    normalized = normalize_identifier(value)
    return normalized.casefold() if normalized else None
