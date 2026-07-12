from __future__ import annotations

import re


class MacAddressError(ValueError):
    pass


class H3cMacDeriveError(ValueError):
    pass


def mac_to_hex12(mac: str) -> str:
    text = re.sub(r"[^0-9a-fA-F]", "", str(mac or ""))
    if len(text) != 12 or not re.fullmatch(r"[0-9a-fA-F]{12}", text):
        raise MacAddressError("MAC格式无效")
    return text.upper()


def format_mac(hex12: str) -> str:
    value = mac_to_hex12(hex12)
    return ":".join(value[index : index + 2] for index in range(0, 12, 2))


def normalize_mac(mac: str) -> str:
    return format_mac(mac_to_hex12(mac))


def derive_h3c_r1_mac(physical_mac: str) -> str:
    chars = list(mac_to_hex12(physical_mac))
    chars[-1] = "F"
    return format_mac("".join(chars))


def derive_h3c_r2_mac(physical_mac: str) -> str:
    chars = list(mac_to_hex12(physical_mac))
    if chars[-2] == "F":
        raise H3cMacDeriveError("R2推导失败：倒数第二位为F，无法按单字符+1生成")
    chars[-2] = f"{int(chars[-2], 16) + 1:X}"
    chars[-1] = "F"
    return format_mac("".join(chars))
