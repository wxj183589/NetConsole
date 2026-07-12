from __future__ import annotations

import re


TERMS = {
    "mesh link": "Mesh 链路",
    "interface": "接口",
    "neighbor": "邻居",
    "trap": "告警",
    "notification": "通知",
    "counter": "计数器",
    "octets": "字节数",
    "packets": "报文数",
    "discard": "丢弃",
    "status": "状态",
    "address": "地址",
    "table": "表",
    "entry": "表项",
    "index": "索引",
    "description": "描述",
    "system": "系统",
    "noise": "噪声",
    "duration": "持续时间",
    "peer": "对端",
    "local": "本端",
    "active": "活跃",
    "dormant": "休眠",
    "bytes": "字节",
    "broadcast": "广播",
    "multicast": "组播",
}


def translate_mib_description(text: str) -> str:
    if not text:
        return ""
    translated = text
    for term, chinese in sorted(TERMS.items(), key=lambda item: -len(item[0])):
        translated = re.sub(rf"\b{re.escape(term)}\b", chinese, translated, flags=re.IGNORECASE)
    translated = translated.replace("This object", "该对象")
    translated = translated.replace("This table", "该表")
    translated = translated.replace("describes", "描述")
    translated = translated.replace("indicates", "表示")
    return translated
