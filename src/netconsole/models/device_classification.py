from __future__ import annotations

from dataclasses import dataclass


CATALOG_VERSION = "smarthub-device-v1.0.9-r6"
UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True)
class Classification:
    vendor_code: str = ""
    vendor_label: str = ""
    category_code: str = UNCLASSIFIED
    category_label: str = "未分类"
    subcategory_code: str = UNCLASSIFIED
    subcategory_label: str = "未分类"
    device_role: str = ""


VENDOR_LABELS = {
    "H3C": "新华三",
    "HUAWEI": "华为",
    "CISCO": "思科",
    "DPTECH": "迪普",
    "RUIJIE": "锐捷",
    "F5": "F5",
    "HPE": "惠普",
    "DELL": "戴尔",
    "LENOVO": "联想",
    "INSPUR": "浪潮",
    "IBM": "IBM",
    "UNIS": "紫光",
    "SUGON": "曙光",
    "ZTE": "中兴",
    "BROCADE": "博科",
    "JUNIPER": "Juniper",
    "HILLSTONE": "山石网科",
    "ORACLE": "Oracle",
    "XFUSION": "超聚变",
    "OTHER": "其他",
}

CATEGORY_LABELS = {
    "NETWORK": "网络设备",
    "SERVER": "服务器",
    "STORAGE": "存储",
    "CLOUD_SOFTWARE": "云智软件产品",
    "SOLUTION": "解决方案",
    "BUSINESS_SOFTWARE": "业务软件产品",
    "OS": "操作系统",
    "MVS_DATA": "数据库",
    UNCLASSIFIED: "未分类",
}

SUBCATEGORY_LABELS = {
    "ROUTER": "路由器",
    "SWITCH": "交换机",
    "WIRELESS": "无线",
    "SECURITY": "安全",
    "LOAD_BALANCER": "负载均衡",
    "H3C_SERVER": "H3C 服务器",
    "HPE_SERVER": "HPE 服务器",
    "MVS_SERVER": "通用服务器",
    "THREE_PAR": "3PAR",
    "SAN": "SAN",
    "ONESTOR": "ONEStor",
    "X10000": "X10000",
    "CAS": "CAS",
    "VDI": "VDI",
    "UIS": "UIS",
    "CLOUDOS": "CloudOS",
    "DATAENGINE": "DataEngine",
    "DBAAS": "DBaaS",
    "ADDC": "AD-DC",
    "ADCAMPUS": "AD-Campus",
    "ADWAN": "AD-WAN",
    "SDWAN": "SD-WAN",
    "UC": "UC",
    "LINUX": "Linux",
    "MVS_DB_MYSQL": "MySQL",
    "MVS_DB_ORACLE": "Oracle",
    UNCLASSIFIED: "未分类",
}

# Collapsed from SmartHub device-v1.0.9 device_type_protocol_template. Protocol
# duplicates are intentionally removed; the order follows the shipped seed.
SMART_HUB_CATALOG: dict[str, dict[str, tuple[str, ...]]] = {
    "H3C": {
        "NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY"),
        "SERVER": ("H3C_SERVER",),
        "STORAGE": ("THREE_PAR", "SAN", "ONESTOR", "X10000"),
        "CLOUD_SOFTWARE": ("CAS", "VDI", "UIS", "CLOUDOS", "DATAENGINE", "DBAAS"),
        "SOLUTION": ("ADDC", "ADCAMPUS", "ADWAN", "SDWAN"),
        "BUSINESS_SOFTWARE": ("UC",),
    },
    "HUAWEI": {
        "NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY"),
        "SERVER": ("MVS_SERVER",),
    },
    "CISCO": {
        "NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY"),
        "SERVER": ("MVS_SERVER",),
    },
    "DPTECH": {"NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY")},
    "RUIJIE": {"NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY")},
    "F5": {"NETWORK": ("LOAD_BALANCER",)},
    "HPE": {"SERVER": ("HPE_SERVER",), "STORAGE": ("THREE_PAR", "SAN")},
    "DELL": {
        "SERVER": ("MVS_SERVER",),
        "NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY"),
    },
    "LENOVO": {"SERVER": ("MVS_SERVER",)},
    "INSPUR": {"SERVER": ("MVS_SERVER",)},
    "IBM": {"SERVER": ("MVS_SERVER",)},
    "UNIS": {"SERVER": ("MVS_SERVER",)},
    "SUGON": {"SERVER": ("MVS_SERVER",)},
    "ZTE": {
        "SERVER": ("MVS_SERVER",),
        "NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY"),
    },
    "BROCADE": {"STORAGE": ("THREE_PAR", "SAN")},
    "JUNIPER": {"NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY")},
    "HILLSTONE": {"NETWORK": ("ROUTER", "SWITCH", "WIRELESS", "SECURITY")},
    "ORACLE": {"MVS_DATA": ("MVS_DB_MYSQL", "MVS_DB_ORACLE")},
    "XFUSION": {"SERVER": ("MVS_SERVER",)},
    "OTHER": {"OS": ("LINUX",)},
}

