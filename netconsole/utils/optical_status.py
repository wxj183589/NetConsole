from __future__ import annotations


OPTICAL_STATUS_LABELS = {
    "zh": {
        "normal": "正常",
        "warning": "提示告警",
        "alarm": "一般告警",
        "link_abnormal": "链路异常",
        "link_down": "链路断开",
        "no_light": "无光",
        "skipped": "未检查",
        "not_collected": "未采集",
        "unknown": "未知",
    },
    "en": {
        "normal": "Normal",
        "warning": "Warning",
        "alarm": "Alarm",
        "link_abnormal": "Link Abnormal",
        "link_down": "Link Down",
        "no_light": "No Light",
        "skipped": "Skipped",
        "not_collected": "Not Collected",
        "unknown": "Unknown",
    },
}


def display_optical_status(status: object, language: str = "zh") -> str:
    raw = str(status or "unknown").strip()
    lang = "en" if str(language or "").lower().startswith("en") else "zh"
    return OPTICAL_STATUS_LABELS.get(lang, OPTICAL_STATUS_LABELS["zh"]).get(raw, raw or OPTICAL_STATUS_LABELS[lang]["unknown"])
