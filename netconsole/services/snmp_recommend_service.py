from __future__ import annotations

from netconsole.models.device import Device
from netconsole.models.snmp_models import DeviceSnmpProfileResult, DictionaryRecommendation, ProductReferenceRecommendation
from netconsole.repositories.global_mib_repository import GlobalMibRepository
from netconsole.services.comware_version_service import parse_comware_version


class SnmpRecommendService:
    def __init__(self, repository: GlobalMibRepository) -> None:
        self.repository = repository

    def recommend(self, device: Device, profile: DeviceSnmpProfileResult | None = None) -> list[DictionaryRecommendation]:
        dictionaries = self.repository.list_dictionary_sets()
        profile = profile or DeviceSnmpProfileResult(device_name=device.name, vendor=device.device_vendor or "", device_type=device.device_type or "")
        os_major = profile.os_major or _os_major_from_profile(profile)
        is_h3c = "h3c" in f"{profile.vendor} {device.device_vendor} {profile.sys_descr}".lower()
        is_wireless_ac = _is_wireless_ac(device, profile)
        recommendations: list[DictionaryRecommendation] = []
        for item in dictionaries:
            dictionary_id = int(item["id"])
            score = 0
            reasons: list[str] = []
            name = str(item.get("name") or "")
            if int(item.get("enabled_by_default") or 0):
                score += 60
                reasons.append("默认启用的通用字典")
            if name == "内置通用字典":
                score = max(score, 100)
                reasons.append("标准 SNMP 对象可用于基础信息和接口查询")
            vendor = str(item.get("vendor") or "")
            if vendor and vendor not in {"标准", "通用"} and vendor.lower() in (profile.vendor or device.device_vendor or "").lower():
                score += 25
                reasons.append(f"厂商匹配：{vendor}")
            device_type = str(item.get("device_type") or "")
            if device_type and device_type not in {"通用"} and device_type.lower() in (profile.device_type or device.device_type or "").lower():
                score += 20
                reasons.append(f"设备类型匹配：{device_type}")
            sys_prefix = str(item.get("sysobjectid_prefix") or "")
            if sys_prefix and profile.sys_object_id.startswith(sys_prefix):
                score += 30
                reasons.append(f"sysObjectID 前缀匹配：{sys_prefix}")
            model_pattern = str(item.get("model_pattern") or "")
            if model_pattern and model_pattern.lower() in (profile.model or "").lower():
                score += 20
                reasons.append(f"型号关键词匹配：{model_pattern}")
            os_pattern = str(item.get("os_pattern") or "")
            if os_pattern and os_pattern.lower() in f"{profile.system} {profile.system_version} {profile.sys_descr}".lower():
                score += 15
                reasons.append(f"系统关键词匹配：{os_pattern}")
            if is_h3c and os_major == "V5" and "H3C Comware V5" in name:
                score += 45
                reasons.append("识别为 H3C Comware V5")
            if is_h3c and os_major in {"V7", "V9"} and ("H3C Comware V7/V9" in name or "H3C V7/V9" in name):
                score += 45
                reasons.append(f"识别为 H3C Comware {os_major}")
            if is_wireless_ac and "无线 AC" in name:
                score += 35
                reasons.append("型号或设备类型匹配无线 AC")
            if is_wireless_ac and "Dot11 Mesh" in name:
                score += 20
                reasons.append("无线 AC 可选叠加 Dot11 Mesh 字典")
            if score > 0:
                recommendations.append(DictionaryRecommendation(dictionary_id, name, min(100, score), reasons or ["规则匹配"]))
        return sorted(recommendations, key=lambda item: (-item.score, item.name))

    def recommend_product_references(self, device: Device, profile: DeviceSnmpProfileResult | None = None) -> list[ProductReferenceRecommendation]:
        profile = profile or DeviceSnmpProfileResult(device_name=device.name, vendor=device.device_vendor or "", device_type=device.device_type or "")
        release_series = profile.release_series or parse_comware_version(profile.sys_descr).release_series
        os_major = profile.os_major or _os_major_from_profile(profile)
        is_wireless_ac = _is_wireless_ac(device, profile)
        recommendations: list[ProductReferenceRecommendation] = []
        for row in self.repository.list_product_references():
            score = 0
            reasons: list[str] = []
            name = str(row.get("reference_name") or "")
            vendor = str(row.get("vendor") or "")
            if vendor.lower() == "h3c" and "h3c" in f"{profile.vendor} {device.device_vendor} {profile.sys_descr}".lower():
                score += 20
                reasons.append("厂商匹配 H3C")
            device_type = str(row.get("device_type") or "")
            if is_wireless_ac and device_type == "wireless_ac":
                score += 25
                reasons.append("设备类型匹配无线控制器")
            row_os_major = str(row.get("os_major") or "")
            if row_os_major and os_major and row_os_major == os_major:
                score += 15
                reasons.append(f"Comware 大版本匹配：{os_major}")
            row_series = _split_series(str(row.get("release_series") or ""))
            if release_series and release_series.lower() in {item.lower() for item in row_series}:
                score += 50
                reasons.append(f"设备 Release {profile.release or ''} 属于 {release_series} 系列")
            elif row_series:
                score -= 30
                reasons.append(f"Release 系列不匹配：设备 {release_series or '未知'}，参考表 {','.join(row_series)}")
            if score > 0:
                recommendations.append(ProductReferenceRecommendation(int(row["id"]), name, min(100, score), reasons))
        return sorted(recommendations, key=lambda item: (-item.score, item.reference_name))


def _os_major_from_profile(profile: DeviceSnmpProfileResult) -> str:
    if profile.system_version:
        major = profile.system_version.split(".", 1)[0]
        if major.isdigit():
            return f"V{major}"
    return parse_comware_version(profile.sys_descr).os_major


def _is_wireless_ac(device: Device, profile: DeviceSnmpProfileResult) -> bool:
    text = f"{device.name} {device.device_type} {profile.device_type} {profile.model} {profile.sys_descr}".upper()
    return "WX" in text or "无线" in text or "WIRELESS" in text or "AC" in text


def _split_series(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