_VENDOR_ALIASES = {
    "h3c": "H3C",
    "新华三": "H3C",
    "新华三h3c": "H3C",
    "huawei": "HUAWEI",
    "华为": "HUAWEI",
    "cisco": "CISCO",
    "思科": "CISCO",
    "dptech": "DPTECH",
    "迪普": "DPTECH",
    "ruijie": "RUIJIE",
    "锐捷": "RUIJIE",
    "f5": "F5",
    "hpe": "HPE",
    "hp": "HPE",
    "惠普": "HPE",
    "dell": "DELL",
    "戴尔": "DELL",
    "lenovo": "LENOVO",
    "联想": "LENOVO",
    "inspur": "INSPUR",
    "浪潮": "INSPUR",
    "ibm": "IBM",
    "unis": "UNIS",
    "紫光": "UNIS",
    "sugon": "SUGON",
    "曙光": "SUGON",
    "zte": "ZTE",
    "中兴": "ZTE",
    "中兴通讯": "ZTE",
    "brocade": "BROCADE",
    "博科": "BROCADE",
    "juniper": "JUNIPER",
    "hillstone": "HILLSTONE",
    "山石": "HILLSTONE",
    "山石网科": "HILLSTONE",
    "oracle": "ORACLE",
    "xfusion": "XFUSION",
    "超聚变": "XFUSION",
    "other": "OTHER",
    "其他": "OTHER",
}

PREFERRED_VENDOR_VALUES = {
    "H3C": "H3C",
    "HUAWEI": "Huawei",
    "CISCO": "Cisco",
    "RUIJIE": "Ruijie",
    "ZTE": "ZTE",
    "OTHER": "Other",
}

ROLE_TO_SUBCATEGORY = {
    "AC": ("NETWORK", "WIRELESS"),
    "Cloud-AP": ("NETWORK", "WIRELESS"),
    "FAT-AP": ("NETWORK", "WIRELESS"),
    "MR": ("NETWORK", "WIRELESS"),
    "SW": ("NETWORK", "SWITCH"),
    "FW": ("NETWORK", "SECURITY"),
    "Route": ("NETWORK", "ROUTER"),
}

SUBCATEGORY_TO_ROLES = {
    "ROUTER": ("Route",),
    "SWITCH": ("SW",),
    "WIRELESS": ("AC", "Cloud-AP", "FAT-AP", "MR"),
    "SECURITY": ("FW",),
}


def canonical_vendor_code(value: object) -> str:
    text = "".join(str(value or "").strip().split()).casefold()
    return _VENDOR_ALIASES.get(text, "")


def vendor_label(value: object) -> str:
    code = canonical_vendor_code(value)
    return VENDOR_LABELS.get(code, str(value or "").strip() or "未分类")


