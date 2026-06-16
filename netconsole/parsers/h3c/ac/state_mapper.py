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


def map_fit_ap_state(state_raw: object) -> str:
    text = str(state_raw or "").strip().upper()
    if text in STATE_DISPLAY:
        return STATE_DISPLAY[text]
    if text.startswith("R/"):
        return "\u8fd0\u884c"
    return text or "-"
