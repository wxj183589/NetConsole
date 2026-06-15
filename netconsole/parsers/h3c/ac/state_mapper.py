from __future__ import annotations


STATE_DISPLAY = {
    "I": "Idle",
    "J": "Join",
    "JA": "JoinAck",
    "IL": "ImageLoad",
    "C": "Config",
    "DC": "DataCheck",
    "R/M": "运行(主)",
    "R/B": "运行(备)",
}


def map_fit_ap_state(state_raw: object) -> str:
    text = str(state_raw or "").strip().upper()
    if text in STATE_DISPLAY:
        return STATE_DISPLAY[text]
    if text.startswith("R/"):
        return "运行"
    return text or "-"