def normalize_category_code(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    code = text.upper()
    if code in CATEGORY_LABELS:
        return code
    for candidate, label in CATEGORY_LABELS.items():
        if text == label:
            return candidate
    raise ValueError(f"不支持的设备大类：{text}")


def normalize_subcategory_code(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    code = text.upper()
    if code in SUBCATEGORY_LABELS:
        return code
    for candidate, label in SUBCATEGORY_LABELS.items():
        if text.casefold() == label.casefold():
            return candidate
    raise ValueError(f"不支持的设备子类：{text}")


def classify_device(vendor: object, device_role: object) -> Classification:
    role = str(device_role or "").strip()
    vendor_code = canonical_vendor_code(vendor)
    mapped = ROLE_TO_SUBCATEGORY.get(role)
    if not vendor_code or mapped is None:
        return Classification(
            vendor_code=vendor_code,
            vendor_label=vendor_label(vendor),
            device_role=role,
        )
    category, subcategory = mapped
    if subcategory not in SMART_HUB_CATALOG.get(vendor_code, {}).get(category, ()):
        return Classification(
            vendor_code=vendor_code,
            vendor_label=vendor_label(vendor),
            device_role=role,
        )
    return Classification(
        vendor_code=vendor_code,
        vendor_label=VENDOR_LABELS[vendor_code],
        category_code=category,
        category_label=CATEGORY_LABELS[category],
        subcategory_code=subcategory,
        subcategory_label=SUBCATEGORY_LABELS[subcategory],
        device_role=role,
    )


def writable_roles(vendor: object, category: object, subcategory: object) -> tuple[str, ...]:
    vendor_code = canonical_vendor_code(vendor)
    category_code = str(category or "").strip().upper()
    subcategory_code = str(subcategory or "").strip().upper()
    if subcategory_code not in SMART_HUB_CATALOG.get(vendor_code, {}).get(category_code, ()):
        return ()
    return SUBCATEGORY_TO_ROLES.get(subcategory_code, ())


def validate_classification_selection(
    vendor: object,
    category: object,
    subcategory: object,
    device_role: object,
) -> None:
    category_code = str(category or "").strip().upper()
    subcategory_code = str(subcategory or "").strip().upper()
    if not category_code and not subcategory_code:
        return
    if not category_code or not subcategory_code:
        raise ValueError("设备大类和设备子类必须同时选择")
    if category_code == UNCLASSIFIED and subcategory_code == UNCLASSIFIED:
        classification = classify_device(vendor, device_role)
        if (
            classification.category_code == UNCLASSIFIED
            and classification.subcategory_code == UNCLASSIFIED
        ):
            return
        raise ValueError("已适配设备不能标记为未分类")
    roles = writable_roles(vendor, category_code, subcategory_code)
    if not roles:
        raise ValueError("该 SmartHub 分类当前无法无损写入 NetConsole 业务角色")
    role = str(device_role or "").strip()
    if role not in roles:
        raise ValueError("设备分类与设备角色不一致")


def matches_classification_filters(
    vendor: object,
    device_role: object,
    categories: object = None,
    subcategories: object = None,
) -> bool:
    selected_categories = _normalize_filter_values(categories, "设备大类")
    selected_subcategories = _normalize_filter_values(subcategories, "设备子类")
    classification = classify_device(vendor, device_role)
    if selected_categories and classification.category_code not in selected_categories:
        return False
    if selected_subcategories and classification.subcategory_code not in selected_subcategories:
        return False
    return True


def _normalize_filter_values(values: object, label: str) -> set[str]:
    if values is None:
        return set()
    if not isinstance(values, (list, tuple)) or len(values) > 100:
        raise ValueError(f"{label}筛选最多支持 100 个值")
    selected = {
        str(value).strip().upper()
        for value in values
        if isinstance(value, str) and str(value).strip()
    }
    allowed = (
        set(CATEGORY_LABELS)
        if label == "设备大类"
        else set(SUBCATEGORY_LABELS)
    )
    unknown = selected - allowed
    if unknown:
        raise ValueError(f"不支持的{label}：{', '.join(sorted(unknown))}")
    return selected
