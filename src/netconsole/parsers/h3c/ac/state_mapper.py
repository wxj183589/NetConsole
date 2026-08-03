from __future__ import annotations


STATE_DISPLAY = {
    "I": "Idle",
    "J": "Join",
    "JA": "JoinAck",
    "IL": "ImageLoad",
    "C": "Config",
    "DC": "DataCheck",
    "R": "Run",
    "R/M": "\u8fd0\u884c(\u4e3b)",
    "R/B": "\u8fd0\u884c(\u5907)",
}
FIT_AP_RUNNING_STATE_TOKENS = frozenset({"R/M", "R/B"})
FIT_AP_RUNNING_STATE_DISPLAYS = frozenset(
    str(STATE_DISPLAY[token]).casefold() for token in FIT_AP_RUNNING_STATE_TOKENS
)


def normalize_fit_ap_state_token(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split("=", 1)[0].strip().upper()


def classify_fit_ap_state(*values: object) -> str:
    """Classify explicit H3C FIT-AP state evidence for business consumers."""

    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        token = normalize_fit_ap_state_token(text)
        if (
            token in FIT_AP_RUNNING_STATE_TOKENS
            or text.casefold() in FIT_AP_RUNNING_STATE_DISPLAYS
        ):
            return "online"
        return "offline"
    return "unknown"


def map_fit_ap_state(state_raw: object) -> str:
    text = normalize_fit_ap_state_token(state_raw)
    if text in STATE_DISPLAY:
        return STATE_DISPLAY[text]
    if text.startswith("R/"):
        return "\u8fd0\u884c"
    return text or "-"
