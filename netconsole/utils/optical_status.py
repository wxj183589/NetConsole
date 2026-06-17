from __future__ import annotations


OPTICAL_STATUS_LABELS = {
    "zh": {
        "normal": "正常",
        "warning": "提示告警",
        "alarm": "一般告警",
        "link_abnormal": "链路异常",
        "no_light": "无光",
        "skipped": "未检查",
        "unknown": "未知",
    },
    "en": {
        "normal": "Normal",
        "warning": "Warning",
        "alarm": "Alarm",
        "link_abnormal": "Link Abnormal",
        "no_light": "No Light",
        "skipped": "Skipped",
        "unknown": "Unknown",
    },
}


def display_optical_status(status: object, language: str = "zh") -> str:
    raw = str(status or "unknown").strip()
    lang = "en" if str(language or "").lower().startswith("en") else "zh"
    return OPTICAL_STATUS_LABELS.get(lang, OPTICAL_STATUS_LABELS["zh"]).get(raw, raw or OPTICAL_STATUS_LABELS[lang]["unknown"])
